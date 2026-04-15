"""
db_upgrade.py

Одноразовый скрипт миграции БД для перехода на мультимодульную архитектуру.

Что делает:
  1. Добавляет колонку «modules» в таблицу admin_users (если её нет)
  2. Создаёт таблицу «stock» для модуля supplies (если её нет)
  3. Существующим пользователям без modules назначает '["implants"]' по умолчанию

Запуск (один раз на сервере):
    python db_upgrade.py
"""

import sqlite3
import sys
import os

# Берём путь к БД из переменной окружения или используем дефолтный
from dotenv import load_dotenv
load_dotenv()

DB_DSN = os.getenv("DB_DSN", "sqlite:///stock.db")

# Вытаскиваем путь к файлу из sqlite DSN
if DB_DSN.startswith("sqlite:///"):
    db_path = DB_DSN[len("sqlite:///"):]
    # Если путь не абсолютный — относительно корня проекта
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), db_path)
else:
    print(f"❌ Этот скрипт работает только с SQLite. DB_DSN={DB_DSN}")
    sys.exit(1)

print(f"База данных: {db_path}")

con = sqlite3.connect(db_path)
cur = con.cursor()

# ── 1. Колонка modules в admin_users ──────────────────────────────────────────
cur.execute("PRAGMA table_info(admin_users)")
columns = [row[1] for row in cur.fetchall()]

if "modules" not in columns:
    print("Добавляю колонку modules в admin_users...")
    cur.execute("ALTER TABLE admin_users ADD COLUMN modules TEXT")
    # Существующим пользователям даём доступ к implants (текущий модуль)
    cur.execute("UPDATE admin_users SET modules = '[\"implants\"]' WHERE modules IS NULL")
    print("  ✅ Готово. Существующим пользователям назначен модуль [\"implants\"].")
else:
    print("  ℹ️  Колонка modules уже существует.")

# ── 2. Таблица stock для модуля supplies ──────────────────────────────────────
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock'")
if not cur.fetchone():
    print("Создаю таблицу stock (расходники/инструменты)...")
    cur.execute("""
        CREATE TABLE stock (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name  TEXT,
            region      TEXT,
            warehouse   TEXT,
            category    TEXT,
            manufacturer TEXT,
            brand       TEXT,
            nomenclature TEXT,
            characteristic TEXT,
            photo_url   TEXT,
            balance     NUMERIC,
            updated_at  DATETIME NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_stock_group_name    ON stock (group_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_stock_region        ON stock (region)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_stock_warehouse     ON stock (warehouse)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_stock_category      ON stock (category)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_stock_manufacturer  ON stock (manufacturer)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_stock_brand         ON stock (brand)")
    print("  ✅ Таблица stock создана.")
else:
    print("  ℹ️  Таблица stock уже существует.")

# ── 3. Таблицы для модуля inn_check ───────────────────────────────────────────
for table_name, ddl in [
    ("inn_dilers", """
        CREATE TABLE inn_dilers (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            inn     TEXT NOT NULL UNIQUE,
            allowed INTEGER DEFAULT 1
        )"""),
    ("inn_lpu", """
        CREATE TABLE inn_lpu (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            inn     TEXT NOT NULL UNIQUE,
            allowed INTEGER DEFAULT 1
        )"""),
    ("inn_pending", """
        CREATE TABLE inn_pending (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL,
            inn      TEXT NOT NULL UNIQUE,
            date     TEXT,
            approved INTEGER DEFAULT 0,
            denied   INTEGER DEFAULT 0
        )"""),
]:
    cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    if not cur.fetchone():
        print(f"Создаю таблицу {table_name}...")
        cur.execute(ddl)
        cur.execute(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_inn ON {table_name} (inn)")
        print(f"  ✅ Таблица {table_name} создана.")
    else:
        print(f"  ℹ️  Таблица {table_name} уже существует.")

con.commit()
con.close()

print("\n✅ Миграция завершена.")
