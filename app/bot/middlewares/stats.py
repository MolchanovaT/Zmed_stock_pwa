from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update
from typing import Callable, Dict, Any, Awaitable
from datetime import datetime, timezone

from app.db.session import AsyncSessionLocal
from app.db.models_stats import TgUser, Interaction

class StatsMiddleware(BaseMiddleware):
    def __init__(self, bot_name: str):
        super().__init__()
        self.bot_name = bot_name

    async def __call__(self, handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
                       event: Update, data: Dict[str, Any]) -> Any:
        try:
            if isinstance(event, Message):
                await self._log_message(event)
            elif isinstance(event, CallbackQuery):
                await self._log_callback(event)
        except Exception:
            pass  # статистика не должна ломать бота
        return await handler(event, data)

    async def _ensure_and_touch_user(self, u):
        async with AsyncSessionLocal() as s:
            user = await s.get(TgUser, u.id)
            if not user:
                user = TgUser(
                    id=u.id, is_bot=u.is_bot, username=u.username,
                    first_name=u.first_name, last_name=u.last_name,
                    language_code=getattr(u, "language_code", None),
                )
                s.add(user)
            user.last_seen_at = datetime.now(timezone.utc)
            user.username = u.username
            user.first_name = u.first_name
            user.last_name = u.last_name
            await s.commit()

    async def _log_message(self, msg: Message):
        if msg.from_user:
            await self._ensure_and_touch_user(msg.from_user)
        kind = "command" if (msg.text or "").startswith("/") else "message"
        if msg.text == "/start":
            kind = "start"
        async with AsyncSessionLocal() as s:
            s.add(Interaction(
                bot_name=self.bot_name,
                user_id=msg.from_user.id if msg.from_user else 0,
                chat_id=msg.chat.id,
                chat_type=msg.chat.type,
                kind=kind,
                payload=(msg.text or "")[:4096],
            ))
            await s.commit()

    async def _log_callback(self, c: CallbackQuery):
        if c.from_user:
            await self._ensure_and_touch_user(c.from_user)
        async with AsyncSessionLocal() as s:
            s.add(Interaction(
                bot_name=self.bot_name,
                user_id=c.from_user.id if c.from_user else 0,
                chat_id=c.message.chat.id if c.message else 0,
                chat_type=c.message.chat.type if c.message else None,
                kind="callback",
                payload=(c.data or "")[:4096],
            ))
            await s.commit()
