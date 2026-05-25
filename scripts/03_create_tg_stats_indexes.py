"""
scripts/03_create_tg_stats_indexes.py

Одноразовый скрипт: добавляет индексы на tg_interactions в PWA-БД.
Нужно для производительности страницы /tg-stats при росте таблицы
(после подключения двух ботов остатков к общей БД и переноса истории).

Запуск (один раз на сервере, из корня /root/zmed_pwa):
    python scripts/03_create_tg_stats_indexes.py
"""

import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv("DB_DSN", "sqlite:///stock.db")

if not DB_DSN.startswith("sqlite:///"):
    print(f"❌ Скрипт работает только с SQLite. DB_DSN={DB_DSN}")
    sys.exit(1)

db_path = DB_DSN[len("sqlite:///"):]
if not os.path.isabs(db_path):
    db_path = os.path.join(os.path.dirname(__file__), "..", db_path)

print(f"База данных: {db_path}")

con = sqlite3.connect(db_path)
cur = con.cursor()

for name, ddl in [
    ("ix_tg_interactions_created_at",
     "CREATE INDEX IF NOT EXISTS ix_tg_interactions_created_at ON tg_interactions(created_at)"),
    ("ix_tg_interactions_user_id",
     "CREATE INDEX IF NOT EXISTS ix_tg_interactions_user_id ON tg_interactions(user_id)"),
    ("ix_tg_interactions_bot_name",
     "CREATE INDEX IF NOT EXISTS ix_tg_interactions_bot_name ON tg_interactions(bot_name)"),
]:
    print(f"  CREATE INDEX IF NOT EXISTS {name}...")
    cur.execute(ddl)

con.commit()
con.close()
print("✅ Готово")
