"""
scripts/05_extend_carts_schema.py

Миграция схемы: добавляет колонки в таблицу carts.

    source_lpu  TEXT  — склад-источник (где отбирался товар), фиксируется
                        при первом добавлении позиции в корзину.
    comment     TEXT  — свободный комментарий к заказу.

Идемпотентна: повторный запуск ничего не ломает.

Запуск на проде:
    cd /root/zmed_pwa && python scripts/05_extend_carts_schema.py
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

added = []
for col, ddl in [
    ("source_lpu", "ALTER TABLE carts ADD COLUMN source_lpu TEXT"),
    ("comment",    "ALTER TABLE carts ADD COLUMN comment TEXT"),
]:
    if col in existing:
        print(f"  ℹ️  carts.{col} уже есть, пропускаю.")
    else:
        cur.execute(ddl)
        added.append(col)
        print(f"  ✅ carts.{col} добавлен.")

con.commit()
con.close()

if added:
    print(f"\nГотово. Добавлены колонки: {', '.join(added)}.")
else:
    print("\nГотово. Изменений не потребовалось.")
