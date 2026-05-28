# app/bot/middlewares/middleware_access.py
import json
from typing import Callable, Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select

from app.db.models import User
from app.db.session import AsyncSessionLocal

# Этот бот — импланты, для него требуется модуль `bot_implants` в users.modules.
BOT_MODULE = "bot_implants"


class DBAccessMiddleware(BaseMiddleware):
    """
    Доступ контролируется через общую таблицу users в PWA-БД
    (читается через общий AsyncSessionLocal PWA-бэкенда).

    Пропускаем событие дальше только если:
      • tg_id найден в users
      • active = 1
      • в modules есть `bot_implants`
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(User.modules, User.active).where(User.tg_id == user.id)
            )).first()

        if row is None:
            await self._reply(event, (
                "🚫 У вас пока нет доступа к боту.\n\n"
                f"Ваш UID: <code>{user.id}</code>\n"
                "Передайте этот номер администратору для добавления."
            ))
            return

        modules_json, active = row
        if not active:
            await self._reply(event, "🚫 Ваш доступ временно отключён. "
                                     "Обратитесь к администратору.")
            return

        try:
            modules = json.loads(modules_json) if modules_json else []
        except (ValueError, TypeError):
            modules = []

        if BOT_MODULE not in modules:
            await self._reply(event, "🚫 У вас нет доступа к этому боту "
                                     "(нужен модуль «Бот имплантов»). "
                                     "Обратитесь к администратору.")
            return

        return await handler(event, data)

    @staticmethod
    async def _reply(event: TelegramObject, text_msg: str) -> None:
        if isinstance(event, CallbackQuery):
            await event.message.answer(text_msg, parse_mode="HTML")
        elif isinstance(event, Message):
            await event.answer(text_msg, parse_mode="HTML")
        elif hasattr(event, "answer"):
            await event.answer(text_msg, parse_mode="HTML")
