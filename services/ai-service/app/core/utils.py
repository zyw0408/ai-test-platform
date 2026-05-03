from datetime import datetime
from uuid import uuid4

def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
