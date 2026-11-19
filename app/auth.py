"""Demo role credentials. Individual identity/SSO is a later deployment requirement."""

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


def get_role(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    if credentials and credentials.scheme.lower() == "bearer":
        for role in ("agent", "manager", "auditor"):
            configured = getattr(settings, f"{role}_api_key").get_secret_value()
            if secrets.compare_digest(credentials.credentials.encode(), configured.encode()):
                return role
    raise HTTPException(
        401, "Valid bearer credential required", headers={"WWW-Authenticate": "Bearer"}
    )


def require_writer(role: str = Depends(get_role)) -> str:
    if role not in {"agent", "manager"}:
        raise HTTPException(403, "Auditors have read-only access")
    return role
