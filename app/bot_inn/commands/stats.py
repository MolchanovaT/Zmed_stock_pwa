from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import text

from app.db.session import AsyncSessionLocal

stats_router = Router()

BOT_NAME = "flask_bot_app"
PERIOD = "-30 days"


@stats_router.message(Command("stats"))
async def cmd_stats(msg: Message):
    async with AsyncSessionLocal() as s:
        uniq = (await s.execute(text("""
            SELECT COUNT(DISTINCT user_id) FROM tg_interactions
            WHERE created_at >= datetime('now', :p) AND bot_name = :b
        """), {"p": PERIOD, "b": BOT_NAME})).scalar() or 0

        total = (await s.execute(text("""
            SELECT COUNT(*) FROM tg_interactions
            WHERE created_at >= datetime('now', :p) AND bot_name = :b
        """), {"p": PERIOD, "b": BOT_NAME})).scalar() or 0

        by_kind_rows = (await s.execute(text("""
            SELECT kind, COUNT(*) FROM tg_interactions
            WHERE created_at >= datetime('now', :p) AND bot_name = :b
            GROUP BY kind
        """), {"p": PERIOD, "b": BOT_NAME})).all()
        by_kind = {k: c for k, c in by_kind_rows}

    out = (
        f"📊 Статистика за {PERIOD}\n"
        f"• Уникальные пользователи: {uniq}\n"
        f"• Всего событий: {total}\n"
        f"  — сообщения: {by_kind.get('message', 0)}\n"
        f"  — команды:   {by_kind.get('command', 0)}\n"
        f"  — /start:    {by_kind.get('start', 0)}\n"
        f"  — колбэки:   {by_kind.get('callback', 0)}"
    )
    await msg.answer(out)
