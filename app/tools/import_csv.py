"""
Универсальный импорт остатков (CSV / TXT / XLS / XLSX) → таблица «stock».
Добавлена колонка updated_at – дате/время актуальности исходного файла.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from app.config import DB_DSN
from app.db.base import Base

# ──────────────────────────────────────────────────────────────
ENG_COLUMNS = {
    "Группа складов": "group_name",
    "Бизнес-регион": "region",
    "Склад": "warehouse",
    "Группа аналитического учета": "category",
    "_Производитель": "manufacturer",
    "Марка (бренд)": "brand",
    "Вид номенклатуры": "nom_type",
    "_Артикул": "article",
    "Номенклатура": "nomenclature",
    "Характеристика": "characteristic",
    "Конечный остаток": "balance",
}
NEEDED = list(ENG_COLUMNS.values())
SUPPORTED = {".csv", ".txt", ".xls", ".xlsx"}


# ──────────────────────────────────────────────────────────────
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
    text_cols = ("group_name", "region", "warehouse",
                 "category", "manufacturer", "brand",
                 "nom_type", "nomenclature")
    present = [c for c in text_cols if c in df.columns]

    mask_bad = pd.concat(
        [df[c].astype(str).str.lower().isin(bad) for c in present],
        axis=1
    ).any(axis=1)
    # строка считается «пустой», если ВСЕ присутствующие text-колонки пусты/NaN
    mask_empty = df[present].isna().all(axis=1)
    return df[~(mask_bad | mask_empty)].copy()


# ──────────────────────────────────────────────────────────────
# app/tools/import_file.py
# ──────────────────────────────────────────────────────────────
def load_file(
        path: str | Path,
        src: str,
        *,
        file_dt: datetime | None = None,
) -> int:
    p = Path(path)
    if file_dt is None:
        file_dt = datetime.fromtimestamp(p.stat().st_mtime)

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
          f"Импорт «{p.name}», актуально на {file_dt:%d.%m.%Y %H:%M}")

    df = _normalize(_read_df(p))
    df["updated_at"] = file_dt
    df["source"] = src

    eng = create_engine(DB_DSN)

    # 1. удостоверимся, что база физически существует
    Base.metadata.create_all(bind=eng)

    # 2. грузим данные
    with eng.begin() as con:
        con.execute(text("DELETE FROM implant_stock WHERE source=:s"), {"s": src})
        df.to_sql("implant_stock", con=con, if_exists="append", index=False)

    print(f"✅ Загружено строк: {len(df)}")
    return len(df)
