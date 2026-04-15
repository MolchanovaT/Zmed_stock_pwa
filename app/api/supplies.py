"""
app/api/supplies.py

REST-эндпоинты для расходников и инструментов (таблица «stock», модуль «supplies»).
Аналогичен app/api/stock.py, но без nom_type и без корзины.
PDF включает ссылки на фото из photo_url.

Эндпоинты:
  GET /api/supplies/groups
  GET /api/supplies/regions
  GET /api/supplies/warehouses
  GET /api/supplies/categories
  GET /api/supplies/manufacturers
  GET /api/supplies/brands
  GET /api/supplies/search
  GET /api/supplies/export-pdf
"""

import asyncio
import io
import os
from collections import defaultdict
from math import ceil
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from sqlalchemy import select, func

from app.api.activity import log_activity
from app.api.auth import get_current_user
from app.db.models import AdminUser, Supplies
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/supplies", tags=["supplies"])

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
try:
    pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
except Exception:
    pass


# ── Вспомогательные функции ────────────────────────────────────────────────────

async def _uniq(col: str, session, **filters) -> list[str]:
    """Уникальные ненулевые значения колонки с учётом фильтров."""
    stmt = select(getattr(Supplies, col)).distinct()
    for k, v in filters.items():
        if v:
            stmt = stmt.filter(getattr(Supplies, k) == v)
    res = await session.scalars(stmt)
    values = [x for x in res.all() if x is not None]
    values = [v for v in values if str(v).strip().lower() != "итого"]
    return sorted(values)


def _v(val: Optional[str]) -> Optional[str]:
    """None если значение пустое или 'все'."""
    return val if val and val.lower() != "все" else None


def _apply_filters(stmt, group, region, warehouse, category, manufacturer, brand, search):
    filter_values = {
        "group_name": _v(group),
        "region": _v(region),
        "warehouse": _v(warehouse),
        "category": _v(category),
        "manufacturer": _v(manufacturer),
        "brand": _v(brand),
    }
    for col_name, val in filter_values.items():
        if val:
            stmt = stmt.filter(getattr(Supplies, col_name) == val)

    if search:
        like = f"%{search}%"
        stmt = stmt.filter(
            Supplies.nomenclature.ilike(like) |
            Supplies.characteristic.ilike(like)
        )
    return stmt


# ── Эндпоинты фильтров ─────────────────────────────────────────────────────────

@router.get("/groups")
async def get_groups(_: AdminUser = Depends(get_current_user)):
    async with AsyncSessionLocal() as s:
        values = await _uniq("group_name", s)
    return {"items": values}


