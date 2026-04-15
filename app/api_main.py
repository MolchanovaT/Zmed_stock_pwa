"""
app/api_main.py

Точка входа FastAPI для PWA-бэкенда.

Запуск для разработки:
    uvicorn app.api_main:app --reload --port 8000

В продакшене статика фронтенда раздаётся из frontend/dist/.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.auth import router as auth_router
from app.api.stock import router as stock_router
from app.api.cart import router as cart_router
from app.api.supplies import router as supplies_router
from app.api.inn_check import router as inn_check_router

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
app.include_router(supplies_router)
app.include_router(inn_check_router)


# Чистка pwa_activity перенесена в scheduler.py → nightly_cleanup() (03:00)


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
