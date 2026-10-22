"""
scripts/16_create_fts_reports.py

Миграция F26 — полнотекстовый поиск по отчётам об операциях (SQLite FTS5).

Создаёт:
  * operation_reports_fts  — виртуальная таблица FTS5 (content=operation_reports)
  * 3 триггера синхронизации (insert/update/delete)
  * rebuild при первом запуске (заполняет FTS из существующих данных)

Поля в индексе:
  patient_code, doctor_name, operation_type, diagnosis_text,
  complications, notes

Поиск:
  WHERE id IN (SELECT rowid FROM operation_reports_fts WHERE operation_reports_fts MATCH :q)

Идемпотентна: виртуальную таблицу и триггеры создаёт только если их ещё нет.

Запуск:
    cd /root/zmed_pwa && python scripts/16_create_fts_reports.py
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

# Проверим, что FTS5 доступен
try:
    cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(x)")
    cur.execute("DROP TABLE _fts5_test")
except sqlite3.OperationalError as e:
    print(f"❌ FTS5 не поддерживается этой сборкой SQLite: {e}")
    sys.exit(1)

cur.execute("""
CREATE VIRTUAL TABLE IF NOT EXISTS operation_reports_fts USING fts5(
    patient_code,
    doctor_name,
    operation_type,
    diagnosis_text,
    complications,
    notes,
    content='operation_reports',
    content_rowid='id',
    tokenize='unicode61'
)
""")
print("  ✅ operation_reports_fts создана / уже есть.")

# Триггеры синхронизации
cur.execute("""
CREATE TRIGGER IF NOT EXISTS operation_reports_fts_ai
AFTER INSERT ON operation_reports BEGIN
    INSERT INTO operation_reports_fts(
        rowid, patient_code, doctor_name, operation_type,
        diagnosis_text, complications, notes
    ) VALUES (
        new.id, new.patient_code, new.doctor_name, new.operation_type,
        COALESCE(new.diagnosis_text, ''), COALESCE(new.complications, ''), COALESCE(new.notes, '')
    );
END
""")
cur.execute("""
CREATE TRIGGER IF NOT EXISTS operation_reports_fts_ad
AFTER DELETE ON operation_reports BEGIN
    INSERT INTO operation_reports_fts(
        operation_reports_fts, rowid, patient_code, doctor_name, operation_type,
        diagnosis_text, complications, notes
    ) VALUES (
        'delete', old.id, old.patient_code, old.doctor_name, old.operation_type,
        COALESCE(old.diagnosis_text, ''), COALESCE(old.complications, ''), COALESCE(old.notes, '')
    );
END
""")
cur.execute("""
CREATE TRIGGER IF NOT EXISTS operation_reports_fts_au
AFTER UPDATE ON operation_reports BEGIN
    INSERT INTO operation_reports_fts(
        operation_reports_fts, rowid, patient_code, doctor_name, operation_type,
        diagnosis_text, complications, notes
    ) VALUES (
        'delete', old.id, old.patient_code, old.doctor_name, old.operation_type,
        COALESCE(old.diagnosis_text, ''), COALESCE(old.complications, ''), COALESCE(old.notes, '')
    );
    INSERT INTO operation_reports_fts(
        rowid, patient_code, doctor_name, operation_type,
        diagnosis_text, complications, notes
    ) VALUES (
        new.id, new.patient_code, new.doctor_name, new.operation_type,
        COALESCE(new.diagnosis_text, ''), COALESCE(new.complications, ''), COALESCE(new.notes, '')
    );
END
""")
print("  ✅ Триггеры синхронизации.")

# Rebuild: наполнить из существующих отчётов (безопасно повторять)
cur.execute("INSERT INTO operation_reports_fts(operation_reports_fts) VALUES('rebuild')")
print("  ✅ Rebuild FTS выполнен.")

con.commit()
con.close()
print("\nГотово.")
