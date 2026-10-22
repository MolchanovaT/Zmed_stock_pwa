"""
scripts/11_create_clinic_stock.py

Миграция H2 — модуль «Учёт товара на ОХ (ответственное хранение) в клинике».

Четыре таблицы:

  clinic_stock_locations         Места хранения внутри клиники
      id, organization_id, name, kind ('warehouse'|'surgery'|'other'), active

  clinic_stock_items             Партии товара на ОХ (один SKU может быть
                                 несколькими партиями из-за lot/exp)
      id, organization_id, article, nomenclature, characteristic,
      barcode (nullable), lot_number, expiration_date (YYYY-MM-DD, nullable),
      received_at, received_doc_number

  clinic_stock_balances          Остатки: partition по (item_id, location_id)
      id, item_id, location_id, quantity
      UNIQUE (item_id, location_id)

  clinic_stock_movements         Append-only журнал движений
      id, organization_id, kind,
      item_id, from_location_id, to_location_id, quantity,
      user_id, operation_report_id (nullable — связка consume → отчёт H1),
      doc_number, note, created_at

При первом запуске: НИЧЕГО не сидим — локации клиника заводит сама.

Идемпотентна.

Запуск:
    cd /root/zmed_pwa && python scripts/11_create_clinic_stock.py
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
CREATE TABLE IF NOT EXISTS clinic_stock_locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_loc_org ON clinic_stock_locations(organization_id)")
cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_clinic_loc_org_name ON clinic_stock_locations(organization_id, name)")
print("  ✅ clinic_stock_locations.")

cur.execute("""
CREATE TABLE IF NOT EXISTS clinic_stock_items (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id      INTEGER NOT NULL,
    article              TEXT NOT NULL,
    nomenclature         TEXT NOT NULL,
    characteristic       TEXT,
    barcode              TEXT,
    lot_number           TEXT,
    expiration_date      TEXT,
    received_at          TEXT NOT NULL,
    received_doc_number  TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_item_org ON clinic_stock_items(organization_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_item_article ON clinic_stock_items(article)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_item_barcode ON clinic_stock_items(barcode)")
print("  ✅ clinic_stock_items.")

cur.execute("""
CREATE TABLE IF NOT EXISTS clinic_stock_balances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (item_id)     REFERENCES clinic_stock_items(id)     ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES clinic_stock_locations(id) ON DELETE CASCADE,
    UNIQUE (item_id, location_id)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_bal_item ON clinic_stock_balances(item_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_bal_loc  ON clinic_stock_balances(location_id)")
print("  ✅ clinic_stock_balances.")

cur.execute("""
CREATE TABLE IF NOT EXISTS clinic_stock_movements (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id      INTEGER NOT NULL,
    kind                 TEXT NOT NULL,
    item_id              INTEGER NOT NULL,
    from_location_id     INTEGER,
    to_location_id       INTEGER,
    quantity             INTEGER NOT NULL,
    user_id              INTEGER NOT NULL,
    operation_report_id  INTEGER,
    doc_number           TEXT,
    note                 TEXT,
    created_at           TEXT NOT NULL,
    FOREIGN KEY (organization_id)     REFERENCES organizations(id),
    FOREIGN KEY (item_id)             REFERENCES clinic_stock_items(id),
    FOREIGN KEY (from_location_id)    REFERENCES clinic_stock_locations(id),
    FOREIGN KEY (to_location_id)      REFERENCES clinic_stock_locations(id),
    FOREIGN KEY (user_id)             REFERENCES users(id),
    FOREIGN KEY (operation_report_id) REFERENCES operation_reports(id)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_mov_org  ON clinic_stock_movements(organization_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_mov_item ON clinic_stock_movements(item_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_mov_date ON clinic_stock_movements(created_at)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clinic_mov_report ON clinic_stock_movements(operation_report_id)")
print("  ✅ clinic_stock_movements.")

con.commit()
con.close()

print("\nГотово.")
