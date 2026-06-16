"""
scripts/08_create_email_recipients.py

Миграция: таблица email_recipients для списка адресов рассылки заказов.

Раньше адресаты лежали в ORDER_EMAIL_TO в .env. Теперь — таблица в БД,
которую редактирует админ через Flask-админку.

Колонки:
    id          INTEGER PK
    email       TEXT NOT NULL UNIQUE
    label       TEXT NULL                — назначение (например, «Отдел продаж»)
    created_at  TEXT NOT NULL

Если таблица пуста и ORDER_EMAIL_TO задана — однократно переносим адреса
оттуда (с пустым label), чтобы рассылка не прервалась.

Идемпотентна.

Запуск на проде:
    cd /root/zmed_pwa && python scripts/08_create_email_recipients.py
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv("DB_DSN", "sqlite:///stock.db")
ORDER_EMAIL_TO = os.getenv("ORDER_EMAIL_TO", "")

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

cur.execute("""
CREATE TABLE IF NOT EXISTS email_recipients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL UNIQUE,
    label      TEXT,
    created_at TEXT NOT NULL
)
""")
print("  ✅ email_recipients существует / создана.")

cur.execute("SELECT COUNT(*) FROM email_recipients")
existing_count = cur.fetchone()[0]

if existing_count == 0 and ORDER_EMAIL_TO.strip():
    now = datetime.now(timezone.utc).isoformat()
    addresses = [a.strip() for a in ORDER_EMAIL_TO.split(",") if a.strip()]
    imported = 0
    for addr in addresses:
        try:
            cur.execute(
                "INSERT INTO email_recipients (email, label, created_at) VALUES (?, ?, ?)",
                (addr, None, now),
            )
            imported += 1
        except sqlite3.IntegrityError:
            pass
    print(f"  ✅ Перенесено из ORDER_EMAIL_TO: {imported} адресов.")
elif existing_count > 0:
    print(f"  ℹ️  В таблице уже {existing_count} адресов, перенос пропущен.")
else:
    print("  ℹ️  ORDER_EMAIL_TO пуста, переносить нечего.")

con.commit()
con.close()

print("\nГотово.")
