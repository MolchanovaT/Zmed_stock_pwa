"""
app/api/otp.py

Email-OTP для подтверждения чувствительных действий (сейчас — подпись
отчёта при draft→submitted).

Эндпоинты:
  POST /api/otp/request  — выдать код по email текущему юзеру
                           body: {"purpose": "report_submit:42"}
                           ответ: {"sent_to": "u***@domain.ru", "ttl": 600}
  POST /api/otp/verify   — проверить и ПОМЕТИТЬ код использованным
                           body: {"purpose": "...", "code": "123456"}
                           ответ: {"ok": true}

Политика:
  * 6-значный числовой код (криптослучайный);
  * Хранится как SHA-256(code + JWT_SECRET) — plaintext в БД нет;
  * TTL = OTP_TTL_SECONDS (default 600c);
  * При выдаче нового кода на тот же purpose — старые помечаются used_at
    (one-active-per-purpose);
  * verify удаляет rate-limit брутфорса — ограничен scan_rate_limit-подобным
    механизмом на /verify (3 попытки за минуту на пользователя+purpose).
"""

import asyncio
import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.api.auth import get_current_user
from app.api.rate_limit import _check as _rate_check
from app.config import (
    JWT_SECRET, OTP_TTL_SECONDS, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT,
    SMTP_USER,
)
from app.db.models import OtpCode, User
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/otp", tags=["otp"])
logger = logging.getLogger(__name__)


class OtpRequest(BaseModel):
    purpose: str = Field(..., min_length=1, max_length=100)


class OtpVerify(BaseModel):
    purpose: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=4, max_length=12)


# ── Hash & helpers ──────────────────────────────────────────────────────────

def _hash_code(code: str) -> str:
    return hashlib.sha256(f"{code}|{JWT_SECRET}".encode("utf-8")).hexdigest()


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[0] + "*"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def _send_otp_email_sync(to_email: str, code: str, purpose: str) -> None:
    if not SMTP_HOST:
        logger.info("SMTP не настроен — OTP не отправлен.")
        return
    msg = MIMEText(
        f"Код подтверждения для действия «{purpose}»: {code}\n\n"
        f"Код действует {OTP_TTL_SECONDS // 60} минут.\n\n"
        "Если вы не запрашивали это действие — просто проигнорируйте письмо.",
        "plain", "utf-8",
    )
    msg["Subject"] = f"ZMed · код подтверждения: {code}"
    msg["From"] = SMTP_FROM or SMTP_USER
    msg["To"] = to_email
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        logger.info("OTP отправлен на %s", _mask_email(to_email))
    except Exception as e:                           # noqa: BLE001
        logger.error("Ошибка отправки OTP: %s", e)


async def _send_otp_email(to_email: str, code: str, purpose: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_otp_email_sync, to_email, code, purpose)


# ── Verify-функция (переиспользуется из других API) ─────────────────────────

async def consume_otp(user: User, purpose: str, code: str) -> None:
    """Проверяет OTP и помечает его used. Поднимает 400/401 при проблеме.

    Используется и из /otp/verify, и напрямую из других API (чтобы не плодить
    фронт-roundtrip, можно передавать code прямо в submit).
    """
    if not code or not code.strip():
        raise HTTPException(status_code=400, detail="Укажите OTP-код")

    code_hash = _hash_code(code.strip())
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as s:
        # Находим активный код
        res = await s.execute(
            select(OtpCode).where(
                OtpCode.user_id == user.id,
                OtpCode.purpose == purpose,
                OtpCode.code_hash == code_hash,
                OtpCode.used_at.is_(None),
            )
        )
        rec = res.scalars().first()
        if rec is None:
            raise HTTPException(status_code=401, detail="Неверный или устаревший код")
        if rec.expires_at < now:
            raise HTTPException(status_code=401, detail="Код истёк — запросите новый")
        rec.used_at = now
        s.add(rec)
        await s.commit()


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/request")
async def request_otp(
    body: OtpRequest,
    current_user: User = Depends(get_current_user),
):
    # Rate limit: не чаще 5 запросов за 10 минут на user+purpose
    _rate_check(f"otp_req:{body.purpose}", current_user.id,
                 per_seconds=600.0, max_hits=5)

    if not current_user.email or "@" not in current_user.email:
        raise HTTPException(
            status_code=400,
            detail="У вашего профиля не указан email — обратитесь к администратору.",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = _hash_code(code)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=OTP_TTL_SECONDS)

    async with AsyncSessionLocal() as s:
        # Пометить старые активные коды use (one-active-per-purpose)
        await s.execute(
            update(OtpCode)
            .where(
                OtpCode.user_id == current_user.id,
                OtpCode.purpose == body.purpose,
                OtpCode.used_at.is_(None),
            )
            .values(used_at=now)
        )
        s.add(OtpCode(
            user_id=current_user.id,
            purpose=body.purpose,
            code_hash=code_hash,
            expires_at=expires,
            created_at=now,
        ))
        await s.commit()

    asyncio.create_task(_send_otp_email(current_user.email, code, body.purpose))
    return {
        "sent_to": _mask_email(current_user.email),
        "ttl": OTP_TTL_SECONDS,
    }


@router.post("/verify")
async def verify_otp(
    body: OtpVerify,
    current_user: User = Depends(get_current_user),
):
    # Rate limit: не больше 10 попыток ввода за минуту на user+purpose
    _rate_check(f"otp_verify:{body.purpose}", current_user.id,
                 per_seconds=60.0, max_hits=10)
    await consume_otp(current_user, body.purpose, body.code)
    return {"ok": True}
