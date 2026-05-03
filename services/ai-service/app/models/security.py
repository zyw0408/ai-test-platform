from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from uuid import uuid4

class VulnerabilitySeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

class Vulnerability(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    findingId: str | None = None
    type: str
    severity: VulnerabilitySeverity
    endpoint: str
    method: str
    description: str
    evidence: str | None = None
    remediation: str | None = None

class SecurityScanRequest(BaseModel):
    projectId: str
    collectionIds: list[str] = Field(default_factory=list)
    targetUrl: str | None = None
    maxDiscoveredUrls: int = 8
    scanTypes: list[str] = [
        "owasp_api",
        "pii_scan",
        "auth_bypass",
        "security_headers",
        "cors_misconfig",
        "xss_reflection",
        "error_leak",
        "insecure_transport",
        "idor_enumeration",
        "path_traversal",
        "ssrf_probe",
        "file_upload_security",
        "command_template_injection",
        "jwt_session_security",
        "rate_limit_bruteforce",
    ]
    deepScan: bool = False

class SecurityScanResult(BaseModel):
    scanId: str
    status: str = "completed"
    totalIssues: int = 0
    criticalCount: int = 0
    highCount: int = 0
    mediumCount: int = 0
    lowCount: int = 0
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    startTime: datetime = Field(default_factory=datetime.now)
    endTime: datetime | None = None


class SecurityFindingStatus(str, Enum):
    OPEN = "open"
    FIXED = "fixed"
    RETEST = "retest"


class SecurityFinding(BaseModel):
    id: str
    projectId: str
    scanId: str | None = None
    signature: str
    type: str
    severity: VulnerabilitySeverity
    endpoint: str
    method: str
    description: str
    evidence: str | None = None
    remediation: str | None = None
    status: SecurityFindingStatus = SecurityFindingStatus.OPEN
    createdAt: str
    updatedAt: str
    resolvedAt: str | None = None
