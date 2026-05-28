import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import BOT_TOKEN_IMPLANTS

from .commands.export_stats import export_router
from .commands.stats import stats_router
from .handlers import r
from .middlewares.middleware_access import DBAccessMiddleware
from .middlewares.stats import StatsMiddleware


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN_IMPLANTS)
    dp = Dispatcher(storage=MemoryStorage())

    access_mw = DBAccessMiddleware()
    dp.message.middleware(access_mw)
    dp.callback_query.middleware(access_mw)

    dp.message.middleware(StatsMiddleware(bot_name="stockbot2_implants"))
    dp.callback_query.middleware(StatsMiddleware(bot_name="stockbot2_implants"))

    dp.include_router(stats_router)
    dp.include_router(export_router)
    dp.include_router(r)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
