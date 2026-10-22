"""
app/api/clinic_analytics.py

Аналитика по клиническим модулям.

Все эндпоинты — под RLS: клиника видит свои цифры, ZMed-staff видит все
(с опциональным фильтром ?organization_id=X).

GET /api/clinic-analytics/monthly
    — агрегат по месяцам за последние N месяцев (default 12):
      {month: 'YYYY-MM', reports, implants_total, losses_qty}

GET /api/clinic-analytics/by-clinic
    — агрегат по клиникам за период (date_from/to):
      [{organization_id, name, reports, implants_total, losses_qty}]
    У клинического пользователя — одна строка (своя).

GET /api/clinic-analytics/top-operation-types
    — топ-10 типов операций по частоте за период.
"""

import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.api.scoping import OrgScope, require_org_scope
from app.db.models import (
    ClinicStockMovement, OperationReport, Organization,
)
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/clinic-analytics", tags=["clinic_analytics"])


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_iso_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        date.fromisoformat(s)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Дата: {s!r}")
    return s


def _implants_count(implants_used_json: Optional[str]) -> int:
    if not implants_used_json:
        return 0
    try:
        arr = json.loads(implants_used_json)
    except (ValueError, TypeError):
        return 0
    return sum(int(i.get("qty") or 1) for i in arr if isinstance(i, dict))


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/monthly")
async def monthly(
    months: int = Query(12, ge=1, le=36),
    scope: OrgScope = Depends(require_org_scope),
):
    """Поочерёдно: отчёты по submitted, импланты (сумма qty), потери."""
    today = date.today()
    first_day = (today.replace(day=1)
                  - timedelta(days=31 * (months - 1))).replace(day=1)
    cutoff_date_str = first_day.isoformat()

    async with AsyncSessionLocal() as s:
        # Отчёты + impl
        q_reports = select(OperationReport).where(
            OperationReport.status == "submitted",
            OperationReport.operation_date >= cutoff_date_str,
        )
        if scope.organization_id is not None:
            q_reports = q_reports.where(
                OperationReport.organization_id == scope.organization_id
            )
        reports = list((await s.execute(q_reports)).scalars().all())

        # Потери: write_off + inventory_adjust (abs(qty) для отриц.)
        q_mov = select(ClinicStockMovement).where(
            ClinicStockMovement.kind.in_(("write_off", "inventory_adjust")),
            ClinicStockMovement.created_at >= datetime.combine(first_day, datetime.min.time()),
        )
        if scope.organization_id is not None:
            q_mov = q_mov.where(
                ClinicStockMovement.organization_id == scope.organization_id
            )
        movs = list((await s.execute(q_mov)).scalars().all())

    # Группируем по YYYY-MM
    monthly_map: dict[str, dict] = {}
    cursor = first_day
    while cursor <= today:
        key = cursor.strftime("%Y-%m")
        monthly_map[key] = {"month": key, "reports": 0, "implants_total": 0, "losses_qty": 0}
        # следующий месяц
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1, day=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1, day=1)

    for r in reports:
        k = r.operation_date[:7]
        if k not in monthly_map:
            continue
        monthly_map[k]["reports"] += 1
        monthly_map[k]["implants_total"] += _implants_count(r.implants_used_json)

    for m in movs:
        if not m.created_at:
            continue
        k = m.created_at.strftime("%Y-%m")
        if k not in monthly_map:
            continue
        # write_off всегда +N (списано — потеря); inventory_adjust отрицательный
        # qty — тоже потеря, положительный — «нашли», вычитаем.
        if m.kind == "write_off":
            monthly_map[k]["losses_qty"] += abs(m.quantity)
        else:
            if m.quantity < 0:
                monthly_map[k]["losses_qty"] += -m.quantity
            else:
                monthly_map[k]["losses_qty"] -= m.quantity

    return {"series": [monthly_map[k] for k in sorted(monthly_map)]}


