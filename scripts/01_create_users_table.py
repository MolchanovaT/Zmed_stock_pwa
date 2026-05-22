"""
scripts/01_create_users_table.py

Одноразовая миграция схемы: создаёт таблицу `users` в основной БД PWA.
Старые admin_users и allowed_users НЕ трогаются — данные перенесёт
следующий скрипт импорта (см. scripts/02_import_users.py).

Запуск на проде:
    cd /root/zmed_pwa && python scripts/01_create_users_table.py
"""

import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv("DB_DSN", "sqlite:///stock.db")

if not DB_DSN.startswith("sqlite:///"):
    print(f"❌ Этот скрипт работает только с SQLite. DB_DSN={DB_DSN}")
    sys.exit(1)

db_path = DB_DSN[len("sqlite:///"):]
if not os.path.isabs(db_path):
    db_path = os.path.join(os.path.dirname(__file__), "..", db_path)
db_path = os.path.abspath(db_path)

print(f"База данных: {db_path}")

con = sqlite3.connect(db_path)
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
if cur.fetchone():
    print("  ℹ️  Таблица users уже существует, пропускаю.")
else:
    print("Создаю таблицу users...")
    cur.execute("""
        CREATE TABLE users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE,
            password_hash TEXT,
            tg_id         INTEGER UNIQUE,
            full_name     TEXT,
            title         TEXT,
            modules       TEXT,
            is_superuser  INTEGER NOT NULL DEFAULT 0,
            active        INTEGER NOT NULL DEFAULT 1,
            created_at    DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cur.execute("CREATE INDEX ix_users_tg_id ON users (tg_id)")
    print("  ✅ Таблица users создана.")

con.commit()
con.close()

print("\n✅ Миграция схемы завершена.")