@router.get("/regions")
async def get_regions(
    group: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await _uniq("region", s, group_name=_v(group))
    return {"items": values}


@router.get("/warehouses")
async def get_warehouses(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await _uniq("warehouse", s, group_name=_v(group), region=_v(region))
    return {"items": values}


@router.get("/categories")
async def get_categories(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await _uniq(
            "category", s,
            group_name=_v(group), region=_v(region), warehouse=_v(warehouse),
        )
    return {"items": values}


@router.get("/manufacturers")
async def get_manufacturers(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await _uniq(
            "manufacturer", s,
            group_name=_v(group), region=_v(region),
            warehouse=_v(warehouse), category=_v(category),
        )
    return {"items": values}


@router.get("/brands")
async def get_brands(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await _uniq(
            "brand", s,
            group_name=_v(group), region=_v(region), warehouse=_v(warehouse),
            category=_v(category), manufacturer=_v(manufacturer),
        )
    return {"items": values}


# ── Поиск ─────────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_supplies(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        stmt = (
            select(
                Supplies.nomenclature,
                Supplies.characteristic,
                Supplies.photo_url,
                func.sum(Supplies.balance).label("bal"),
                func.max(Supplies.updated_at).label("ts"),
            )
            .where(Supplies.nomenclature.is_not(None))
            .group_by(Supplies.nomenclature, Supplies.characteristic, Supplies.photo_url)
        )
        stmt = _apply_filters(stmt, group, region, warehouse, category, manufacturer, brand, search)
        all_rows = (await s.execute(stmt)).all()

    total = len(all_rows)
    total_pages = max(1, ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    chunk = all_rows[start: start + per_page]

    if all_rows:
        max_ts = max((row.ts for row in all_rows if row.ts), default=None)
        updated_at = max_ts.strftime("%d.%m.%Y %H:%M") if max_ts else "–"
    else:
        updated_at = "–"

    items = [
        {
            "nomenclature": row.nomenclature or "",
            "characteristic": row.characteristic or "",
            "photo_url": row.photo_url or "",
            "balance": float(row.bal or 0),
        }
        for row in chunk
    ]

    asyncio.create_task(log_activity(
        current_user.id, current_user.username, "search",
        {"module": "supplies", "search": search, "group": group, "region": region,
         "warehouse": warehouse, "category": category, "manufacturer": manufacturer,
         "brand": brand, "results": total},
    ))
    return {
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "updated_at": updated_at,
    }


# ── PDF-экспорт ────────────────────────────────────────────────────────────────

@router.get("/export-pdf")
async def export_pdf(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    detail: bool = Query(True),
    current_user: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        if detail:
            stmt = (
                select(
                    Supplies.region, Supplies.warehouse,
                    Supplies.nomenclature, Supplies.characteristic, Supplies.photo_url,
                    func.sum(Supplies.balance).label("bal"),
                )
                .group_by(
                    Supplies.region, Supplies.warehouse,
                    Supplies.nomenclature, Supplies.characteristic, Supplies.photo_url,
                )
            )
        else:
            stmt = (
                select(
                    Supplies.region, Supplies.warehouse,
                    Supplies.nomenclature,
                    func.sum(Supplies.balance).label("bal"),
                )
                .group_by(Supplies.region, Supplies.warehouse, Supplies.nomenclature)
            )
        stmt = _apply_filters(stmt, group, region, warehouse, category, manufacturer, brand, search)
        rows = (await s.execute(stmt)).all()

        ts_stmt = select(func.max(Supplies.updated_at))
        ts_stmt = _apply_filters(ts_stmt, group, region, warehouse, category, manufacturer, brand, search)
        max_ts = await s.scalar(ts_stmt)

    ts_str = max_ts.strftime("%d.%m.%Y %H:%M") if max_ts else "–"

    labels = {
        "Склад": group, "Регион": region, "Склад внутри региона": warehouse,
        "Категория": category, "Производитель": manufacturer, "Марка": brand,
    }
    breadcrumbs = "<br/>".join(
        f"{label}: {val}" for label, val in labels.items() if val and val != "все"
    ) or "Все позиции"

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(name="N", parent=styles["Normal"], fontName="DejaVuSans", fontSize=9)
    bold = ParagraphStyle(name="B", parent=styles["Normal"], fontName="DejaVuSans-Bold", fontSize=11, leading=14)

    grouped = defaultdict(list)
    for row in rows:
        key = f"{row.region or '—'} / {row.warehouse or '—'}"
        if detail:
            grouped[key].append((row.nomenclature or "—", row.characteristic or "—", row.photo_url or "", row.bal))
        else:
            grouped[key].append((row.nomenclature or "—", row.bal))

    elems = []
    elems.append(Paragraph(breadcrumbs, bold))
    elems.append(Paragraph(f"Актуально на: {ts_str}", bold))
    elems.append(Spacer(1, 8))

    for idx, (grp_title, grp_items) in enumerate(grouped.items()):
        if idx:
            elems.append(Spacer(1, 10))
        elems.append(Paragraph(grp_title, bold))

        if detail:
            table_data = (
                [[Paragraph("Номенклатура", normal), Paragraph("Характеристика", normal),
                  Paragraph("Фото", normal), Paragraph("Остаток", normal)]] +
                [[
                    Paragraph(nom, normal),
                    Paragraph(char, normal),
                    Paragraph(f'<a href="{ph}" color="blue"><u>Ссылка</u></a>' if ph else "", normal),
                    f"{bal:,.0f}",
                ] for nom, char, ph, bal in grp_items]
            )
            t = Table(table_data, colWidths=[200, 130, 80, 60])
        else:
            table_data = (
                [[Paragraph("Номенклатура", normal), Paragraph("Остаток", normal)]] +
                [[Paragraph(nom, normal), f"{bal:,.0f}"] for nom, bal in grp_items]
            )
            t = Table(table_data, colWidths=[430, 80])

        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ]))
        elems.append(t)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    doc.build(elems)
    buf.seek(0)

    asyncio.create_task(log_activity(
        current_user.id, current_user.username, "pdf_export",
        {"module": "supplies", "detail": detail, "search": search, "group": group,
         "region": region, "warehouse": warehouse, "category": category,
         "manufacturer": manufacturer, "brand": brand},
    ))
    filename = "supplies_report_detail.pdf" if detail else "supplies_report.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