@router.get("/by-clinic")
async def by_clinic(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    scope: OrgScope = Depends(require_org_scope),
):
    date_from = _parse_iso_date(date_from)
    date_to = _parse_iso_date(date_to)

    async with AsyncSessionLocal() as s:
        orgs_stmt = select(Organization).where(Organization.kind == "clinic",
                                                 Organization.active == 1)
        if scope.organization_id is not None:
            orgs_stmt = orgs_stmt.where(Organization.id == scope.organization_id)
        orgs = list((await s.execute(orgs_stmt)).scalars().all())
        if not orgs:
            return {"items": []}

        org_ids = [o.id for o in orgs]
        q_reports = select(OperationReport).where(
            OperationReport.organization_id.in_(org_ids),
            OperationReport.status == "submitted",
        )
        if date_from:
            q_reports = q_reports.where(OperationReport.operation_date >= date_from)
        if date_to:
            q_reports = q_reports.where(OperationReport.operation_date <= date_to)
        reports = list((await s.execute(q_reports)).scalars().all())

        q_mov = select(ClinicStockMovement).where(
            ClinicStockMovement.organization_id.in_(org_ids),
            ClinicStockMovement.kind.in_(("write_off", "inventory_adjust")),
        )
        if date_from:
            q_mov = q_mov.where(
                ClinicStockMovement.created_at
                >= datetime.fromisoformat(date_from)
            )
        if date_to:
            dt = datetime.fromisoformat(date_to)
            q_mov = q_mov.where(
                ClinicStockMovement.created_at
                < dt.replace(hour=23, minute=59, second=59)
            )
        movs = list((await s.execute(q_mov)).scalars().all())

    # Последний submitted отчёт на клинику — для health-индикации
    async with AsyncSessionLocal() as s:
        last_stmt = (
            select(OperationReport.organization_id,
                    func.max(OperationReport.submitted_at))
            .where(OperationReport.status == "submitted")
            .group_by(OperationReport.organization_id)
        )
        last_rows = (await s.execute(last_stmt)).all()
    last_by_org = {oid: ts for oid, ts in last_rows}

    now = datetime.utcnow()
    agg: dict[int, dict] = {
        o.id: {"organization_id": o.id, "name": o.name,
                "reports": 0, "implants_total": 0, "losses_qty": 0,
                "last_report_at": None, "health": "no_data"}
        for o in orgs
    }
    for r in reports:
        a = agg.get(r.organization_id)
        if a is None:
            continue
        a["reports"] += 1
        a["implants_total"] += _implants_count(r.implants_used_json)
    for m in movs:
        a = agg.get(m.organization_id)
        if a is None:
            continue
        if m.kind == "write_off":
            a["losses_qty"] += abs(m.quantity)
        else:
            if m.quantity < 0:
                a["losses_qty"] += -m.quantity
            else:
                a["losses_qty"] -= m.quantity

    # Выставляем last_report_at и health_status
    #   ok      — есть отчёт за последние 14 дней
    #   warning — последний 15-30 дней назад
    #   silent  — >30 дней или никогда
    for oid, a in agg.items():
        last = last_by_org.get(oid)
        if last:
            a["last_report_at"] = last.isoformat()
            # last может быть offset-naive если sqlite хранит без TZ
            delta_days = (now - last.replace(tzinfo=None)).days
            if delta_days <= 14:
                a["health"] = "ok"
            elif delta_days <= 30:
                a["health"] = "warning"
            else:
                a["health"] = "silent"
        else:
            a["health"] = "silent"

    items = sorted(agg.values(), key=lambda x: -x["reports"])
    return {"items": items}


