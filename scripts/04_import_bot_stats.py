"""
scripts/04_import_bot_stats.py

Перенос исторических tg_users / tg_interactions из локальных БД ботов
расходников и имплантов в общую PWA-БД. Идемпотентен — повторный запуск
ничего не дублирует.

Источники:
  /root/stockbot2/data/stock.db                   — bot_name='stockbot2'
  /root/stockbot2_implants/data/implant_stock.db  — bot_name='stockbot2_implants'
    (в источнике есть исторические строки с bot_name='stockbot2' — это
     баг middleware имп-бота на старте; переписываем все на 'stockbot2_implants',
     так как impl-БД хранит ТОЛЬКО события имп-бота)

tg_users:        INSERT OR IGNORE по PK (tg_id) — естественная идемпотентность.
tg_interactions: id не передаём (autoincrement PWA), дедуп через
                 NOT EXISTS на (bot_name, user_id, created_at, kind).

Запуск (из корня /root/zmed_pwa):
    python scripts/04_import_bot_stats.py --dry-run   # показать без записи
    python scripts/04_import_bot_stats.py             # реально импортировать
"""

import argparse
import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv("DB_DSN", "sqlite:///data/implant_stock.db")
if not DB_DSN.startswith("sqlite:///"):
    print(f"❌ Скрипт работает только с SQLite. DB_DSN={DB_DSN}")
    sys.exit(1)

PWA_DB = DB_DSN[len("sqlite:///"):]
if not os.path.isabs(PWA_DB):
    PWA_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", PWA_DB))

SOURCES = [
    {
        "path": "/root/stockbot2/data/stock.db",
        "label": "stockbot2 (расходники)",
        "bot_name_override": None,
    },
    {
        "path": "/root/stockbot2_implants/data/implant_stock.db",
        "label": "stockbot2_implants (импланты)",
        "bot_name_override": "stockbot2_implants",
    },
]

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true", help="Только посчитать, ничего не писать")
args = ap.parse_args()

print(f"PWA-БД: {PWA_DB}")
print(f"Режим:  {'DRY-RUN (без записи)' if args.dry_run else 'РЕАЛЬНЫЙ ИМПОРТ'}")
print()

if not os.path.exists(PWA_DB):
    print(f"❌ PWA-БД не найдена: {PWA_DB}")
    sys.exit(1)

con = sqlite3.connect(PWA_DB)
con.execute("PRAGMA busy_timeout = 30000")
con.execute("PRAGMA foreign_keys = OFF")
cur = con.cursor()

before_users = cur.execute("SELECT COUNT(*) FROM tg_users").fetchone()[0]
before_int = cur.execute("SELECT COUNT(*) FROM tg_interactions").fetchone()[0]
print(f"PWA до импорта: tg_users={before_users}, tg_interactions={before_int}")
print()

total_added_users = 0
total_added_int = 0

for src in SOURCES:
    print(f"━━ {src['label']} ━━")
    print(f"   Файл: {src['path']}")

    if not os.path.exists(src["path"]):
        print(f"   ⚠ Файл не найден — пропускаем")
        print()
        continue

    cur.execute("ATTACH DATABASE ? AS ext", (src["path"],))

    tables = {r[0] for r in cur.execute(
        "SELECT name FROM ext.sqlite_master WHERE type='table'"
    ).fetchall()}
    if "tg_users" not in tables or "tg_interactions" not in tables:
        print(f"   ⚠ В источнике нет tg_users/tg_interactions — пропускаем")
        cur.execute("DETACH DATABASE ext")
        print()
        continue

    src_users = cur.execute("SELECT COUNT(*) FROM ext.tg_users").fetchone()[0]
    src_int = cur.execute("SELECT COUNT(*) FROM ext.tg_interactions").fetchone()[0]
    print(f"   В источнике: tg_users={src_users}, tg_interactions={src_int}")

    if src["bot_name_override"]:
        breakdown = cur.execute(
            "SELECT bot_name, COUNT(*) FROM ext.tg_interactions GROUP BY bot_name"
        ).fetchall()
        print(f"   Исходные bot_name (все будут переписаны на "
              f"'{src['bot_name_override']}'): {breakdown}")

    bn_expr = "?" if src["bot_name_override"] else "e.bot_name"
    bn_params = (src["bot_name_override"],) if src["bot_name_override"] else ()

    new_users = cur.execute("""
        SELECT COUNT(*) FROM ext.tg_users e
        WHERE NOT EXISTS (SELECT 1 FROM tg_users m WHERE m.id = e.id)
    """).fetchone()[0]

    new_int = cur.execute(f"""
        SELECT COUNT(*) FROM ext.tg_interactions e
        WHERE NOT EXISTS (
            SELECT 1 FROM tg_interactions m
            WHERE m.bot_name = {bn_expr}
              AND m.user_id = e.user_id
              AND m.created_at = e.created_at
              AND m.kind = e.kind
        )
    """, bn_params).fetchone()[0]
    print(f"   К добавлению: tg_users +{new_users}, tg_interactions +{new_int}")

    if not args.dry_run:
        cur.execute("""
            INSERT OR IGNORE INTO tg_users
                (id, is_bot, username, first_name, last_name, language_code,
                 first_seen_at, last_seen_at)
            SELECT id, is_bot, username, first_name, last_name, language_code,
                   first_seen_at, last_seen_at
            FROM ext.tg_users
        """)
        added_users = cur.rowcount

        cur.execute(f"""
            INSERT INTO tg_interactions
                (bot_name, user_id, chat_id, chat_type, kind, payload, created_at)
            SELECT {bn_expr}, e.user_id, e.chat_id, e.chat_type, e.kind, e.payload, e.created_at
            FROM ext.tg_interactions e
            WHERE NOT EXISTS (
                SELECT 1 FROM tg_interactions m
                WHERE m.bot_name = {bn_expr}
                  AND m.user_id = e.user_id
                  AND m.created_at = e.created_at
                  AND m.kind = e.kind
            )
        """, bn_params + bn_params)
        added_int = cur.rowcount

        con.commit()
        total_added_users += added_users
        total_added_int += added_int
        print(f"   ✅ Добавлено: tg_users={added_users}, tg_interactions={added_int}")

    cur.execute("DETACH DATABASE ext")
    print()

after_users = cur.execute("SELECT COUNT(*) FROM tg_users").fetchone()[0]
after_int = cur.execute("SELECT COUNT(*) FROM tg_interactions").fetchone()[0]
print("━━ Итог ━━")
print(f"PWA после: tg_users={after_users} ({after_users - before_users:+d}), "
      f"tg_interactions={after_int} ({after_int - before_int:+d})")

con.close()
print()
print("✅ Готово" if not args.dry_run else "[dry-run] ничего не записано — запусти без --dry-run для импорта")
