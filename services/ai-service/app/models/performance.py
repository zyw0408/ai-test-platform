from pydantic import BaseModel, Field
from typing import Any

class PerformanceRunRequest(BaseModel):
    collectionId: str
    projectId: str
    environmentId: str | None = None
    requestIds: list[str] | None = None
    vus: int = Field(default=10, ge=1, le=1000)
    durationSeconds: int = Field(default=30, ge=5, le=600)
    rampUpSeconds: int = Field(default=5, ge=0, le=60)
    targetTps: int | None = Field(default=None, ge=1)
    slaMaxP95Latency: float | None = None
    slaMaxErrorRate: float | None = None
    dataFileUri: str | None = None
    timeoutMs: int = Field(default=15000, ge=500, le=120000)
    verifySsl: bool = True
    tls: dict[str, Any] | None = None

class PerformancePoint(BaseModel):
    timestamp: float
    tps: float
    latencyMs: float
    errorRate: float

class PerformanceRunResult(BaseModel):
    runId: str
    totalRequests: int
    successCount: int
    failCount: int
    avgLatencyMs: float
    p95LatencyMs: float
    p99LatencyMs: float
    maxLatencyMs: float
    tps: float
    timeSeries: list[PerformancePoint] = Field(default_factory=list)
    status: str = "completed"
    passedSla: bool = True
    errorMsg: str | None = None
