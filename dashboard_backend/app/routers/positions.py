"""POST /api/positions/{ticket}/close — auth-guarded manual close.

Mutating + money-affecting → unlike the read-only GET routes this REQUIRES a
valid session bearer token (the same HMAC token minted by /api/auth/login).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_session
from ..services.positions import PositionCloseError, close_position
from .auth import _verify

router = APIRouter(prefix="/api/positions", tags=["positions"])


def require_auth(authorization: str | None = Header(default=None)) -> str:
    """Verify the bearer token; return the username (used as the audit actor)."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    payload = _verify(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return str(payload.get("u", "dashboard"))


@router.post("/{ticket}/close")
def close(
    ticket: str,
    actor: str = Depends(require_auth),
    s: Session = Depends(get_session),
) -> dict:
    try:
        return close_position(ticket, s, actor=actor)
    except PositionCloseError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
