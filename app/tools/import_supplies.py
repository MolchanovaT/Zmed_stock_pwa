"""
Импорт остатков расходников/инструментов (CSV / XLS / XLSX) → таблица «stock».
Используется модулем supplies.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from app.config import DB_DSN
from app.db.base import Base

# ──────────────────────────────────────────────────────────────
ENG_COLUMNS = {
    "Группа складов":    "group_name",
    "Бизнес-регион":     "region",
    "Склад":             "warehouse",
    "Товарная категория": "category",
    "_Производитель":    "manufacturer",
    "Марка (бренд)":     "brand",
    "Номенклатура":      "nomenclature",
    "Характеристика":    "characteristic",
    "Фото в облаке":     "photo_url",
    "Конечный остаток":  "balance",
}
NEEDED = list(ENG_COLUMNS.values())
SUPPORTED = {".csv", ".txt", ".xls", ".xlsx"}


def _read_df(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Формат «{ext}» не поддерживается")
    if ext in {".csv", ".txt"}:
        return pd.read_csv(path, sep=";", encoding="utf-8")
    return pd.read_excel(path, engine="openpyxl")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=ENG_COLUMNS)
    missing = set(NEEDED) - set(df.columns)
    if missing:
        raise ValueError("Нет колонок: " + ", ".join(missing))

    df = df[NEEDED].copy()
    df["balance"] = pd.to_numeric(df["balance"], errors="coerce").fillna(0).astype(int)

    bad = {"итого", "total"}
    text_cols = ["group_name", "region", "warehouse", "category",
                 "manufacturer", "brand", "nomenclature"]
    mask_bad = pd.concat(
        [df[c].astype(str).str.lower().isin(bad) for c in text_cols],
        axis=1,
    ).any(axis=1)
    mask_empty = df[text_cols].isna().all(axis=1)
    return df[~(mask_bad | mask_empty)].copy()


def load_supplies_file(
        path: str | Path,
        *,
        file_dt: datetime | None = None,
) -> int:
    """Загружает файл расходников в таблицу «stock» (полная замена)."""
    p = Path(path)
    if file_dt is None:
        file_dt = datetime.fromtimestamp(p.stat().st_mtime)

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
          f"[supplies] Импорт «{p.name}», актуально на {file_dt:%d.%m.%Y %H:%M}")

    df = _normalize(_read_df(p))
    df["updated_at"] = file_dt

    eng = create_engine(DB_DSN)
    Base.metadata.create_all(bind=eng)

    with eng.begin() as con:
        df.to_sql("stock", con=con, if_exists="replace", index=False)

    print(f"✅ [supplies] Загружено строк: {len(df)}")
    return len(df)
