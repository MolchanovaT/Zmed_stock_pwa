"""
app/api/activity.py

Логирование действий пользователей PWA в таблицу pwa_activity.
Вызывается из эндпоинтов fire-and-forget через asyncio.create_task().
"""

import json
from datetime import datetime, timezone

from app.db.models import PwaActivity
from app.db.session import AsyncSessionLocal


async def log_activity(user_id: int, username: str, action: str, detail: dict | None = None):
    """Записывает действие пользователя. Ошибки логирования не пробрасываются."""
    try:
        async with AsyncSessionLocal() as s:
            s.add(PwaActivity(
                user_id=user_id,
                username=username,
                action=action,
                detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                created_at=datetime.now(timezone.utc),
            ))
            await s.commit()
    except Exception:
        pass
