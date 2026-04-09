from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, scoped_session

from app.config import ASYNC_DB_DSN, DB_DSN

# ─────────────────────────────────────────────────────────────
# Async (для бота и scheduler)

async_engine = create_async_engine(ASYNC_DB_DSN, future=True)
AsyncSessionLocal = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


# ─────────────────────────────────────────────────────────────
# Sync (для Flask и Alembic)

sync_engine = create_engine(DB_DSN, future=True)
db_session_factory = sessionmaker(bind=sync_engine)
db_session = scoped_session(db_session_factory)
