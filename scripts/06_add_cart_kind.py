"""
scripts/06_add_cart_kind.py

Миграция схемы: добавляет в carts колонку kind для разделения корзин
имплантов и расходников.

    kind TEXT NOT NULL DEFAULT 'implants'

Все существующие записи получают kind='implants' (до миграции корзина была
только у модуля имплантов).

Идемпотентна: повторный запуск ничего не ломает.

Запуск на проде:
    cd /root/zmed_pwa && python scripts/06_add_cart_kind.py
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

cur.execute("PRAGMA table_info(carts)")
existing = {row[1] for row in cur.fetchall()}

if not existing:
    print("❌ Таблица carts не найдена — сначала PWA должен поднять схему.")
    sys.exit(1)

if "kind" in existing:
    print("  ℹ️  carts.kind уже есть, пропускаю.")
else:
    cur.execute("ALTER TABLE carts ADD COLUMN kind TEXT NOT NULL DEFAULT 'implants'")
    print("  ✅ carts.kind добавлен (default='implants').")

con.commit()
con.close()

print("\nГотово.")
