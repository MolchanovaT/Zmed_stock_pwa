from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, Update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.models_stats import Interaction, TgUser, now_utc
from app.db.session import AsyncSessionLocal


class StatsMiddleware(BaseMiddleware):
    def __init__(self, bot_name: str):
        super().__init__()
        self.bot_name = bot_name

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        try:
            if isinstance(event, Message):
                await self._log_message(event)
            elif isinstance(event, CallbackQuery):
                await self._log_callback(event)
        except Exception:
            pass
        return await handler(event, data)

    async def _ensure_and_touch_user(self, u, session):
        stmt = sqlite_insert(TgUser).values(
            id=u.id,
            is_bot=bool(u.is_bot),
            username=u.username,
            first_name=u.first_name,
            last_name=u.last_name,
            language_code=getattr(u, "language_code", None),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[TgUser.id],
            set_={
                "username": stmt.excluded.username,
                "first_name": stmt.excluded.first_name,
                "last_name": stmt.excluded.last_name,
                "last_seen_at": now_utc(),
            },
        )
        await session.execute(stmt)

    async def _log_message(self, msg: Message):
        if msg.text == "/start":
            kind = "start"
        elif (msg.text or "").startswith("/"):
            kind = "command"
        else:
            kind = "message"

        async with AsyncSessionLocal() as s:
            if msg.from_user:
                await self._ensure_and_touch_user(msg.from_user, s)
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
        async with AsyncSessionLocal() as s:
            if c.from_user:
                await self._ensure_and_touch_user(c.from_user, s)
            s.add(Interaction(
                bot_name=self.bot_name,
                user_id=c.from_user.id if c.from_user else 0,
                chat_id=c.message.chat.id if c.message else 0,
                chat_type=c.message.chat.type if c.message else None,
                kind="callback",
                payload=(c.data or "")[:4096],
            ))
            await s.commit()
