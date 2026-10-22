"""
app/api/tg_notify.py

Telegram-уведомления о клинических событиях.

Кому: supers-юзеры ZMed с заполненным tg_id (т.е. писавшие хоть раз
@ZmedBot — чтобы бот мог им отправлять сообщения).
Через какого бота: @ZmedBot (BOT_TOKEN_INN) — он всегда рядом в стеке,
есть у всех сотрудников ZMed.

Политика ошибок: fire-and-forget, тихо гасим — не ломать submit отчёта
из-за недоступности Telegram.
"""

import asyncio
import logging
from typing import Iterable

import aiohttp
from sqlalchemy import select

from app.config import BOT_TOKEN_INN, PWA_BASE_URL
from app.db.models import Organization, User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def _send_one(session: aiohttp.ClientSession, token: str,
                     chat_id: int, text: str) -> None:
    try:
        async with session.post(
            _API_URL.format(token=token),
            json={"chat_id": chat_id, "text": text,
                   "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning("TG sendMessage chat_id=%s: %s %s",
                               chat_id, resp.status, body[:200])
    except Exception as e:                           # noqa: BLE001
        # В restart:always-контейнерах не раздуваем лог при длительном простое TG
        logger.debug("TG sendMessage chat_id=%s failed: %s", chat_id, e)


async def _recipients() -> list[int]:
    """Супер-юзеры ZMed-организации с заполненным tg_id и active=1."""
    async with AsyncSessionLocal() as s:
        stmt = (
            select(User.tg_id)
            .join(Organization, Organization.id == User.organization_id)
            .where(
                User.is_superuser == 1,
                User.active == 1,
                User.tg_id.isnot(None),
                Organization.kind == "zmed",
            )
        )
        rows = (await s.execute(stmt)).all()
    return [r[0] for r in rows if r[0]]


async def _broadcast(text: str) -> None:
    """Отправка одного и того же текста всем целевым tg_id через @ZmedBot."""
    token = BOT_TOKEN_INN
    if not token:
        logger.info("BOT_TOKEN_INN не задан — TG-уведомления пропущены.")
        return
    chat_ids = await _recipients()
    if not chat_ids:
        logger.info("Нет получателей TG-уведомлений (супер-ZMed без tg_id).")
        return
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[
            _send_one(session, token, cid, text) for cid in chat_ids
        ])


async def send_report_tg_notification(
    report_id: int,
    organization_name: str,
    operation_date: str,
    operation_type: str,
    patient_code: str,
    doctor_name: str,
    files_count: int,
) -> None:
    """Fire-and-forget: оповещаем ZMed-админов о новом отправленном отчёте."""
    url_line = ""
    if PWA_BASE_URL:
        url_line = f'\n<a href="{PWA_BASE_URL}/clinic-reports/{report_id}">Открыть отчёт</a>'
    text = (
        f"📋 <b>Новый отчёт #{report_id}</b>\n"
        f"<b>Клиника:</b> {organization_name}\n"
        f"<b>Дата:</b> {operation_date}\n"
        f"<b>Тип:</b> {operation_type}\n"
        f"<b>Врач:</b> {doctor_name}\n"
        f"<b>Код операции:</b> <code>{patient_code}</code>\n"
        f"<b>Файлов:</b> {files_count}"
        f"{url_line}"
    )
    await _broadcast(text)
