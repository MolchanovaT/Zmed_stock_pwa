# app/bot/middlewares/middleware_access.py
from typing import Callable, Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import AllowedUser


class DBAccessMiddleware(BaseMiddleware):
    """
    Пропускаем событие дальше **только** если `tg_id` присутствует
    в таблице allowed_users.

    Иначе отправляем пользователю UID-подсказку и прерываем обработку.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:                     # service-updates, etc.
            return await handler(event, data)

        # ── проверяем доступ ─────────────────────────────────────────
        async with AsyncSessionLocal() as session:
            ok = await session.scalar(
                select(AllowedUser.tg_id).where(AllowedUser.tg_id == user.id)
            )

        if not ok:
            text = (
                "🚫 У вас пока нет доступа к боту.\n\n"
                f"Ваш UID: <code>{user.id}</code>\n"
                "Передайте этот номер администратору для добавления."
            )

            # 1) если это нажатие на inline-кнопку
            if isinstance(event, CallbackQuery):
                await event.message.answer(text, parse_mode="HTML")

            # 2) если это обычное сообщение (/start, текст)
            elif isinstance(event, Message):
                await event.answer(text, parse_mode="HTML")

            # 3) прочие случаи — fallback
            elif hasattr(event, "answer"):
                await event.answer(text, parse_mode="HTML")

            return                                  # доступ не даём

        # ── всё хорошо ───────────────────────────────────────────────
        return await handler(event, data)
