"""
scripts/13_create_operation_report_audit.py

Миграция F20 — audit log для отчётов об операциях.

Таблица operation_report_audit:
    id              INTEGER PK
    report_id       INTEGER NULL  — FK на operation_reports.id (NULL если
                                     исходный отчёт удалён)
    organization_id INTEGER NOT NULL — для RLS
    action          TEXT NOT NULL — 'submit' | 'edit_after_submit' | 'delete_submitted'
    user_id         INTEGER NOT NULL — кто совершил действие
    snapshot_json   TEXT NOT NULL — полный снимок OperationReport на момент
    note            TEXT NULL     — комментарий (почему правили)
    created_at      TEXT NOT NULL

Индексы:
    idx_opr_audit_report  ON (report_id)
    idx_opr_audit_org     ON (organization_id)
    idx_opr_audit_user    ON (user_id)

Идемпотентна.

Запуск:
    cd /root/zmed_pwa && python scripts/13_create_operation_report_audit.py
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
CREATE TABLE IF NOT EXISTS operation_report_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       INTEGER,
    organization_id INTEGER NOT NULL,
    action          TEXT NOT NULL,
    user_id         INTEGER NOT NULL,
    snapshot_json   TEXT NOT NULL,
    note            TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (report_id)       REFERENCES operation_reports(id) ON DELETE SET NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id),
    FOREIGN KEY (user_id)         REFERENCES users(id)
)
""")
print("  ✅ operation_report_audit существует / создана.")

cur.execute("CREATE INDEX IF NOT EXISTS idx_opr_audit_report ON operation_report_audit(report_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_opr_audit_org    ON operation_report_audit(organization_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_opr_audit_user   ON operation_report_audit(user_id)")

con.commit()
con.close()

print("\nГотово.")
