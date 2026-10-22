"""
scripts/10_create_operation_reports.py

Миграция H1 — модуль «Отчёты клиник об операциях».

Таблицы:

  operation_reports
      id                 INTEGER PK
      organization_id    INTEGER NOT NULL   — FK на organizations.id (RLS-ключ)
      user_id            INTEGER NOT NULL   — FK на users.id (кто создал)
      patient_code       TEXT NOT NULL      — обезличенный ID операции (НЕ ФИО)
      operation_date     TEXT NOT NULL      — ISO YYYY-MM-DD
      department         TEXT NULL
      doctor_name        TEXT NOT NULL
      operation_type     TEXT NOT NULL      — свободный текст с автокомплитом (MVP)
      diagnosis_text     TEXT NULL          — свободный текст, 500 символов max (валидирует API)
      implants_used_json TEXT NULL          — JSON-массив [{article, nomenclature, qty, lot_number, serial}]
      complications      TEXT NULL
      notes              TEXT NULL
      status             TEXT NOT NULL      — 'draft' | 'submitted'
      created_at         TEXT NOT NULL
      submitted_at       TEXT NULL

  operation_report_files
      id             INTEGER PK
      report_id      INTEGER NOT NULL   — FK на operation_reports.id
      stored_path    TEXT NOT NULL      — относительный путь внутри data/reports/
      original_name  TEXT NULL
      content_type   TEXT NULL
      size_bytes     INTEGER NULL
      uploaded_at    TEXT NOT NULL

Индексы:
  idx_opreports_org   ON operation_reports(organization_id)
  idx_opreports_user  ON operation_reports(user_id)
  idx_opreports_date  ON operation_reports(operation_date)
  idx_opreport_files_report ON operation_report_files(report_id)

Идемпотентна.

Запуск:
    cd /root/zmed_pwa && python scripts/10_create_operation_reports.py
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

cur.execute("""
CREATE TABLE IF NOT EXISTS operation_reports (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id    INTEGER NOT NULL,
    user_id            INTEGER NOT NULL,
    patient_code       TEXT NOT NULL,
    operation_date     TEXT NOT NULL,
    department         TEXT,
    doctor_name        TEXT NOT NULL,
    operation_type     TEXT NOT NULL,
    diagnosis_text     TEXT,
    implants_used_json TEXT,
    complications      TEXT,
    notes              TEXT,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    submitted_at       TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (user_id)         REFERENCES users(id)
)
""")
print("  ✅ operation_reports существует / создана.")

cur.execute("CREATE INDEX IF NOT EXISTS idx_opreports_org  ON operation_reports(organization_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_opreports_user ON operation_reports(user_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_opreports_date ON operation_reports(operation_date)")

cur.execute("""
CREATE TABLE IF NOT EXISTS operation_report_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL,
    stored_path   TEXT NOT NULL,
    original_name TEXT,
    content_type  TEXT,
    size_bytes    INTEGER,
    uploaded_at   TEXT NOT NULL,
    FOREIGN KEY (report_id) REFERENCES operation_reports(id) ON DELETE CASCADE
)
""")
print("  ✅ operation_report_files существует / создана.")

cur.execute("CREATE INDEX IF NOT EXISTS idx_opreport_files_report ON operation_report_files(report_id)")

con.commit()
con.close()

print("\nГотово.")
