"""
scripts/02_import_users.py

Одноразовый импорт данных в новую таблицу `users`.
Запускать ПОСЛЕ scripts/01_create_users_table.py.

Что делает:
  1. admin_users (PWA) → users: username/password_hash/modules.
     is_superuser=1 для логинов из SUPERUSERS, остальным 0.
  2. allowed_users из БД бота расходников → users: tg_id/full_name,
     modules='["bot_supplies"]'.
  3. allowed_users из БД бота имплантов → upsert по tg_id:
     если уже есть (из шага 2) — добавляем 'bot_implants' к modules,
     иначе создаём новую запись с modules='["bot_implants"]'.
  4. allowed_users в PWA-БД пустая, не трогаем.

После запуска:
  - в users будет 4 PWA-юзера + 25 бот-юзеров (все с обоими bot_*-модулями).
  - 3 пары admin/tg, описывающие одного человека (molchanova/Tatiana Molchanova,
    R_Bereza/Roman Bereza, KirinaOM/Kirina Olga) НЕ сливаются автоматически —
    свести вручную через UI «Пользователи» позже.

Запуск:
    cd /root/zmed_pwa && python scripts/02_import_users.py
"""

import json
import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv("DB_DSN", "sqlite:///stock.db")

if not DB_DSN.startswith("sqlite:///"):
    print(f"❌ Этот скрипт работает только с SQLite. DB_DSN={DB_DSN}")
    sys.exit(1)

pwa_db_path = DB_DSN[len("sqlite:///"):]
if not os.path.isabs(pwa_db_path):
    pwa_db_path = os.path.join(os.path.dirname(__file__), "..", pwa_db_path)
pwa_db_path = os.path.abspath(pwa_db_path)

# Прод-пути к БД «спящих» ботов. Для локального теста — поменять руками.
BOT_SUPPLIES_DB = "/root/stockbot2/data/stock.db"
BOT_IMPLANTS_DB = "/root/stockbot2_implants/data/implant_stock.db"

SUPERUSERS = {"admin", "molchanova"}

print(f"PWA БД:          {pwa_db_path}")
print(f"Бот расходников: {BOT_SUPPLIES_DB}")
print(f"Бот имплантов:   {BOT_IMPLANTS_DB}")

for path in (pwa_db_path, BOT_SUPPLIES_DB, BOT_IMPLANTS_DB):
    if not os.path.exists(path):
        print(f"❌ Файл БД не найден: {path}")
        sys.exit(1)

con = sqlite3.connect(pwa_db_path)
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
if not cur.fetchone():
    print("❌ Таблица users не существует. Сначала запусти scripts/01_create_users_table.py.")
    con.close()
    sys.exit(1)

cur.execute("SELECT COUNT(*) FROM users")
existing_count = cur.fetchone()[0]
if existing_count > 0:
    print(f"⚠️  В таблице users уже {existing_count} строк. Импорт прерван, чтобы не дублировать.")
    print("    Если нужно перезапустить — очисти таблицу: DELETE FROM users;")
    con.close()
    sys.exit(1)

# ── 1. admin_users PWA ────────────────────────────────────────────────────────
print("\n--- admin_users → users ---")
cur.execute("SELECT username, password_hash, modules FROM admin_users ORDER BY id")
admin_rows = cur.fetchall()
for username, password_hash, modules in admin_rows:
    is_super = 1 if username in SUPERUSERS else 0
    cur.execute(
        "INSERT INTO users (username, password_hash, modules, is_superuser, active) "
        "VALUES (?, ?, ?, ?, 1)",
        (username, password_hash, modules, is_super),
    )
    print(f"  + {username} (superuser={is_super}, modules={modules})")
print(f"  Итого PWA-юзеров: {len(admin_rows)}")

# ── 2. allowed_users из бота расходников ──────────────────────────────────────
print("\n--- allowed_users (supplies) → users ---")
con_sup = sqlite3.connect(BOT_SUPPLIES_DB)
sup_rows = con_sup.execute(
    "SELECT tg_id, full_name, title FROM allowed_users ORDER BY id"
).fetchall()
con_sup.close()

modules_supplies = json.dumps(["bot_supplies"])
for tg_id, full_name, title in sup_rows:
    cur.execute(
        "INSERT INTO users (tg_id, full_name, title, modules, is_superuser, active) "
        "VALUES (?, ?, ?, ?, 0, 1)",
        (tg_id, full_name, title, modules_supplies),
    )
print(f"  Итого добавлено: {len(sup_rows)}")

# ── 3. allowed_users из бота имплантов — upsert по tg_id ──────────────────────
print("\n--- allowed_users (implants) → users (upsert) ---")
con_imp = sqlite3.connect(BOT_IMPLANTS_DB)
imp_rows = con_imp.execute(
    "SELECT tg_id, full_name, title FROM allowed_users ORDER BY id"
).fetchall()
con_imp.close()

added = 0
merged = 0
for tg_id, full_name, title in imp_rows:
    cur.execute(
        "SELECT id, modules FROM users WHERE tg_id = ?",
        (tg_id,),
    )
    row = cur.fetchone()
    if row:
        user_id, current_modules_json = row
        current = json.loads(current_modules_json) if current_modules_json else []
        if "bot_implants" not in current:
            current.append("bot_implants")
        cur.execute(
            "UPDATE users SET modules = ? WHERE id = ?",
            (json.dumps(current), user_id),
        )
        merged += 1
    else:
        cur.execute(
            "INSERT INTO users (tg_id, full_name, title, modules, is_superuser, active) "
            "VALUES (?, ?, ?, ?, 0, 1)",
            (tg_id, full_name, title, json.dumps(["bot_implants"])),
        )
        added += 1
print(f"  Слито с supplies: {merged}, новых: {added}")

con.commit()

# ── Финальная сводка ──────────────────────────────────────────────────────────
total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
pwa_only = cur.execute(
    "SELECT COUNT(*) FROM users WHERE username IS NOT NULL AND tg_id IS NULL"
).fetchone()[0]
bot_only = cur.execute(
    "SELECT COUNT(*) FROM users WHERE username IS NULL AND tg_id IS NOT NULL"
).fetchone()[0]
both = cur.execute(
    "SELECT COUNT(*) FROM users WHERE username IS NOT NULL AND tg_id IS NOT NULL"
).fetchone()[0]
supers = cur.execute("SELECT COUNT(*) FROM users WHERE is_superuser = 1").fetchone()[0]

print("\n=== Сводка ===")
print(f"Всего записей:    {total}")
print(f"PWA-only:         {pwa_only}")
print(f"Bot-only:         {bot_only}")
print(f"PWA+Bot (слитые): {both}")
print(f"Суперюзеров:      {supers}")
print("\n📌 Не забудь свести вручную через UI 3 пары: ")
print("    molchanova ↔ Tatiana Molchanova (tg_id 924263690)")
print("    R_Bereza   ↔ Roman Bereza       (tg_id 393760399)")
print("    KirinaOM   ↔ Kirina Olga        (tg_id 1077000722)")

con.close()
print("\n✅ Импорт завершён.")