@router.get("/my-activity")
async def my_activity(scope: OrgScope = Depends(require_org_scope)):
    """KPI текущего scope за 7 и 30 дней + последний отчёт.

    Клиника видит себя; ZMed без фильтра — суммарно по всем своим клиникам
    (клиники kind='clinic', active=1).
    """
    from datetime import timedelta
    today = date.today()
    seven = (today - timedelta(days=7)).isoformat()
    thirty = (today - timedelta(days=30)).isoformat()

    async with AsyncSessionLocal() as s:
        stmt = select(OperationReport).where(
            OperationReport.status == "submitted",
        )
        if scope.organization_id is not None:
            stmt = stmt.where(OperationReport.organization_id == scope.organization_id)
        reports = list((await s.execute(stmt)).scalars().all())

    reports_7d = sum(1 for r in reports if r.operation_date >= seven)
    reports_30d = sum(1 for r in reports if r.operation_date >= thirty)
    implants_30d = sum(
        _implants_count(r.implants_used_json)
        for r in reports if r.operation_date >= thirty
    )

    last_report_date: Optional[str] = None
    if reports:
        last_report_date = max(r.operation_date for r in reports)

    return {
        "reports_7d": reports_7d,
        "reports_30d": reports_30d,
        "implants_30d": implants_30d,
        "last_report_date": last_report_date,
    }


@router.get("/top-operation-types")
async def top_operation_types(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    scope: OrgScope = Depends(require_org_scope),
):
    date_from = _parse_iso_date(date_from)
    date_to = _parse_iso_date(date_to)
    async with AsyncSessionLocal() as s:
        stmt = (select(OperationReport.operation_type, func.count())
                 .where(OperationReport.status == "submitted")
                 .group_by(OperationReport.operation_type)
                 .order_by(func.count().desc())
                 .limit(limit))
        if scope.organization_id is not None:
            stmt = stmt.where(OperationReport.organization_id == scope.organization_id)
        if date_from:
            stmt = stmt.where(OperationReport.operation_date >= date_from)
        if date_to:
            stmt = stmt.where(OperationReport.operation_date <= date_to)
        rows = (await s.execute(stmt)).all()
    return {"items": [{"operation_type": t, "count": c} for t, c in rows]}


async def _grouped_report_stats(scope: OrgScope, group_field,
                                  date_from: Optional[str],
                                  date_to: Optional[str], limit: int) -> list[dict]:
    """Общая логика группировки отчётов по произвольному полю (врач / отделение).

    Для каждой группы считаем:
      count     — число submitted-отчётов;
      implants  — сумма qty имплантов (из JSON — агрегируем в Python).
    """
    async with AsyncSessionLocal() as s:
        stmt = (select(group_field, OperationReport.implants_used_json)
                 .where(OperationReport.status == "submitted"))
        if scope.organization_id is not None:
            stmt = stmt.where(OperationReport.organization_id == scope.organization_id)
        if date_from:
            stmt = stmt.where(OperationReport.operation_date >= date_from)
        if date_to:
            stmt = stmt.where(OperationReport.operation_date <= date_to)
        rows = (await s.execute(stmt)).all()

    agg: dict[str, dict] = {}
    for key, implants_json in rows:
        if not key:
            continue  # пропускаем пустые группы (department может быть None)
        a = agg.setdefault(key, {"name": key, "count": 0, "implants": 0})
        a["count"] += 1
        a["implants"] += _implants_count(implants_json)
    items = sorted(agg.values(), key=lambda x: -x["count"])[:limit]
    return items


@router.get("/by-doctor")
async def by_doctor(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    scope: OrgScope = Depends(require_org_scope),
):
    items = await _grouped_report_stats(
        scope, OperationReport.doctor_name,
        _parse_iso_date(date_from), _parse_iso_date(date_to), limit,
    )
    return {"items": items}


@router.get("/by-department")
async def by_department(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    scope: OrgScope = Depends(require_org_scope),
):
    items = await _grouped_report_stats(
        scope, OperationReport.department,
        _parse_iso_date(date_from), _parse_iso_date(date_to), limit,
    )
    return {"items": items}
