"""
app/api/rate_limit.py

Простой in-memory rate limiter per-user. Для production-масштаба стоило бы
взять Redis + slowapi, но на наши тома (несколько клиник, десятки юзеров,
~ пара запросов/сек на сканере в худшем случае) этого достаточно.

Ограничения:
  * Один процесс = одна карта. Если uvicorn запущен с --workers N, у каждого
    своя копия — лимит де-факто умножается на N. Для сканера это не страшно.
  * Нет persist между рестартами — тоже допустимо (при рестарте лимит
    обнуляется).

Применение:
    @router.get("/scan")
    async def scan(..., _rl=Depends(scan_rate_limit)):
        ...
"""

from collections import defaultdict, deque
from time import monotonic

from fastapi import Depends, HTTPException, status

from app.api.auth import get_current_user
from app.db.models import User


# ── Общая структура: dict[(bucket_name, user_id)] -> deque[timestamp] ───────

_HITS: dict[tuple[str, int], deque[float]] = defaultdict(deque)


def _check(bucket: str, user_id: int, *, per_seconds: float,
            max_hits: int) -> None:
    """Поднимает HTTP 429, если за последние per_seconds было >=max_hits запросов."""
    now = monotonic()
    key = (bucket, user_id)
    q = _HITS[key]
    # Выкидываем старые
    while q and (now - q[0]) > per_seconds:
        q.popleft()
    if len(q) >= max_hits:
        # Отдадим Retry-After = сколько ждать до самой старой «отвалившейся» точки
        retry_after = max(1, int(per_seconds - (now - q[0])))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много запросов. Повторите через {retry_after} с.",
            headers={"Retry-After": str(retry_after)},
        )
    q.append(now)


# ── Пресеты: FastAPI-dependency под конкретный endpoint ─────────────────────

async def scan_rate_limit(current_user: User = Depends(get_current_user)) -> None:
    """20 запросов на /scan за 60 секунд на одного юзера."""
    _check("scan", current_user.id, per_seconds=60.0, max_hits=20)


async def upload_rate_limit(current_user: User = Depends(get_current_user)) -> None:
    """30 загрузок файлов отчётов за 60 секунд на одного юзера."""
    _check("upload", current_user.id, per_seconds=60.0, max_hits=30)
