from fastapi import APIRouter, Depends, HTTPException, Query, status, Response, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import Any, List, Optional
import logging
import json
from datetime import datetime, timezone

from .deps import (
    get_current_user, 
    require_roles, 
    get_requirement_analysis, 
    get_analysis_queue,
    get_ai_chat,
    get_api_testing,
    get_user_auth,
    get_vector_rag,
)
from app.services.ai_chat import AIChatService
from app.services.vector_rag import VectorRAGService
from app.models.ai import AIChatRequest
from app.models.requirements import AiOperationPublic, RequirementAnalyzeResult
from app.models.testing import TestCase
from app.services.case_generation import generate_cases
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger(__name__)

@router.get("/ops/{operation_id}", response_model=AiOperationPublic)
async def get_ai_operation(
    operation_id: str,
    _: dict = Depends(get_current_user),
    ai_service: Any = Depends(get_requirement_analysis),
) -> AiOperationPublic:
    operation = ai_service.get_ai_operation(operation_id)
    if not operation:
        raise HTTPException(status_code=404, detail="ai operation not found")
    return AiOperationPublic.model_validate(operation)

@router.post("/ops/{operation_id}/run", response_model=RequirementAnalyzeResult)
async def run_ai_operation(
    operation_id: str,
    current_user: dict = Depends(require_roles("admin", "tester")),
    ai_service: Any = Depends(get_requirement_analysis),
) -> RequirementAnalyzeResult:
    try:
        result = await ai_service.execute_operation(operation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    return RequirementAnalyzeResult.model_validate(result)

@router.post("/cases/generate", response_model=List[TestCase])
async def ai_generate_cases(
    specId: str,
    projectId: str,
    kinds: List[str] = Query(["api", "ui"]),
    current_user: dict = Depends(require_roles("admin", "tester")),
    ai_testing: Any = Depends(get_api_testing), # to fetch spec
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    # Fetch spec content
    spec_data = ai_testing.get_spec(specId)
    if not spec_data:
        raise HTTPException(status_code=404, detail="Spec not found")
    
    from app.models import SourceSpec
    spec = SourceSpec.model_validate(dict(spec_data))
    
    # Generate
    provider = ai_chat.get_provider() # Helper method needed in AIChatService
    cases = await generate_cases(
        provider=provider,
        spec=spec,
        project_id=projectId,
        kinds=kinds
    )
    return cases

@router.post("/chat")
async def ai_chat_stream(
    payload: AIChatRequest,
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
    vector_rag: VectorRAGService = Depends(get_vector_rag),
    user_auth = Depends(get_user_auth),
):
    user_settings = user_auth.get_user_settings(current_user["id"])
    runtime_config = ai_chat.resolve_runtime_config(user_settings)
    model_name = str(runtime_config.get("model") or "")

    normalized_messages = [item.model_dump() for item in payload.messages]
    latest_user = next(
        (msg for msg in reversed(normalized_messages) if str(msg.get("role") or "") == "user"),
        None,
    )
    latest_user_text = str(latest_user.get("content") or "").strip() if latest_user else ""
    rag_context = ""
    if latest_user_text and vector_rag.enabled:
        try:
            rag_context = await vector_rag.build_context_for_query(
                query=latest_user_text,
                project_id=(payload.projectId or "").strip() or None,
            )
        except Exception:
            rag_context = ""
    prepared = ai_chat.prepare_chat_turn(
        user_id=current_user["id"],
        messages=normalized_messages,
        session_id=payload.sessionId,
        project_id=(payload.projectId or "").strip() or None,
        page=(payload.page or "").strip() or None,
        context=payload.context,
        rag_context=rag_context,
        runtime_config=runtime_config,
    )
    session_id = str(prepared["sessionId"])
    task_type = str(prepared["taskType"])
    agents_used = [str(item) for item in prepared["agentsUsed"]]
    tools_available = [str(item) for item in prepared.get("toolsAvailable", [])]
    mcp_available = prepared.get("mcpAvailable") if isinstance(prepared.get("mcpAvailable"), list) else []

    if latest_user:
        ai_chat.append_chat_message(
            user_id=current_user["id"],
            session_id=session_id,
            project_id=(payload.projectId or "").strip() or None,
            task_type=task_type,
            agent_key="orchestrator",
            role="user",
            content=str(latest_user.get("content") or ""),
            meta={"page": payload.page, "agentsUsed": agents_used},
        )

    if payload.stream:
        async def _stream_with_persistence():
            assistant_parts: list[str] = []
            yield "data: " + json.dumps(
                {
                    "event": "metadata",
                    "sessionId": session_id,
                    "taskType": task_type,
                    "agentsUsed": agents_used,
                    "toolsAvailable": tools_available,
                    "mcpAvailable": mcp_available,
                    "model": model_name,
                },
                ensure_ascii=False,
            ) + "\n\n"
            async for chunk in ai_chat.chat_stream(
                prepared["messages"],
                context=prepared["context"],
                runtime_config=prepared["runtimeConfig"],
                actor_id=current_user["id"],
            ):
                if isinstance(chunk, str) and chunk.startswith("data: "):
                    data_str = chunk[6:].strip()
                    if data_str and data_str != "[DONE]":
                        try:
                            parsed = json.loads(data_str)
                            if isinstance(parsed, dict):
                                content_piece = str(parsed.get("content") or "")
                                if content_piece:
                                    assistant_parts.append(content_piece)
                        except json.JSONDecodeError:
                            pass
                yield chunk
            final_text = "".join(assistant_parts).strip()
            if final_text:
                ai_chat.append_chat_message(
                    user_id=current_user["id"],
                    session_id=session_id,
                    project_id=(payload.projectId or "").strip() or None,
                    task_type=task_type,
                    agent_key="orchestrator",
                    role="assistant",
                    content=final_text,
                    model=model_name,
                    meta={"agentsUsed": agents_used},
                )
                ai_chat.maybe_summarize_session(session_id=session_id, user_id=current_user["id"])

        return StreamingResponse(
            _stream_with_persistence(),
            media_type="text/event-stream",
        )

    content = await ai_chat.chat(
        prepared["messages"],
        context=prepared["context"],
        runtime_config=prepared["runtimeConfig"],
    )
    ai_chat.append_chat_message(
        user_id=current_user["id"],
        session_id=session_id,
        project_id=(payload.projectId or "").strip() or None,
        task_type=task_type,
        agent_key="orchestrator",
        role="assistant",
        content=content,
        model=model_name,
        meta={"agentsUsed": agents_used},
    )
    ai_chat.maybe_summarize_session(session_id=session_id, user_id=current_user["id"])
    return {
        "content": content,
        "model": model_name,
        "sessionId": session_id,
        "taskType": task_type,
        "agentsUsed": agents_used,
        "toolsAvailable": tools_available,
        "mcpAvailable": mcp_available,
    }


@router.post("/rag/reindex")
async def ai_rag_reindex(
    payload: dict[str, Any],
    current_user: dict = Depends(require_roles("admin", "tester")),
    vector_rag: VectorRAGService = Depends(get_vector_rag),
):
    project_id = str(payload.get("projectId") or "").strip() or None
    result = await vector_rag.rebuild_index(project_id=project_id)
    return result


@router.post("/rag/search")
async def ai_rag_search(
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    vector_rag: VectorRAGService = Depends(get_vector_rag),
):
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    project_id = str(payload.get("projectId") or "").strip() or None
    top_k = int(payload.get("topK") or 8)
    rows = await vector_rag.search(query=query, project_id=project_id, top_k=top_k)
    return {
        "items": [
            {
                "id": item.id,
                "projectId": item.project_id,
                "module": item.module,
                "sourceId": item.source_id,
                "title": item.title,
                "content": item.content,
                "score": item.score,
                "updatedAt": item.updated_at,
                "meta": item.meta,
            }
            for item in rows
        ]
    }


@router.get("/prompt-templates")
async def list_ai_prompt_templates(
    current_user: dict = Depends(require_roles("admin", "tester")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    return {"items": ai_chat.list_prompt_templates()}


@router.patch("/prompt-templates/{task_type}")
async def update_ai_prompt_template(
    task_type: str,
    payload: dict[str, Any],
    current_user: dict = Depends(require_roles("admin")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    try:
        return ai_chat.update_prompt_template(task_type, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agents")
async def list_ai_agents(
    current_user: dict = Depends(require_roles("admin", "tester")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    return {"items": ai_chat.list_agents()}


@router.patch("/agents/{key}")
async def update_ai_agent(
    key: str,
    payload: dict[str, Any],
    current_user: dict = Depends(require_roles("admin")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    try:
        return ai_chat.update_agent(key, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hooks")
async def list_ai_hooks(
    current_user: dict = Depends(require_roles("admin", "tester")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    return {"items": ai_chat.list_hooks()}


@router.patch("/hooks/{key}")
async def update_ai_hook(
    key: str,
    payload: dict[str, Any],
    current_user: dict = Depends(require_roles("admin")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    try:
        return ai_chat.update_hook(key, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="hook not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/plugins")
async def list_ai_plugins(
    current_user: dict = Depends(require_roles("admin", "tester")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    return {"items": ai_chat.list_plugins()}


@router.patch("/plugins/{key}")
async def update_ai_plugin(
    key: str,
    payload: dict[str, Any],
    current_user: dict = Depends(require_roles("admin")),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    try:
        return ai_chat.update_plugin(key, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="plugin not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/chat/sessions")
async def list_ai_chat_sessions(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    return {"items": ai_chat.list_chat_sessions(user_id=current_user["id"], limit=limit)}


@router.post("/chat/sessions")
async def create_ai_chat_session(
    payload: dict[str, Any],
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    return ai_chat.ensure_chat_session(
        user_id=current_user["id"],
        session_id=str(payload.get("sessionId") or "").strip() or None,
        project_id=str(payload.get("projectId") or "").strip() or None,
        title=str(payload.get("title") or "").strip() or None,
    )


@router.get("/chat/sessions/{session_id}")
async def get_ai_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    session = ai_chat.get_chat_session(session_id=session_id, user_id=current_user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    messages = ai_chat.list_chat_messages(user_id=current_user["id"], session_id=session_id, limit=100)
    return {**session, "messages": messages}


@router.delete("/chat/sessions/{session_id}")
async def delete_ai_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    deleted = ai_chat.delete_chat_session(session_id=session_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": True}


@router.post("/chat/sessions/{session_id}/summarize")
async def summarize_ai_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    session = ai_chat.get_chat_session(session_id=session_id, user_id=current_user["id"])
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return ai_chat.summarize_chat_session(session_id=session_id, user_id=current_user["id"])

@router.get("/chat/history")
async def get_ai_chat_history(
    limit: int = Query(80, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    return {
        "items": ai_chat.list_chat_messages(user_id=current_user["id"], limit=limit),
    }

@router.delete("/chat/history")
async def clear_ai_chat_history(
    current_user: dict = Depends(get_current_user),
    ai_chat: AIChatService = Depends(get_ai_chat),
):
    deleted = ai_chat.clear_chat_messages(user_id=current_user["id"])
    return {"deleted": deleted}
