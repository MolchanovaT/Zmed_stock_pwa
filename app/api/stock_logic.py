"""Общая логика фильтрации остатков, используемая API-эндпойнтами."""

from sqlalchemy import select

from app.db.models import Stock

FILTER_MAP = {
    "group": Stock.group_name,
    "region": Stock.region,
    "warehouse": Stock.warehouse,
    "category": Stock.category,
    "manufacturer": Stock.manufacturer,
    "brand": Stock.brand,
    "nom_type": Stock.nom_type,
}


async def uniq(col: str, session, **f):
    stmt = select(getattr(Stock, col)).distinct()
    for k, v in f.items():
        if v and v.lower() != "все":
            stmt = stmt.filter(getattr(Stock, k) == v)

    res = await session.scalars(stmt)
    values = [x for x in res.all() if x is not None]
    values = [v for v in values if str(v).strip().lower() != "итого"]
    return sorted(values)
