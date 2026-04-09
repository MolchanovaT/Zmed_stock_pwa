from __future__ import annotations

import pyzipper
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

ALLOWED_INNER = {".csv", ".txt", ".xls", ".xlsx"}

DT_RE = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})[_-](\d{2})[-_](\d{2})")


def extract_zip(zip_path: Path, password: str) -> tuple[Path, datetime]:
    """
    Распаковывает первый допустимый файл из зашифрованного ZIP.

    :return: (путь к распакованному файлу, дата/время актуальности)
    :raises: ValueError если ничего подходящего нет или пароль неверный
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="stock_"))

    with pyzipper.AESZipFile(zip_path) as zf:
        zf.pwd = password.encode()

        for name in zf.namelist():
            p = Path(name)
            if p.suffix.lower() in ALLOWED_INNER and not name.endswith("/"):
                # — распаковка
                target = temp_dir / p.name
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                # — пытаемся вынуть дату из имени
                dt_match = DT_RE.search(p.stem)
                if dt_match:
                    y, m, d, H, M = map(int, dt_match.groups())
                    file_dt = datetime(y, m, d, H, M)
                else:
                    file_dt = datetime.fromtimestamp(target.stat().st_mtime)

                return target, file_dt

    raise ValueError("В ZIP-архиве нет подходящих файлов")
