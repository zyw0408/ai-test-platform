from pydantic import BaseModel

class ResourceLock(BaseModel):
    resourceType: str
    resourceId: str
    ownerId: str
    ownerName: str
    acquiredAt: float
    expiresAt: float

class LockResponse(BaseModel):
    success: bool
    lock: ResourceLock | None = None
    message: str | None = None

class LockAcquireReq(BaseModel):
    resourceType: str
    resourceId: str
    ttlSeconds: int = 60

class LockPublic(BaseModel):
    isLocked: bool
    ownerId: str | None = None
    ownerName: str | None = None
    acquiredAt: float | None = None
    expiresAt: float | None = None
