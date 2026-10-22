"""
scripts/14_create_otp_codes.py

Миграция F21 — Email-OTP подпись отчётов.

Таблица otp_codes:
    id          INTEGER PK
    user_id     INTEGER NOT NULL  — кому выдан (FK users.id)
    purpose     TEXT NOT NULL     — "report_submit:{report_id}" и т.п.
    code_hash   TEXT NOT NULL     — SHA-256 от кода + соль (JWT_SECRET)
    expires_at  TEXT NOT NULL     — ISO datetime UTC
    used_at     TEXT NULL         — проставляется при verify
    created_at  TEXT NOT NULL

Индексы:
    idx_otp_user_purpose ON (user_id, purpose)
    idx_otp_expires      ON (expires_at)

Идемпотентна.

Запуск:
    cd /root/zmed_pwa && python scripts/14_create_otp_codes.py
"""

import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv("DB_DSN", "sqlite:///stock.db")

if not DB_DSN.startswith("sqlite:///"):
    print(f"❌ Только SQLite. DB_DSN={DB_DSN}")
    sys.exit(1)

db_path = DB_DSN[len("sqlite:///"):]
if not os.path.isabs(db_path):
    db_path = os.path.join(os.path.dirname(__file__), "..", db_path)
db_path = os.path.abspath(db_path)

print(f"База данных: {db_path}")

con = sqlite3.connect(db_path)
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS otp_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    purpose     TEXT NOT NULL,
    code_hash   TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_otp_user_purpose ON otp_codes(user_id, purpose)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_otp_expires ON otp_codes(expires_at)")
print("  ✅ otp_codes существует / создана.")

con.commit()
con.close()
print("\nГотово.")
