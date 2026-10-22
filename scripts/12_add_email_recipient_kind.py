"""
scripts/12_add_email_recipient_kind.py

Миграция F3: колонка email_recipients.kind для разделения рассылок.

    kind TEXT NOT NULL DEFAULT 'all'
       'orders'  — только уведомления о заказах из корзины
       'reports' — только уведомления об отправленных отчётах клиник
       'all'     — обе рассылки

Существующие записи получают 'all' — чтобы ничего не сломать.

Идемпотентна.

Запуск:
    cd /root/zmed_pwa && python scripts/12_add_email_recipient_kind.py
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

cur.execute("PRAGMA table_info(email_recipients)")
cols = {row[1] for row in cur.fetchall()}
if not cols:
    print("❌ Таблица email_recipients не найдена — сначала scripts/08_create_email_recipients.py")
    sys.exit(1)

if "kind" in cols:
    print("  ℹ️  email_recipients.kind уже есть, пропускаю.")
else:
    cur.execute("ALTER TABLE email_recipients ADD COLUMN kind TEXT NOT NULL DEFAULT 'all'")
    print("  ✅ email_recipients.kind добавлен (default 'all').")

con.commit()
con.close()

print("\nГотово.")
