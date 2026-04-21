

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

import jwt  # PyJWT
from fastapi import Header, HTTPException

from .config import get_settings


def issue_token(profile: Dict[str, Any]) -> str:
    """
    Create a signed JWT carrying the user's profile.

    `profile` is the dict shape used elsewhere in the app
    ({email, employee_id, name, department, manager, role}).
    """
    s = get_settings()
    now = int(time.time())
    claims = {
        "sub": profile.get("employee_id") or profile.get("email"),
        "iat": now,
        "nbf": now,
        "exp": now + s.JWT_EXPIRES_HOURS * 3600,
        "jti": str(uuid.uuid4()),
        "profile": profile,
    }
    return jwt.encode(claims, s.JWT_SECRET, algorithm=s.JWT_ALG)


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify a token and return the embedded profile.

    Raises HTTPException(401) on any failure. We deliberately don't leak
    why the token is invalid to the client.
    """
    s = get_settings()
    try:
        claims = jwt.decode(token, s.JWT_SECRET, algorithms=[s.JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    profile = claims.get("profile")
    if not isinstance(profile, dict):
        raise HTTPException(status_code=401, detail="Malformed token")
    return profile


async def auth_required(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """FastAPI dependency. Returns the authenticated profile or raises 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    return verify_token(token)


async def require_roles(*roles: str):
    """
    Dependency factory for role-based checks.

    Usage:
        @app.get("/x", dependencies=[Depends(require_roles("hr", "admin"))])
    """
    allowed = {r.lower() for r in roles}

    async def _dep(profile: Dict[str, Any] = None, authorization: Optional[str] = Header(None)):
        profile = await auth_required(authorization)
        role = (profile.get("role") or "").lower()
        if role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return profile

    return _dep
