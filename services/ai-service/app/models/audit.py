from pydantic import BaseModel, Field
from typing import Any

class AuditLogPublic(BaseModel):
    id: str
    actorId: str | None = None
    action: str
    targetType: str
    targetId: str
    payload: dict[str, Any] | None = None
    createdAt: str

class DashboardReportStats(BaseModel):
    totalRuns: int = 0
    passedRuns: int = 0
    failedRuns: int = 0
    passRate: float = 0.0
    totalCases: int = 0
    totalProjects: int = 0
    avgDurationMs: float = 0.0
    recentRuns: list[dict[str, Any]] = Field(default_factory=list)
    trendData: list[dict[str, Any]] = Field(default_factory=list)
    moduleCoverage: list[dict[str, Any]] = Field(default_factory=list)
