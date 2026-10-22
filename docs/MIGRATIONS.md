# Миграции схемы БД

До октября 2026 использовались **скрипты** `scripts/01_create_users_table.py` … `scripts/12_add_email_recipient_kind.py` — идемпотентные Python-скрипты с `CREATE TABLE IF NOT EXISTS` и `ALTER TABLE ADD COLUMN`. Запускались вручную в заданном порядке.

С октября 2026 новые изменения схемы делаются через **Alembic**. Папка `alembic/`, конфиг `alembic.ini`. Текущая стартовая ревизия — `0001` (baseline, no-op), она просто фиксирует точку отсчёта.

## Один раз на каждой БД — пометить baseline

```bash
# Локально (из корня репо, с активированным venv)
alembic stamp 0001

# На проде (/root/zmed_pwa)
cd /root/zmed_pwa && alembic stamp 0001
```

`alembic stamp` НЕ выполняет миграций — просто пишет в таблицу `alembic_version` строку `0001`. Нужно сделать это один раз на каждой БД, где уже есть схема от старых `scripts/XX_*.py`.

**Проверка:**
```bash
alembic current
# должно вывести: 0001 (head)
```

## Как делать новые миграции

### Автогенерация по моделям (рекомендуется)

1. Поменяли `app/db/models.py` (добавили колонку, таблицу и т.п.).
2. Из корня репо:
   ```bash
   alembic revision --autogenerate -m "add_foo_to_bar"
   ```
3. Открыли созданный файл `alembic/versions/XXXX_add_foo_to_bar.py`, **проверили `upgrade()` и `downgrade()`** — Alembic иногда неточен (переименования, enum, индексы).
4. Применили:
   ```bash
   alembic upgrade head
   ```

### Руками (если autogenerate не справляется)

```bash
alembic revision -m "backfill_data"
# → редактируем alembic/versions/XXXX_backfill_data.py
alembic upgrade head
```

## Откат

```bash
alembic downgrade -1          # на одну ревизию назад
alembic downgrade 0001        # к конкретной
```

Все новые ревизии должны содержать корректный `downgrade()` — проверяйте.

## Старые скрипты

`scripts/01_create_users_table.py` … `scripts/12_add_email_recipient_kind.py` оставляем в репо:
- **Как исторический журнал** — чтобы было видно, что меняла схему со временем;
- **Для разворачивания новой БД с нуля** без Alembic — можно запустить их по порядку, затем `alembic stamp 0001`.

Новые изменения через скрипты **НЕ добавлять** — всё через Alembic.

## Нюансы SQLite

- `render_as_batch=True` включён в `alembic/env.py` для SQLite — иначе `ALTER TABLE DROP COLUMN` и подобные операции не сработают. Alembic в этом режиме делает «copy-and-move».
- Для PostgreSQL batch mode не нужен и выключается автоматически.

## Запуск в разных окружениях

Alembic читает `DB_DSN` из `.env`:
- Локаль: `sqlite:///data/implant_stock.db`
- Прод: тот же файл через bind-mount, `sqlite:///data/implant_stock.db` (относительно `/root/zmed_pwa`).
- Тесты: `conftest.py` подменяет `DB_DSN` на tmp, но тесты используют `Base.metadata.create_all` напрямую — Alembic там не вызывается.
