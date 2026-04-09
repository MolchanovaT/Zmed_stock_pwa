"""
app/api/stock.py

REST-эндпоинты для работы с остатками.
Логика фильтрации переиспользует функцию uniq() из app.bot.handlers.
PDF генерируется той же логикой, что и в handlers.download_pdf.

Эндпоинты:
  GET /api/stock/groups
  GET /api/stock/regions
  GET /api/stock/warehouses
  GET /api/stock/categories
  GET /api/stock/manufacturers
  GET /api/stock/brands
  GET /api/stock/nom-types
  GET /api/stock/search
  GET /api/stock/export-pdf
"""

import io
import os
import tempfile
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

from app.api.auth import get_current_user
from app.bot.handlers import uniq, FILTER_MAP   # переиспользуем готовую логику
from app.db.models import AdminUser, Stock
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/stock", tags=["stock"])

# Регистрируем шрифты один раз при импорте модуля
_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
try:
    pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
except Exception:
    pass  # шрифты уже зарегистрированы или файлы не найдены


# ── Вспомогательные функции ────────────────────────────────────────────────────

def _apply_filters(stmt, group, region, warehouse, category, manufacturer, brand, nom_type, search):
    """Применяет активные фильтры к SQLAlchemy-запросу."""
    filter_values = {
        "group_name": group,
        "region": region,
        "warehouse": warehouse,
        "category": category,
        "manufacturer": manufacturer,
        "brand": brand,
        "nom_type": nom_type,
    }
    for col_name, val in filter_values.items():
        if val and val.lower() != "все":
            stmt = stmt.filter(getattr(Stock, col_name) == val)

    if search:
        like = f"%{search}%"
        stmt = stmt.filter(
            Stock.nomenclature.ilike(like) |
            Stock.article.ilike(like) |
            Stock.characteristic.ilike(like)
        )
    return stmt


# ── Эндпоинты фильтров ─────────────────────────────────────────────────────────

@router.get("/groups")
async def get_groups(_: AdminUser = Depends(get_current_user)):
    """Список групп складов (верхний уровень фильтрации)."""
    async with AsyncSessionLocal() as s:
        values = await uniq("group_name", s)
    return {"items": values}


