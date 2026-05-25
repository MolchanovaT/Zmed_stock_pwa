import asyncio
from aiogram import Bot, Dispatcher
from app.config import BOT_TOKEN
from .handlers import r
from app.db.base import Base
from app.db.session import async_engine
from app.bot.middlewares.middleware_access import DBAccessMiddleware
from app.bot.middlewares.stats import StatsMiddleware
from app.bot.commands.stats import stats_router
from app.bot.commands.export_stats import export_router

async def init_models() -> None:
    """Создать все таблицы, если их ещё нет."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main():
    await init_models()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    access_mw = DBAccessMiddleware()
    dp.message.middleware(access_mw)
    dp.callback_query.middleware(access_mw)

    dp.message.middleware(StatsMiddleware(bot_name="stockbot2_implants"))
    dp.callback_query.middleware(StatsMiddleware(bot_name="stockbot2_implants"))
    dp.include_router(stats_router)
    dp.include_router(export_router)

    dp.include_router(r)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
