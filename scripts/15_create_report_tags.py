"""
scripts/15_create_report_tags.py

Миграция F27 — теги отчётов об операциях.

Две таблицы:

  report_tags  — справочник тегов, администрируется ZMed-staff.
      id, name UNIQUE, color (hex, 7 символов, напр. '#9a2a3a'),
      description NULL, active DEFAULT 1, created_at

  operation_report_tags  — many-to-many между отчётами и тегами.
      report_id, tag_id   (PK составной)

Идемпотентна.

Запуск:
    cd /root/zmed_pwa && python scripts/15_create_report_tags.py
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

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
CREATE TABLE IF NOT EXISTS report_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    color       TEXT NOT NULL DEFAULT '#9a2a3a',
    description TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
)
""")
print("  ✅ report_tags.")

cur.execute("""
CREATE TABLE IF NOT EXISTS operation_report_tags (
    report_id INTEGER NOT NULL,
    tag_id    INTEGER NOT NULL,
    PRIMARY KEY (report_id, tag_id),
    FOREIGN KEY (report_id) REFERENCES operation_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id)    REFERENCES report_tags(id)       ON DELETE CASCADE
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_report_tags_tag ON operation_report_tags(tag_id)")
print("  ✅ operation_report_tags.")

# Начальный набор тегов (один раз, пропускаем конфликты)
cur.execute("SELECT COUNT(*) FROM report_tags")
if cur.fetchone()[0] == 0:
    now = datetime.now(timezone.utc).isoformat()
    seed = [
        ("Осложнения", "#dc2626", "В ходе операции возникли осложнения"),
        ("Требует разбора", "#f59e0b", "Нужен клинический разбор с ZMed"),
        ("Нестандарт", "#8b5cf6", "Операция вне типового протокола"),
        ("VIP", "#0891b2", "Отмечено как особо важный случай"),
        ("Тренинг", "#059669", "Операция в рамках обучения / тренинга"),
    ]
    for name, color, descr in seed:
        try:
            cur.execute(
                "INSERT INTO report_tags (name, color, description, active, created_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (name, color, descr, now),
            )
        except sqlite3.IntegrityError:
            pass
    print(f"  ✅ Seed тегов: {len(seed)}")

con.commit()
con.close()
print("\nГотово.")
