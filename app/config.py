"""
app/config.py
Глобальные настройки проекта.

• Все переменные читаются из .env-файла в корне репозитория.
• Значения по умолчанию подходят для локальной разработки (SQLite).
• Для перехода на PostgreSQL просто измените строки DSN в .env
  или передайте переменные окружения при запуске контейнера.
"""

from pathlib import Path
from dotenv import load_dotenv
import os

# ────────────────────────────────────────────────────────────────
# Пути

BASE_DIR: Path = Path(__file__).resolve().parent.parent  # .../app -> repo root
ENV_PATH: Path = BASE_DIR / ".env"

# ────────────────────────────────────────────────────────────────
# Загрузка .env

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)          # локальный .env
else:
    # В Docker .env монтируется на уровень выше; там load_dotenv уже не нужен,
    # переменные окружения приходят напрямую из docker-compose.
    pass

# ────────────────────────────────────────────────────────────────
# Telegram-бот

BOT_TOKEN: str | None = os.getenv("BOT_TOKEN")           # обязателен

# ────────────────────────────────────────────────────────────────
# База данных

# Синхронная строка (для pandas / Alembic / bulk-импорта)
DB_DSN: str = os.getenv("DB_DSN", "sqlite:///stock.db")

# Асинхронная строка (для SQLAlchemy 2.0 + aiogram)
ASYNC_DB_DSN: str = os.getenv(
    "ASYNC_DB_DSN",
    "sqlite+aiosqlite:///stock.db"
)

# ────────────────────────────────────────────────────────────────
# Яндекс-Диск (автозабор CSV)

YD_TOKEN: str | None = os.getenv("YD_TOKEN")                  # OAuth-токен
YD_PATH: str = os.getenv("YD_PATH", "disk:/exports/stock.csv")  # путь к файлу

# ────────────────────────────────────────────────────────────────
# CSV-колонки (ожидаемый порядок после pd.read_csv)

CSV_COLUMNS: list[str] = [
    "group_name",    # Группа складов
    "region",        # Бизнес-регион
    "warehouse",     # Склад
    "category",      # Товарная категория
    "manufacturer",  # _Производитель
    "brand",         # Марка (бренд)
    "nomenclature",  # Номенклатура
    "balance",       # Конечный остаток
]

# ────────────────────────────────────────────────────────────────
# Email (для отправки заказов)

SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "")
# Получатели заказов (через запятую)
ORDER_EMAIL_TO: str = os.getenv("ORDER_EMAIL_TO", "")

# ────────────────────────────────────────────────────────────────
# Разное (можно добавить позже: LOG_LEVEL, SENTRY_DSN и т. д.)
