"""
app/api/inn_check.py

Проверка контрагентов по ИНН (модуль inn_check).
Перенесено из zm_bot.

Эндпоинты:
  POST /api/inn-check/check          — проверить ИНН (тип: diler | lpu)
  GET  /api/inn-check/dilers         — список дилеров (admin)
  GET  /api/inn-check/lpu            — список ЛПУ (admin)
  GET  /api/inn-check/pending        — список заявок (admin)
  POST /api/inn-check/upload-csv     — загрузить CSV для обновления таблицы (admin)
  POST /api/inn-check/pending/add    — добавить заявку вручную
"""

import asyncio
import io
from datetime import date
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, delete

from app.api.activity import log_activity
from app.api.auth import get_current_user
from app.db.models import AdminUser, InnDiler, InnLpu, InnPending
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/inn-check", tags=["inn-check"])


# ── Схемы ─────────────────────────────────────────────────────────────────────

class CheckRequest(BaseModel):
    inn: str
    org_type: Literal["diler", "lpu"]


class CheckResult(BaseModel):
    status: str        # approved | denied | denied_date | pending | not_found
    name: Optional[str] = None
    date: Optional[str] = None


class PendingAddRequest(BaseModel):
    name: str
    inn: str


# ── Проверка ИНН ──────────────────────────────────────────────────────────────

@router.post("/check", response_model=CheckResult)
async def check_inn(
    body: CheckRequest,
    current_user: AdminUser = Depends(get_current_user),
):
    """
    Проверяет ИНН контрагента.
    Возвращает статус: approved | denied | denied_date | pending | not_found
    """
    inn = body.inn.strip()
    Model = InnDiler if body.org_type == "diler" else InnLpu

    async with AsyncSessionLocal() as s:
        # Ищем в основной таблице
        row = (await s.execute(select(Model).where(Model.inn == inn))).scalars().first()
        if row:
            if row.allowed:
                return CheckResult(status="approved", name=row.name)
            else:
                return CheckResult(status="denied", name=row.name)

        # Ищем в заявках
        pending = (await s.execute(
            select(InnPending).where(InnPending.inn == inn)
        )).scalars().first()

        if pending:
            if pending.denied:
                result = CheckResult(status="denied_date", name=pending.name, date=pending.date)
            elif pending.approved:
                result = CheckResult(status="approved", name=pending.name)
            else:
                result = CheckResult(status="pending", name=pending.name, date=pending.date)
        else:
            result = CheckResult(status="not_found")

    asyncio.create_task(log_activity(
        current_user.id, current_user.username, "inn_check",
        {"inn": body.inn, "org_type": body.org_type, "status": result.status,
         "name": result.name},
    ))
    return result


# ── Списки (чтение) ───────────────────────────────────────────────────────────

@router.get("/dilers")
async def get_dilers(_: AdminUser = Depends(get_current_user)):
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(InnDiler).order_by(InnDiler.name))).scalars().all()
    return {"items": [{"id": r.id, "name": r.name, "inn": r.inn, "allowed": bool(r.allowed)} for r in rows]}


@router.get("/lpu")
async def get_lpu(_: AdminUser = Depends(get_current_user)):
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(InnLpu).order_by(InnLpu.name))).scalars().all()
    return {"items": [{"id": r.id, "name": r.name, "inn": r.inn, "allowed": bool(r.allowed)} for r in rows]}


@router.get("/pending")
async def get_pending(_: AdminUser = Depends(get_current_user)):
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(InnPending).order_by(InnPending.date.desc()))).scalars().all()
    return {"items": [
        {"id": r.id, "name": r.name, "inn": r.inn,
         "date": r.date, "approved": bool(r.approved), "denied": bool(r.denied)}
        for r in rows
    ]}


# ── Добавить заявку вручную ───────────────────────────────────────────────────

@router.post("/pending/add")
async def add_pending(
    body: PendingAddRequest,
    _: AdminUser = Depends(get_current_user),
):
    """Добавляет новую заявку на рассмотрение."""
    async with AsyncSessionLocal() as s:
        existing = (await s.execute(
            select(InnPending).where(InnPending.inn == body.inn.strip())
        )).scalars().first()
        if existing:
            raise HTTPException(status_code=400, detail="Заявка с таким ИНН уже существует")

        s.add(InnPending(
            name=body.name.strip(),
            inn=body.inn.strip(),
            date=str(date.today()),
        ))
        await s.commit()
    return {"ok": True}


# ── Загрузка CSV (admin) ───────────────────────────────────────────────────────

@router.post("/upload-csv")
async def upload_csv(
    table: str = Form(...),   # dilers | lpu | pending
    file: UploadFile = File(...),
    _: AdminUser = Depends(get_current_user),
):
    """
    Загружает CSV и заменяет содержимое таблицы.
    Формат CSV (cp1251, запятая): name,inn[,allowed][,date,approved,denied]
    """
    if table not in ("dilers", "lpu", "pending"):
        raise HTTPException(status_code=400, detail="Неверная таблица. Допустимо: dilers, lpu, pending")

    content = await file.read()
    try:
        df = pd.read_csv(
            io.BytesIO(content),
            encoding="cp1251",
            dtype={"inn": str},
            sep=",",
            skipinitialspace=True,
        )
        df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
        df["inn"] = df["inn"].astype(str)
        df["name"] = df["name"].astype(str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Ошибка чтения CSV: {e}")

    async with AsyncSessionLocal() as s:
        if table == "dilers":
            await s.execute(delete(InnDiler))
            for _, row in df.iterrows():
                s.add(InnDiler(name=row["name"], inn=row["inn"], allowed=1))
        elif table == "lpu":
            await s.execute(delete(InnLpu))
            for _, row in df.iterrows():
                s.add(InnLpu(name=row["name"], inn=row["inn"], allowed=1))
        elif table == "pending":
            await s.execute(delete(InnPending))
            for _, row in df.iterrows():
                s.add(InnPending(
                    name=row["name"],
                    inn=row["inn"],
                    date=str(row.get("date", "")) or None,
                    approved=int(bool(row.get("approved", False))),
                    denied=int(bool(row.get("denied", False))),
                ))
        await s.commit()

    return {"ok": True, "rows": len(df)}
