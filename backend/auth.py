"""User authentication — email/password with session tokens (FastAPI + psycopg2)."""
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps
from fastapi import Request, HTTPException

from backend.db import execute


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    salt, hashed = stored_hash.split(":")
    return hashlib.sha256((salt + password).encode()).hexdigest() == hashed


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s, %s, %s)",
        (token, user_id, expires)
    )
    return token


def get_user_from_token(token: str) -> dict | None:
    if not token:
        return None
    rows = execute(
        "SELECT s.user_id, u.email, u.name FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.token = %s AND s.expires_at > NOW()",
        (token,), fetch=True
    )
    if rows:
        return dict(rows[0])
    return None


def login_user(email: str, password: str) -> dict:
    rows = execute(
        "SELECT id, password_hash, name FROM users WHERE email = %s",
        (email,), fetch=True
    )
    if not rows or not verify_password(password, rows[0]["password_hash"]):
        return {"error": "Invalid email or password"}
    user = rows[0]
    execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))
    token = create_session(user["id"])
    return {"token": token, "user": {"id": user["id"], "email": email, "name": user["name"]}}


def get_current_user(request: Request) -> dict | None:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("session_token")
    return get_user_from_token(token)
