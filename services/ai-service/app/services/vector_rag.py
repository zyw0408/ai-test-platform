from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.database import Database
from app.models import new_id, utc_now


@dataclass(slots=True)
class RetrievedChunk:
    id: str
    project_id: str | None
    module: str
    source_id: str
    title: str
    content: str
    score: float
    updated_at: str
    meta: dict[str, Any]


class VectorRAGService:
    def __init__(self, *, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.vector_enabled)

    async def rebuild_index(self, *, project_id: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "indexed": 0, "projectId": project_id}
        rows = self._collect_source_rows(project_id=project_id)
        prepared: list[dict[str, Any]] = []
        for row in rows:
            chunks = self._chunk_text(str(row.get("content") or ""))
            for idx, chunk in enumerate(chunks):
                prepared.append(
                    {
                        "project_id": row.get("project_id"),
                        "module": str(row.get("module") or "unknown"),
                        "source_id": str(row.get("source_id") or ""),
                        "chunk_index": idx,
                        "title": str(row.get("title") or ""),
                        "content": chunk,
                        "updated_at": str(row.get("updated_at") or utc_now()),
                        "meta": row.get("meta") if isinstance(row.get("meta"), dict) else {},
                    }
                )
        if not prepared:
            if project_id:
                self._db.execute("DELETE FROM vector_documents WHERE project_id = ?", (project_id,))
            return {"enabled": True, "indexed": 0, "projectId": project_id}

        embeddings = await self._embed_texts([item["content"] for item in prepared])
        if len(embeddings) != len(prepared):
            raise RuntimeError("embedding 结果数量与待索引文本数量不一致")

        if project_id:
            self._db.execute("DELETE FROM vector_documents WHERE project_id = ?", (project_id,))
        else:
            self._db.execute("DELETE FROM vector_documents")

        now = utc_now()
        for item, emb in zip(prepared, embeddings):
            self._db.execute(
                """
                INSERT INTO vector_documents (
                    id, project_id, module, source_id, chunk_index, title, content, embedding_json, meta_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("vec"),
                    item["project_id"],
                    item["module"],
                    item["source_id"],
                    int(item["chunk_index"]),
                    item["title"],
                    item["content"],
                    json.dumps(emb, ensure_ascii=False),
                    json.dumps(item["meta"], ensure_ascii=False),
                    now,
                    item["updated_at"] or now,
                ),
            )
        return {"enabled": True, "indexed": len(prepared), "projectId": project_id}

    async def search(
        self,
        *,
        query: str,
        project_id: str | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        if not self.enabled:
            return []
        text = str(query or "").strip()
        if not text:
            return []
        k = max(1, min(int(top_k or self._settings.vector_top_k), 30))
        query_emb = (await self._embed_texts([text]))[0]

        if project_id:
            rows = self._db.fetchall(
                """
                SELECT id, project_id, module, source_id, title, content, embedding_json, meta_json, updated_at
                FROM vector_documents
                WHERE project_id = ?
                """,
                (project_id,),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT id, project_id, module, source_id, title, content, embedding_json, meta_json, updated_at
                FROM vector_documents
                """
            )
        scored: list[RetrievedChunk] = []
        for row in rows:
            try:
                emb = json.loads(str(row.get("embedding_json") or "[]"))
                if not isinstance(emb, list):
                    continue
                score = self._cosine(query_emb, [float(v) for v in emb])
            except Exception:
                continue
            try:
                meta = json.loads(str(row.get("meta_json") or "{}"))
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            scored.append(
                RetrievedChunk(
                    id=str(row.get("id") or ""),
                    project_id=str(row.get("project_id") or "") or None,
                    module=str(row.get("module") or ""),
                    source_id=str(row.get("source_id") or ""),
                    title=str(row.get("title") or ""),
                    content=str(row.get("content") or ""),
                    score=float(score),
                    updated_at=str(row.get("updated_at") or ""),
                    meta=meta,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:k]

    async def build_context_for_query(
        self,
        *,
        query: str,
        project_id: str | None = None,
    ) -> str:
        chunks = await self.search(query=query, project_id=project_id, top_k=self._settings.vector_max_context_chunks)
        if not chunks:
            return ""
        lines = ["### RAG 检索上下文（请优先基于这些证据回答）"]
        for idx, item in enumerate(chunks, start=1):
            header = f"[{idx}] module={item.module} source={item.source_id} score={item.score:.4f}"
            if item.title:
                header += f" title={item.title}"
            if item.updated_at:
                header += f" updatedAt={item.updated_at}"
            lines.append(header)
            lines.append(item.content[:1000])
        return "\n".join(lines)

    def _collect_source_rows(self, *, project_id: str | None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if project_id:
            req_rows = self._db.fetchall(
                "SELECT id, project_id, title, content, updated_at FROM requirements WHERE deleted_at IS NULL AND project_id = ?",
                (project_id,),
            )
        else:
            req_rows = self._db.fetchall(
                "SELECT id, project_id, title, content, updated_at FROM requirements WHERE deleted_at IS NULL"
            )
        for row in req_rows:
            rows.append(
                {
                    "project_id": row.get("project_id"),
                    "module": "requirements",
                    "source_id": row.get("id"),
                    "title": row.get("title") or "",
                    "content": row.get("content") or "",
                    "updated_at": row.get("updated_at") or utc_now(),
                    "meta": {},
                }
            )

        try:
            if project_id:
                spec_rows = self._db.fetchall(
                    "SELECT id, project_id, title, content, updated_at FROM source_specs WHERE project_id = ?",
                    (project_id,),
                )
            else:
                spec_rows = self._db.fetchall("SELECT id, project_id, title, content, updated_at FROM source_specs")
        except Exception:
            if project_id:
                spec_rows = self._db.fetchall(
                    "SELECT id, project_id, name AS title, content, updated_at FROM source_specs WHERE project_id = ?",
                    (project_id,),
                )
            else:
                spec_rows = self._db.fetchall("SELECT id, project_id, name AS title, content, updated_at FROM source_specs")
        for row in spec_rows:
            rows.append(
                {
                    "project_id": row.get("project_id"),
                    "module": "source_specs",
                    "source_id": row.get("id"),
                    "title": row.get("title") or "",
                    "content": row.get("content") or "",
                    "updated_at": row.get("updated_at") or utc_now(),
                    "meta": {},
                }
            )

        try:
            if project_id:
                case_rows = self._db.fetchall(
                    """
                    SELECT id, project_id, title, objective, steps_json, assertion_hints_json, updated_at
                    FROM cases
                    WHERE deleted_at IS NULL AND project_id = ?
                    """,
                    (project_id,),
                )
            else:
                case_rows = self._db.fetchall(
                    """
                    SELECT id, project_id, title, objective, steps_json, assertion_hints_json, updated_at
                    FROM cases
                    WHERE deleted_at IS NULL
                    """
                )
        except Exception:
            if project_id:
                case_rows = self._db.fetchall(
                    """
                    SELECT id, project_id, title, '' AS objective, steps_json, '[]' AS assertion_hints_json, updated_at
                    FROM cases
                    WHERE deleted_at IS NULL AND project_id = ?
                    """,
                    (project_id,),
                )
            else:
                case_rows = self._db.fetchall(
                    """
                    SELECT id, project_id, title, '' AS objective, steps_json, '[]' AS assertion_hints_json, updated_at
                    FROM cases
                    WHERE deleted_at IS NULL
                    """
                )
        for row in case_rows:
            steps = self._json_list_to_text(row.get("steps_json"))
            assertions = self._json_list_to_text(row.get("assertion_hints_json"))
            content = f"{row.get('title') or ''}\n目标: {row.get('objective') or ''}\n步骤: {steps}\n断言: {assertions}"
            rows.append(
                {
                    "project_id": row.get("project_id"),
                    "module": "cases",
                    "source_id": row.get("id"),
                    "title": row.get("title") or "",
                    "content": content,
                    "updated_at": row.get("updated_at") or utc_now(),
                    "meta": {},
                }
            )

        if project_id:
            sec_rows = self._db.fetchall(
                """
                SELECT id, project_id, type, severity, endpoint, method, description, remediation, updated_at
                FROM security_findings
                WHERE project_id = ?
                """,
                (project_id,),
            )
        else:
            sec_rows = self._db.fetchall(
                """
                SELECT id, project_id, type, severity, endpoint, method, description, remediation, updated_at
                FROM security_findings
                """
            )
        for row in sec_rows:
            content = (
                f"type={row.get('type')} severity={row.get('severity')} "
                f"{row.get('method')} {row.get('endpoint')}\n"
                f"description: {row.get('description') or ''}\n"
                f"remediation: {row.get('remediation') or ''}"
            )
            rows.append(
                {
                    "project_id": row.get("project_id"),
                    "module": "security_findings",
                    "source_id": row.get("id"),
                    "title": str(row.get("type") or ""),
                    "content": content,
                    "updated_at": row.get("updated_at") or utc_now(),
                    "meta": {},
                }
            )

        return rows

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        # Try remote embedding endpoint first when configured, then fallback to deterministic local hash embedding.
        model = self._settings.vector_embedding_model
        base_url = self._settings.vector_embedding_base_url or self._settings.model_base_url
        api_key = self._settings.vector_embedding_api_key or self._settings.model_api_key
        if model and base_url and api_key:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=True) as client:
                    resp = await client.post(
                        f"{str(base_url).rstrip('/')}/embeddings",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {api_key}",
                        },
                        json={"model": model, "input": texts},
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if isinstance(data, list) and len(data) == len(texts):
                        vectors: list[list[float]] = []
                        for item in data:
                            embedding = item.get("embedding") if isinstance(item, dict) else None
                            if not isinstance(embedding, list):
                                raise ValueError("invalid embedding payload")
                            vectors.append([float(v) for v in embedding[: self._settings.vector_dim]])
                        return [self._fit_dim(v) for v in vectors]
            except Exception:
                pass
        return [self._local_hash_embedding(text) for text in texts]

    def _local_hash_embedding(self, text: str) -> list[float]:
        dim = max(16, int(self._settings.vector_dim))
        vec = [0.0] * dim
        normalized = str(text or "").lower()
        tokens = [tok for tok in re_split_tokens(normalized) if tok]
        if not tokens:
            return vec
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vec[idx] += sign * weight
        return self._normalize(vec)

    def _fit_dim(self, vec: list[float]) -> list[float]:
        dim = max(16, int(self._settings.vector_dim))
        if len(vec) > dim:
            vec = vec[:dim]
        elif len(vec) < dim:
            vec = vec + [0.0] * (dim - len(vec))
        return self._normalize(vec)

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 1e-12:
            return vec
        return [v / norm for v in vec]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return -1.0
        size = min(len(a), len(b))
        return sum(float(a[i]) * float(b[i]) for i in range(size))

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        lines = [ln.strip() for ln in raw.replace("\r\n", "\n").split("\n") if ln.strip()]
        chunks: list[str] = []
        buf: list[str] = []
        max_len = 1200
        for line in lines:
            candidate = ("\n".join(buf + [line])).strip()
            if len(candidate) <= max_len:
                buf.append(line)
                continue
            if buf:
                chunks.append("\n".join(buf).strip())
                buf = [line]
            else:
                chunks.append(line[:max_len])
        if buf:
            chunks.append("\n".join(buf).strip())
        return chunks

    @staticmethod
    def _json_list_to_text(raw: Any) -> str:
        if isinstance(raw, list):
            return "; ".join(str(item) for item in raw if str(item).strip())
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return "; ".join(str(item) for item in parsed if str(item).strip())
            except json.JSONDecodeError:
                return raw.strip()
        return ""


def re_split_tokens(text: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in {"_", "-", "."}:
            current.append(ch)
        else:
            if current:
                result.append("".join(current))
                current = []
    if current:
        result.append("".join(current))
    return result
