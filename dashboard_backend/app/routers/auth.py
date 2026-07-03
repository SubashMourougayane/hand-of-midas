"""Single shared-login auth for the terminal.

One username + password (from env MIDAS_AUTH_USER / MIDAS_AUTH_PASS). The
password is validated server-side ONLY — it never ships in the frontend bundle.
On success we mint a compact HMAC-signed token (payload = username + expiry)
that the SPA stores and replays; `/api/auth/verify` re-checks it on app load.

Closed-desk scope: this gates entry to the terminal. Data GET endpoints + the
WS remain open on the private box; the login wall is the front door.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 24h sessions. Change creds via env on the box; secret rotates all tokens.
_TTL_SECONDS = 24 * 60 * 60


def _user() -> str:
    return os.environ.get("MIDAS_AUTH_USER", "subashtrades.in@gmail.com")


def _password() -> str:
    return os.environ.get("MIDAS_AUTH_PASS", "9994605758")


def _secret() -> bytes:
    # Signing key: dedicated secret if set, else derived from the password so a
    # password change also invalidates every outstanding token.
    raw = os.environ.get("MIDAS_AUTH_SECRET") or f"hom::{_password()}"
    return raw.encode("utf-8")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: dict) -> str:
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginBody) -> dict:
    # Constant-time compare on both fields to avoid revealing which was wrong.
    user_ok = hmac.compare_digest(body.username.strip(), _user())
    pass_ok = hmac.compare_digest(body.password, _password())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    exp = int(time.time()) + _TTL_SECONDS
    token = _sign({"u": _user(), "exp": exp})
    return {"token": token, "username": _user(), "exp": exp}


@router.get("/verify")
def verify(authorization: str | None = Header(default=None)) -> dict:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    payload = _verify(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return {"ok": True, "username": payload.get("u"), "exp": payload.get("exp")}
