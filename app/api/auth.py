"""
app/api/auth.py

JWT-авторизация для PWA.
Аутентификация — по таблице AdminUser (username + password_hash).
Доступ к боту контролируется AllowedUser (tg_id), для PWA используем AdminUser.

Эндпоинты:
  POST /api/auth/login  — принимает form-data {username, password}, возвращает JWT
  GET  /api/auth/me     — возвращает данные текущего пользователя
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select

from app.api.activity import log_activity
from app.db.models import AdminUser
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET: str = os.getenv("JWT_SECRET", "CHANGE_ME_32_char_secret_key_!!!!")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS: int = 8

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Pydantic-схемы ─────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str


class UserOut(BaseModel):
    id: int
    username: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> AdminUser:
    """Dependency: декодирует JWT и возвращает AdminUser из БД."""
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Недействительный токен",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise exc
    except JWTError:
        raise exc

    async with AsyncSessionLocal() as session:
        user = await session.get(AdminUser, int(user_id))

    if user is None:
        raise exc
    return user


# ── Эндпоинты ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    """
    Принимает username + password (form-data), возвращает JWT-токен.
    Фронтенд должен отправлять Content-Type: application/x-www-form-urlencoded.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AdminUser).where(AdminUser.username == form.username)
        )
        user = result.scalars().first()

    if not user or not user.check_password(form.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id)
    asyncio.create_task(log_activity(user.id, user.username, "login"))
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: AdminUser = Depends(get_current_user)):
    """Возвращает данные авторизованного пользователя."""
    return {"id": current_user.id, "username": current_user.username}
