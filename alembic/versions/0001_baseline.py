"""baseline

Нулевая ревизия: ничего не делает. Её назначение — зафиксировать стартовую
точку истории Alembic для БД, где схема уже создана через scripts/01..12.

На ТАКОЙ БД (т.е. локально и на проде) делаем ОДИН РАЗ:

    alembic stamp 0001

Это пишет в таблицу alembic_version revision_id='0001' БЕЗ выполнения
upgrade — т.е. не трогает существующие таблицы.

На ЧИСТОЙ БД (например, в юнит-тестах через Base.metadata.create_all)
alembic обычно не используется, но если запустят `alembic upgrade head` —
эта ревизия пропустится (noop), а последующие создадут новые таблицы.

С этого момента все новые изменения схемы делаются через alembic:

    alembic revision --autogenerate -m "Описание"
    alembic upgrade head

См. docs/MIGRATIONS.md для подробного гида.

Revision ID: 0001
Revises:
Create Date: 2026-10-22 00:00:00
"""

from typing import Sequence, Union


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baseline: БД уже содержит все таблицы (создано через scripts/01..12).
    # Если это НЕ так — ревизия у вас не на той БД; делайте `alembic stamp 0001`
    # только после прогона всех scripts/XX_*.py.
    pass


def downgrade() -> None:
    pass
