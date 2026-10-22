"""
alembic/env.py

Конфигурация Alembic для ZMed Stock PWA.

Особенности:
  * sqlalchemy.url берётся из переменной окружения DB_DSN (а не из alembic.ini).
  * target_metadata = Base.metadata — чтобы autogenerate видел все модели.
  * batch mode включён для SQLite (ALTER TABLE там ограничен).
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Корень проекта — чтобы `from app.db...` импортировался
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import Base                               # noqa: E402
# Эти импорты регистрируют модели в Base.metadata — autogenerate без них
# ничего не увидит.
from app.db import models                                   # noqa: E402, F401
from app.db import models_stats                             # noqa: E402, F401
from dotenv import load_dotenv                              # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

config = context.config

# Берём реальный URL из env, игнорируя заглушку в alembic.ini
db_url = os.getenv("DB_DSN") or config.get_main_option("sqlalchemy.url")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _is_sqlite() -> bool:
    return (db_url or "").startswith("sqlite")


def run_migrations_offline() -> None:
    """Миграции без подключения к БД — печатают SQL."""
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite(),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Миграции с реальным engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite(),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
