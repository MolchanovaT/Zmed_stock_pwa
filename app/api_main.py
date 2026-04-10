"""
app/api_main.py

Точка входа FastAPI для PWA-бэкенда.

Запуск для разработки:
    uvicorn app.api_main:app --reload --port 8000

В продакшене статика фронтенда раздаётся из frontend/dist/.
"""

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import delete

from app.api.auth import router as auth_router
from app.api.stock import router as stock_router
from app.api.cart import router as cart_router
from app.db.models import PwaActivity
from app.db.session import AsyncSessionLocal

# ── CORS origins ───────────────────────────────────────────────────────────────
_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# ── Приложение ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ZMed Stock Implants API",
    description="REST API для PWA управления остатками имплантов",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Роутеры ────────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(stock_router)
app.include_router(cart_router)


# ── Периодическая чистка старых данных ─────────────────────────────────────────
PWA_ACTIVITY_RETAIN_DAYS: int = int(os.getenv("PWA_ACTIVITY_RETAIN_DAYS", "90"))


@app.on_event("startup")
async def schedule_cleanup():
    import asyncio

    async def cleanup_loop():
        while True:
            await asyncio.sleep(24 * 3600)   # раз в сутки
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=PWA_ACTIVITY_RETAIN_DAYS)
                async with AsyncSessionLocal() as s:
                    result = await s.execute(
                        delete(PwaActivity).where(PwaActivity.created_at < cutoff)
                    )
                    await s.commit()
                    deleted = result.rowcount
                if deleted:
                    print(f"[cleanup] pwa_activity: удалено {deleted} записей старше {PWA_ACTIVITY_RETAIN_DAYS} дней",
                          flush=True)
            except Exception as e:
                print(f"[cleanup] ошибка: {e}", flush=True)

    asyncio.create_task(cleanup_loop())


# ── Раздача фронтенда (продакшен) ──────────────────────────────────────────────
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    # Все статические ресурсы (JS, CSS, assets)
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """
        SPA fallback: отдаём index.html для любого пути,
        не перехваченного API-роутерами.
        """
        index = _FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"detail": "Frontend not built. Run: cd frontend && npm run build"}
