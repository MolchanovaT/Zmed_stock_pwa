from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

stats_router = Router()

BOT_NAME = "stockbot2_implants"   # 👈 имя бота для метки
PERIOD = "-30 days"               # SQLite-стиль: "-7 days", "-1 month", и т.п.

@stats_router.message(Command("stats"))
async def cmd_stats(msg: Message):
    async with AsyncSessionLocal() as s:
        q1 = await s.execute(text("""
          SELECT COUNT(DISTINCT user_id)
          FROM tg_interactions
          WHERE created_at >= datetime('now', :period) AND bot_name = :bot
        """), {"period": PERIOD, "bot": BOT_NAME})
        uniq = q1.scalar() or 0

        q2 = await s.execute(text("""
          SELECT COUNT(*)
          FROM tg_interactions
          WHERE created_at >= datetime('now', :period) AND bot_name = :bot
        """), {"period": PERIOD, "bot": BOT_NAME})
        total = q2.scalar() or 0

        q3 = await s.execute(text("""
          SELECT kind, COUNT(*)
          FROM tg_interactions
          WHERE created_at >= datetime('now', :period) AND bot_name = :bot
          GROUP BY kind
        """), {"period": PERIOD, "bot": BOT_NAME})
        by_kind = {k: c for k, c in q3.all()}

    text_out = (
        f"📊 Статистика за {PERIOD}\n"
        f"• Уникальные пользователи: {uniq}\n"
        f"• Всего событий: {total}\n"
        f"  — сообщения: {by_kind.get('message', 0)}\n"
        f"  — команды:   {by_kind.get('command', 0)}\n"
        f"  — /start:    {by_kind.get('start', 0)}\n"
        f"  — колбэки:   {by_kind.get('callback', 0)}"
    )
    await msg.answer(text_out)