@router.get("/regions")
async def get_regions(
    group: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    """Список регионов (фильтруется по group)."""
    async with AsyncSessionLocal() as s:
        values = await uniq("region", s, group_name=group if group and group != "все" else None)
    return {"items": values}


@router.get("/warehouses")
async def get_warehouses(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await uniq(
            "warehouse", s,
            group_name=group if group and group != "все" else None,
            region=region if region and region != "все" else None,
        )
    return {"items": values}


@router.get("/categories")
async def get_categories(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await uniq(
            "category", s,
            group_name=group if group and group != "все" else None,
            region=region if region and region != "все" else None,
            warehouse=warehouse if warehouse and warehouse != "все" else None,
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
        values = await uniq(
            "manufacturer", s,
            group_name=group if group and group != "все" else None,
            region=region if region and region != "все" else None,
            warehouse=warehouse if warehouse and warehouse != "все" else None,
            category=category if category and category != "все" else None,
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
        values = await uniq(
            "brand", s,
            group_name=group if group and group != "все" else None,
            region=region if region and region != "все" else None,
            warehouse=warehouse if warehouse and warehouse != "все" else None,
            category=category if category and category != "все" else None,
            manufacturer=manufacturer if manufacturer and manufacturer != "все" else None,
        )
    return {"items": values}


@router.get("/nom-types")
async def get_nom_types(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    async with AsyncSessionLocal() as s:
        values = await uniq(
            "nom_type", s,
            group_name=group if group and group != "все" else None,
            region=region if region and region != "все" else None,
            warehouse=warehouse if warehouse and warehouse != "все" else None,
            category=category if category and category != "все" else None,
            manufacturer=manufacturer if manufacturer and manufacturer != "все" else None,
            brand=brand if brand and brand != "все" else None,
        )
    return {"items": values}


# ── Поиск ─────────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_stock(
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    manufacturer: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    nom_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _: AdminUser = Depends(get_current_user),
):
    """
    Поиск остатков с пагинацией.
    Возвращает: {items, total, page, total_pages, updated_at}
    """
    async with AsyncSessionLocal() as s:
        stmt = (
            select(
                Stock.article,
                Stock.nomenclature,
                Stock.characteristic,
                func.sum(Stock.balance).label("bal"),
                func.max(Stock.updated_at).label("ts"),
            )
            .where(Stock.nomenclature.is_not(None))
            .group_by(Stock.article, Stock.nomenclature, Stock.characteristic)
        )
        stmt = _apply_filters(stmt, group, region, warehouse, category, manufacturer, brand, nom_type, search)

        all_rows = (await s.execute(stmt)).all()

    total = len(all_rows)
    total_pages = max(1, ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    chunk = all_rows[start: start + per_page]

    # Дата актуальности — максимальный updated_at по всей выборке
    if all_rows:
        max_ts = max(row.ts for row in all_rows if row.ts)
        updated_at = max_ts.strftime("%d.%m.%Y %H:%M") if max_ts else "–"
    else:
        updated_at = "–"

    items = [
        {
            "article": row.article or "",
            "nomenclature": row.nomenclature or "",
            "characteristic": row.characteristic or "",
            "balance": float(row.bal or 0),
        }
        for row in chunk
    ]

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
    nom_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    _: AdminUser = Depends(get_current_user),
):
    """
    Генерирует PDF с результатами поиска и возвращает файл для скачивания.
    Логика идентична handlers.download_pdf.
    """
    async with AsyncSessionLocal() as s:
        stmt = (
            select(
                Stock.region,
                Stock.warehouse,
                Stock.article,
                Stock.nomenclature,
                Stock.characteristic,
                func.sum(Stock.balance).label("bal"),
            )
            .group_by(Stock.region, Stock.warehouse, Stock.article, Stock.nomenclature, Stock.characteristic)
        )
        stmt = _apply_filters(stmt, group, region, warehouse, category, manufacturer, brand, nom_type, search)
        rows = (await s.execute(stmt)).all()

        ts_stmt = select(func.max(Stock.updated_at))
        ts_stmt = _apply_filters(ts_stmt, group, region, warehouse, category, manufacturer, brand, nom_type, search)
        max_ts = await s.scalar(ts_stmt)

    ts_str = max_ts.strftime("%d.%m.%Y %H:%M") if max_ts else "–"

    # Формируем хлебные крошки из активных фильтров
    labels = {
        "Склад": group, "Регион": region, "Склад внутри региона": warehouse,
        "Категория": category, "Производитель": manufacturer,
        "Марка": brand, "Вид номенклатуры": nom_type,
    }
    breadcrumbs = "<br/>".join(
        f"{label}: {val}" for label, val in labels.items() if val and val != "все"
    ) or "Все позиции"

    # ── Строим PDF ─────────────────────────────────────────────────
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(name="N", parent=styles["Normal"], fontName="DejaVuSans", fontSize=9)
    bold = ParagraphStyle(name="B", parent=styles["Normal"], fontName="DejaVuSans-Bold", fontSize=11, leading=14)

    grouped = defaultdict(list)
    for row in rows:
        key = f"{row.region or '—'} / {row.warehouse or '—'}"
        title = f"{row.article or '—'}, {row.nomenclature or '—'}, {row.characteristic or '—'}"
        grouped[key].append((title, row.bal))

    elems = []
    elems.append(Paragraph(breadcrumbs, bold))
    elems.append(Paragraph(f"Актуально на: {ts_str}", bold))
    elems.append(Spacer(1, 8))

    for idx, (grp_title, grp_items) in enumerate(grouped.items()):
        if idx:
            elems.append(Spacer(1, 10))
        elems.append(Paragraph(grp_title, bold))
        table_data = (
            [[Paragraph("Артикул, номенклатура, характеристика", normal), Paragraph("Ост", normal)]] +
            [[Paragraph(t, normal), f"{b:,.0f}"] for t, b in grp_items]
        )
        t = Table(table_data, colWidths=[370, 80])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ]))
        elems.append(t)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    doc.build(elems)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=report.pdf"},
    )
