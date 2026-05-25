from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
import io, csv, datetime as dt

export_router = Router()

BOT_NAME = "stockbot2_implants"
PERIOD = "-30 days"

@export_router.message(Command("export_stats"))
async def export_stats(msg: Message):
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text("""
          SELECT i.created_at, i.kind, i.user_id, u.username, u.first_name, u.last_name, i.payload
          FROM tg_interactions i
          LEFT JOIN tg_users u ON u.id = i.user_id
          WHERE i.created_at >= datetime('now', :period) AND i.bot_name = :bot
          ORDER BY i.created_at DESC
        """), {"period": PERIOD, "bot": BOT_NAME})).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at","kind","user_id","username","first_name","last_name","payload"])
    for r in rows:
        w.writerow(r)

    data = buf.getvalue().encode("utf-8")
    filename = f"stats_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    await msg.answer_document(BufferedInputFile(data, filename=filename),
                              caption=f"Статистика за {PERIOD}")
