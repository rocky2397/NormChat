import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    valid = secrets.compare_digest(
        payload.username, settings.auth_username
    ) and secrets.compare_digest(payload.password, settings.auth_password)
    if not valid:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten.")
    request.session["authenticated"] = True
    return {"ok": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    if _auth_disabled():
        return {"authenticated": True}
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    return {"authenticated": True}


def _auth_disabled() -> bool:
    return not settings.auth_username or not settings.auth_password


def require_auth(request: Request):
    if _auth_disabled():
        return
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
