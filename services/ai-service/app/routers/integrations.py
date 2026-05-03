from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Any, List
from .deps import get_admin_user, get_smithery
from ..models import (
    SmitheryStatus,
    McpRecommendation,
    SmitherySearchResponse,
    SmitheryCommandResult,
    SmitheryConnectRequest,
    SmitheryToolListResponse,
    SmitheryToolCallRequest,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])

@router.get("/smithery/status", response_model=SmitheryStatus)
async def smithery_status(
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> SmitheryStatus:
    return smithery.status()

@router.get("/mcp/recommendations", response_model=List[McpRecommendation])
async def list_mcp_recommendations(
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> List[McpRecommendation]:
    return smithery.recommendations()

@router.get("/smithery/search", response_model=SmitherySearchResponse)
async def smithery_search(
    q: str = Query(..., min_length=1),
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> SmitherySearchResponse:
    return SmitherySearchResponse(query=q, result=smithery.search(q))

@router.get("/smithery/connections", response_model=SmitheryCommandResult)
async def smithery_connections(
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> SmitheryCommandResult:
    return smithery.list_connections()

@router.post("/smithery/connections", response_model=SmitheryCommandResult)
async def smithery_connect(
    payload: SmitheryConnectRequest,
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> SmitheryCommandResult:
    return smithery.add_connection(
        server=payload.server,
        connection_id=payload.connectionId,
        metadata=payload.metadata,
    )

@router.get("/smithery/connections/{connection_id}/tools", response_model=SmitheryToolListResponse)
async def smithery_tools(
    connection_id: str,
    prefix: str | None = Query(None),
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> SmitheryToolListResponse:
    return SmitheryToolListResponse(
        connectionId=connection_id,
        prefix=prefix,
        result=smithery.list_tools(connection_id, prefix),
    )


@router.get("/smithery/connections/{connection_id}/tools/{tool_name}", response_model=SmitheryCommandResult)
async def smithery_tool_detail(
    connection_id: str,
    tool_name: str,
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> SmitheryCommandResult:
    return smithery.get_tool(connection_id, tool_name)


@router.post("/smithery/connections/{connection_id}/tools/{tool_name}/call", response_model=SmitheryCommandResult)
async def smithery_tool_call(
    connection_id: str,
    tool_name: str,
    payload: SmitheryToolCallRequest,
    _: dict = Depends(get_admin_user),
    smithery: Any = Depends(get_smithery),
) -> SmitheryCommandResult:
    return smithery.call_tool(connection_id, tool_name, payload.payload)
