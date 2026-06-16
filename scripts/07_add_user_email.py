"""
scripts/07_add_user_email.py

Миграция схемы: добавляет колонку email в таблицу users.

    email TEXT NULL

Используется для отправки копии письма о заказе самому пользователю.
Пустой email — пользователь просто не получает копию.

Идемпотентна.

Запуск на проде:
    cd /root/zmed_pwa && python scripts/07_add_user_email.py
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

cur.execute("PRAGMA table_info(users)")
existing = {row[1] for row in cur.fetchall()}

if not existing:
    print("❌ Таблица users не найдена.")
    sys.exit(1)

if "email" in existing:
    print("  ℹ️  users.email уже есть, пропускаю.")
else:
    cur.execute("ALTER TABLE users ADD COLUMN email TEXT")
    print("  ✅ users.email добавлен.")

con.commit()
con.close()

print("\nГотово.")
