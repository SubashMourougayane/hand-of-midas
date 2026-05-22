"""Auth API — login, logout, me."""
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from backend.auth import login_user, get_current_user
from backend.db import execute

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(req: LoginRequest, response: Response):
    result = login_user(req.email, req.password)
    if "error" in result:
        return {"error": result["error"]}, 401
    response.set_cookie("session_token", result["token"], max_age=30*86400, httponly=True, samesite="lax")
    return result


@router.get("/auth/me")
def me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}, 401
    return {"user": user}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("session_token")
    if token:
        execute("DELETE FROM sessions WHERE token = %s", (token,))
    response.delete_cookie("session_token")
    return {"ok": True}
