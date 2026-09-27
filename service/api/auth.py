"""Прототип авторизации: регистрация и вход по OAuth2 Password Flow, токен JWT.

Пользователи — PostgreSQL (таблица users, см. store.py). Пароли — PBKDF2-SHA256 с солью.
Секрет JWT — переменная AUTH_SECRET или файл AUTH_DIR/jwt_secret, создаётся один раз и общий для всех воркеров.
Это прототип для демонстрации, а не промышленная система доступа (нет ролей, сброса пароля, ограничения попыток).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from store import add_user, get_user

AUTH_DIR = Path(os.environ.get("AUTH_DIR", "/app/auth"))
TOKEN_TTL_H = float(os.environ.get("TOKEN_TTL_HOURS", "12"))
ALGO = "HS256"
router = APIRouter(prefix="/auth", tags=["Авторизация"])
oauth2 = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


def _secret() -> str:
    if os.environ.get("AUTH_SECRET"):
        return os.environ["AUTH_SECRET"]
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    f = AUTH_DIR / "jwt_secret"
    try:                                     # создаётся ровно один раз, даже если воркеры стартуют одновременно
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, secrets.token_hex(32).encode()); os.close(fd)
    except FileExistsError:
        pass
    return f.read_text().strip()


SECRET = _secret()
DEMO_USER = os.environ.get("DEMO_USER", "demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo2025")


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)


def _seed_demo() -> None:
    """Демо-аккаунт для жюри (DEMO_USER / DEMO_PASSWORD), создаётся при старте, если его нет. Пустой DEMO_USER — не создавать."""
    if not DEMO_USER:
        return
    salt = secrets.token_bytes(16)
    add_user(DEMO_USER.lower(), salt, _hash(DEMO_PASSWORD, salt))


_seed_demo()


class RegisterIn(BaseModel):
    username: str
    password: str


@router.post("/register", status_code=201, summary="Регистрация пользователя")
def register(body: RegisterIn) -> dict:
    u = body.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.@-]{3,64}", u):
        raise HTTPException(400, "логин: 3–64 символа, латиница, цифры и . _ @ -")
    if len(body.password) < 6:
        raise HTTPException(400, "пароль должен быть не короче 6 символов")
    salt = secrets.token_bytes(16)
    if not add_user(u, salt, _hash(body.password, salt)):
        raise HTTPException(409, "пользователь с таким логином уже зарегистрирован")
    return {"username": u, "message": "пользователь зарегистрирован"}


@router.post("/token", summary="Вход: логин и пароль → токен (OAuth2 Password Flow)")
def token(form: OAuth2PasswordRequestForm = Depends()) -> dict:
    u = form.username.strip().lower()
    row = get_user(u)
    if not row or not hmac.compare_digest(_hash(form.password, row[0]), row[1]):
        raise HTTPException(401, "неверный логин или пароль", headers={"WWW-Authenticate": "Bearer"})
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TOKEN_TTL_H)
    return {"access_token": jwt.encode({"sub": u, "exp": exp}, SECRET, algorithm=ALGO), "token_type": "bearer",
            "expires_in": int(TOKEN_TTL_H * 3600)}


def current_user(tok: str | None = Depends(oauth2)) -> str:
    if not tok:
        raise HTTPException(401, "нужна авторизация: войдите и передайте токен в заголовке Authorization: Bearer …",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return jwt.decode(tok, SECRET, algorithms=[ALGO])["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "срок действия токена истёк, войдите заново", headers={"WWW-Authenticate": "Bearer"}) from None
    except jwt.PyJWTError:
        raise HTTPException(401, "неверный токен, войдите заново", headers={"WWW-Authenticate": "Bearer"}) from None


@router.get("/me", summary="Текущий пользователь")
def me(user: str = Depends(current_user)) -> dict:
    return {"username": user}
