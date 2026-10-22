"""
scripts/09_create_organizations.py

Миграция ядра H0 — ввод понятия "организация" для row-level security.

Создаёт:
  1) Таблицу organizations:
        id         INTEGER PK
        name       TEXT NOT NULL UNIQUE
        inn        TEXT NULL                        — опциональная связь с inn_lpu
        kind       TEXT NOT NULL                    — 'zmed' | 'clinic'
        active     INTEGER NOT NULL DEFAULT 1
        created_at TEXT NOT NULL

  2) Колонку users.organization_id INTEGER NULL — FK на organizations.id.
     Для существующих пользователей НЕ выставляется автоматически
     (кроме сотрудников ZMed — см. ниже).

При первом запуске:
  - создаётся организация "ZMed" (kind='zmed'), если её ещё нет;
  - всем is_superuser=1 c organization_id IS NULL проставляется ZMed —
    чтобы они не потеряли доступ, когда новые модули начнут требовать
    organization_id.

Идемпотентна.

Запуск на проде:
    cd /root/zmed_pwa && python scripts/09_create_organizations.py
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

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

# ── 1. organizations ──────────────────────────────────────────────────────────

cur.execute("""
CREATE TABLE IF NOT EXISTS organizations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    inn        TEXT,
    kind       TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
)
""")
print("  ✅ organizations существует / создана.")

cur.execute("CREATE INDEX IF NOT EXISTS idx_organizations_kind ON organizations(kind)")

# ── 2. users.organization_id ──────────────────────────────────────────────────

cur.execute("PRAGMA table_info(users)")
user_cols = {row[1] for row in cur.fetchall()}

if not user_cols:
    print("❌ Таблица users не найдена. Сначала выполните scripts/01_create_users_table.py")
    sys.exit(1)

if "organization_id" in user_cols:
    print("  ℹ️  users.organization_id уже есть, пропускаю.")
else:
    cur.execute("ALTER TABLE users ADD COLUMN organization_id INTEGER")
    print("  ✅ users.organization_id добавлен.")

cur.execute("CREATE INDEX IF NOT EXISTS idx_users_organization_id ON users(organization_id)")

# ── 3. Запись ZMed + привязка существующих супер-юзеров ───────────────────────

cur.execute("SELECT id FROM organizations WHERE kind = 'zmed' LIMIT 1")
row = cur.fetchone()

if row:
    zmed_id = row[0]
    print(f"  ℹ️  Организация ZMed уже существует (id={zmed_id}).")
else:
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO organizations (name, inn, kind, active, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("ZMed", None, "zmed", 1, now),
    )
    zmed_id = cur.lastrowid
    print(f"  ✅ Создана организация ZMed (id={zmed_id}).")

cur.execute("""
    UPDATE users
       SET organization_id = ?
     WHERE organization_id IS NULL
       AND is_superuser = 1
""", (zmed_id,))
if cur.rowcount:
    print(f"  ✅ Привязано к ZMed супер-пользователей: {cur.rowcount}.")
else:
    print("  ℹ️  Все супер-пользователи уже имеют organization_id.")

con.commit()
con.close()

print("\nГотово.")
