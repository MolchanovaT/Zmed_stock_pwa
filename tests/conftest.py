"""
tests/conftest.py

Фикстуры для pytest. Отдельная sqlite-БД в tmp для каждой сессии.

Запуск:
    pytest tests/              — все тесты
    pytest tests/test_rls_clinic_reports.py -v

Нюансы:
  * env ASYNC_DB_DSN/DB_DSN подменяется ДО импорта app.* (это важно —
    AsyncSessionLocal создаётся на импорте app/db/session.py).
  * email: SMTP_HOST пустая → письма не уйдут (в email.py и email_report.py
    есть ранний return).
  * JWT_SECRET тоже задаём — чтобы токены были детерминированные.
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio


# ── ENV до импорта приложения ────────────────────────────────────────────────

_TMP_DIR = tempfile.mkdtemp(prefix="zmed_rls_tests_")
_DB_FILE = Path(_TMP_DIR) / "test.db"

os.environ["ASYNC_DB_DSN"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["DB_DSN"] = f"sqlite:///{_DB_FILE}"
os.environ["JWT_SECRET"] = "test_jwt_secret_32_chars_min_______"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ.setdefault("SMTP_HOST", "")           # отключаем email
os.environ.setdefault("CORS_ORIGINS", "http://testserver")
os.environ.setdefault("REPORTS_DIR", str(Path(_TMP_DIR) / "reports"))


# ── Импорт приложения (после env) ────────────────────────────────────────────

from httpx import ASGITransport, AsyncClient                       # noqa: E402

from app.api.auth import create_access_token                       # noqa: E402
from app.api_main import app                                       # noqa: E402
from app.db.base import Base                                       # noqa: E402
from app.db.models import (                                        # noqa: E402, F401
    AdminUser, AllowedUser, Cart, CartItem, ClinicStockBalance,
    ClinicStockItem, ClinicStockLocation, ClinicStockMovement,
    EmailRecipient, InnDiler, InnLpu, InnPending, OperationReport,
    OperationReportFile, Organization, PwaActivity, Stock, Supplies,
    User,
)
from app.db.session import AsyncSessionLocal, async_engine         # noqa: E402


# ── Инициализация схемы один раз на сессию ───────────────────────────────────

@pytest_asyncio.fixture(scope="session", autouse=True)
async def _init_schema():
    """Создаёт все таблицы из моделей для тестовой БД."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── Очистка данных между тестами ─────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_init_schema):
    """Между тестами чистим бизнес-таблицы, схему не трогаем."""
    yield
    async with AsyncSessionLocal() as s:
        for table in (
            "clinic_stock_movements",
            "clinic_stock_balances",
            "clinic_stock_items",
            "clinic_stock_locations",
            "operation_report_files",
            "operation_reports",
            "pwa_activity",
            "cart_items",
            "carts",
            "users",
            "organizations",
            "email_recipients",
        ):
            from sqlalchemy import text as _text
            await s.execute(_text(f"DELETE FROM {table}"))
        await s.commit()


# ── Общий HTTP-клиент против ASGI ────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """AsyncClient на in-process ASGI (не поднимает отдельный сервер)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ── Фабрики ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def orgs():
    """Создаёт три организации: ZMed + 2 клиники (A, B). Возвращает dict id."""
    async with AsyncSessionLocal() as s:
        zmed = Organization(name="ZMed", kind="zmed", active=1)
        clinic_a = Organization(name="Клиника A", kind="clinic", active=1)
        clinic_b = Organization(name="Клиника B", kind="clinic", active=1)
        s.add_all([zmed, clinic_a, clinic_b])
        await s.commit()
        return {"zmed": zmed.id, "a": clinic_a.id, "b": clinic_b.id}


@pytest_asyncio.fixture
async def users(orgs):
    """Пять юзеров: zmed_admin, clinic_a_user, clinic_a_user2, clinic_b_user,
    orphan (без organization_id)."""
    async with AsyncSessionLocal() as s:
        zmed_admin = User(username="zmed_admin", organization_id=orgs["zmed"],
                          is_superuser=1, active=1, modules='["clinic_reports","clinic_stock"]')
        zmed_admin.set_password("x")
        ua1 = User(username="a_user1", organization_id=orgs["a"],
                   is_superuser=0, active=1, modules='["clinic_reports","clinic_stock"]')
        ua1.set_password("x")
        ua2 = User(username="a_user2", organization_id=orgs["a"],
                   is_superuser=0, active=1, modules='["clinic_reports","clinic_stock"]')
        ua2.set_password("x")
        ub1 = User(username="b_user1", organization_id=orgs["b"],
                   is_superuser=0, active=1, modules='["clinic_reports","clinic_stock"]')
        ub1.set_password("x")
        orphan = User(username="orphan", organization_id=None,
                      is_superuser=0, active=1, modules='["clinic_reports"]')
        orphan.set_password("x")
        s.add_all([zmed_admin, ua1, ua2, ub1, orphan])
        await s.commit()
        return {
            "zmed_admin": zmed_admin.id,
            "a1": ua1.id, "a2": ua2.id, "b1": ub1.id, "orphan": orphan.id,
        }


def _auth(user_id: int) -> dict:
    token = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth(users):
    """Готовые заголовки для каждого юзера."""
    return {
        "zmed_admin": _auth(users["zmed_admin"]),
        "a1": _auth(users["a1"]),
        "a2": _auth(users["a2"]),
        "b1": _auth(users["b1"]),
        "orphan": _auth(users["orphan"]),
    }


# ── pytest-asyncio ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Один event loop на сессию — чтобы async_engine использовал его стабильно."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
