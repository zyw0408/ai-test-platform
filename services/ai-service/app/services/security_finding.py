from __future__ import annotations

from typing import Any

from app.database import Database
from app.models import (
    SecurityFinding,
    SecurityFindingStatus,
    Vulnerability,
    new_id,
    utc_now,
)


class SecurityFindingService:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def make_signature(vuln: Vulnerability) -> str:
        return "|".join(
            [
                str(vuln.type or "").strip().lower(),
                str(vuln.severity or "").strip().lower(),
                str(vuln.method or "").strip().upper(),
                str(vuln.endpoint or "").strip(),
                str(vuln.description or "").strip(),
            ]
        )

    def upsert_from_scan(
        self,
        *,
        project_id: str,
        scan_id: str,
        vulnerabilities: list[Vulnerability],
    ) -> dict[str, dict[str, str]]:
        now = utc_now()
        result: dict[str, dict[str, str]] = {}
        for vuln in vulnerabilities:
            signature = self.make_signature(vuln)
            if not signature:
                continue
            existing = self._db.fetchone(
                """
                SELECT id, status
                FROM security_findings
                WHERE project_id = ? AND signature = ?
                """,
                (project_id, signature),
            )
            if existing:
                finding_id = str(existing["id"])
                self._db.execute(
                    """
                    UPDATE security_findings
                    SET scan_id = ?, type = ?, severity = ?, endpoint = ?, method = ?, description = ?,
                        evidence = ?, remediation = ?, status = ?, resolved_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        scan_id,
                        vuln.type,
                        vuln.severity,
                        vuln.endpoint,
                        vuln.method,
                        vuln.description,
                        vuln.evidence,
                        vuln.remediation,
                        SecurityFindingStatus.OPEN.value,
                        now,
                        finding_id,
                    ),
                )
            else:
                finding_id = new_id("secf")
                self._db.execute(
                    """
                    INSERT INTO security_findings (
                        id, project_id, scan_id, signature, type, severity, endpoint, method, description,
                        evidence, remediation, status, resolved_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding_id,
                        project_id,
                        scan_id,
                        signature,
                        vuln.type,
                        vuln.severity,
                        vuln.endpoint,
                        vuln.method,
                        vuln.description,
                        vuln.evidence,
                        vuln.remediation,
                        SecurityFindingStatus.OPEN.value,
                        None,
                        now,
                        now,
                    ),
                )
            result[signature] = {"id": finding_id, "status": SecurityFindingStatus.OPEN.value}
        return result

    def list_findings(
        self,
        *,
        project_id: str,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where_parts = ["project_id = ?"]
        params: list[Any] = [project_id]
        if status:
            where_parts.append("status = ?")
            params.append(status)
        if severity:
            where_parts.append("severity = ?")
            params.append(severity)
        rows = self._db.fetchall(
            f"""
            SELECT *
            FROM security_findings
            WHERE {' AND '.join(where_parts)}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            tuple([*params, max(1, min(limit, 500))]),
        )
        return [self._row_to_finding(item).model_dump() for item in rows]

    def update_status(
        self,
        *,
        finding_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        normalized = str(status or "").strip().lower()
        if normalized not in {
            SecurityFindingStatus.OPEN.value,
            SecurityFindingStatus.FIXED.value,
            SecurityFindingStatus.RETEST.value,
        }:
            raise ValueError("status 必须是 open/fixed/retest")
        now = utc_now()
        resolved_at = now if normalized == SecurityFindingStatus.FIXED.value else None
        affected = self._db.execute(
            """
            UPDATE security_findings
            SET status = ?, resolved_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (normalized, resolved_at, now, finding_id),
        )
        if int(affected or 0) <= 0:
            return None
        row = self._db.fetchone("SELECT * FROM security_findings WHERE id = ?", (finding_id,))
        if not row:
            return None
        return self._row_to_finding(row).model_dump()

    @staticmethod
    def _row_to_finding(row: dict[str, Any]) -> SecurityFinding:
        return SecurityFinding(
            id=row["id"],
            projectId=row["project_id"],
            scanId=row.get("scan_id"),
            signature=row.get("signature", ""),
            type=row.get("type", ""),
            severity=row.get("severity", "info"),
            endpoint=row.get("endpoint", ""),
            method=row.get("method", ""),
            description=row.get("description", ""),
            evidence=row.get("evidence"),
            remediation=row.get("remediation"),
            status=row.get("status", "open"),
            createdAt=row.get("created_at", ""),
            updatedAt=row.get("updated_at", ""),
            resolvedAt=row.get("resolved_at"),
        )
