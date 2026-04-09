# app/tools/scheduler.py
from __future__ import annotations

import asyncio
import os
import re
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from app.tools.import_csv import load_file
from app.tools.zip_helper import extract_zip

# ──────────── конфигурация ────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

YD_MAIN_FOLDER = os.getenv("YD_MAIN_FOLDER")  # публичные URL-ы
YD_REMOTE_FOLDER = os.getenv("YD_REMOTE_FOLDER")

CRON_MAIN = int(os.getenv("CRON_MAIN_MINUTES", 5))  # период опроса
CRON_REMOTE = int(os.getenv("CRON_REMOTE_MINUTES", 30))

ZIP_PASSWORD = os.getenv("ZIP_PASSWORD", "")

# OAuth-токен нужен только для удаления файлов; для чтения public-folder не нужен
YD_TOKEN = os.getenv("YD_TOKEN", "")
YD_MAIN_PREFIX = os.getenv("YD_MAIN_PREFIX", "").strip("/")
YD_REMOTE_PREFIX = os.getenv("YD_REMOTE_PREFIX", "").strip("/")

ALLOWED_EXT = {".csv", ".txt", ".xls", ".xlsx", ".zip"}

MSK = ZoneInfo("Europe/Moscow")
_DATE_RX = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})[_-](\d{2})[-_](\d{2})")


# ──────────── утилиты ────────────────────────────────────────
def ts_from_filename(name: str) -> datetime | None:
    """Достаём YYYY-MM-DD_HH-MM из имени файла, возвращаем aware-datetime (MSK)."""
    m = _DATE_RX.search(name)
    return datetime(*map(int, m.groups()), tzinfo=MSK) if m else None


def _print(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


async def _api_get(session: aiohttp.ClientSession, url: str, **params):
    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _public_list(session: aiohttp.ClientSession, pub_url: str):
    return (await _api_get(
        session,
        "https://cloud-api.yandex.net/v1/disk/public/resources",
        public_key=pub_url,
        limit=1000,
        fields="_embedded.items.name,_embedded.items.path,_embedded.items.file",
    ))["_embedded"]["items"]


async def _public_download(session: aiohttp.ClientSession, pub_url: str, path: str, dst: Path):
    href = (await _api_get(
        session,
        "https://cloud-api.yandex.net/v1/disk/public/resources/download",
        public_key=pub_url,
        path=path,
    ))["href"]
    async with session.get(href) as r:
        r.raise_for_status()
        dst.write_bytes(await r.read())


async def _yd_delete(raw_path: str, src: str) -> None:
    """Удаляем файл на Я.Диске (нужен OAuth-токен)."""
    if not YD_TOKEN:
        return
    if raw_path.startswith("disk:"):
        full = raw_path
    else:
        root = YD_MAIN_PREFIX if src == "main" else YD_REMOTE_PREFIX
        full = f"disk:/{root}/{raw_path.lstrip('/')}"
    async with aiohttp.ClientSession(
            headers={"Authorization": f"OAuth {YD_TOKEN}"}  # bearer-токен
    ) as s:
        await s.delete(
            "https://cloud-api.yandex.net/v1/disk/resources",
            params={"path": full, "permanently": "true"},
        )


# ──────────── основная задача ────────────────────────────────
async def process_folder(pub_url: str, src: str) -> None:
    try:
        _print(f"🔄 {src}: проверяем папку…")

        async with aiohttp.ClientSession() as s:
            items = await _public_list(s, pub_url)

        # оставляем только файлы с корректной датой в названии
        files = [it for it in items
                 if it.get("file") and Path(it["name"]).suffix.lower() in ALLOWED_EXT
                 and ts_from_filename(it["name"])]
        if not files:
            _print(f"⚠️  {src}: нет файлов подходящего формата + даты")
            return

        # берём самый свежий по дате в НАЗВАНИИ
        latest = max(files, key=lambda it: ts_from_filename(it["name"]))
        latest_dt = ts_from_filename(latest["name"])
        assert latest_dt  # уже проверяли выше

        yd_path = latest["path"]
        local_path = BASE_DIR / latest["name"]

        _print(f"{src}: ⬇️  скачиваем {latest['name']}")
        async with aiohttp.ClientSession() as s:
            await _public_download(s, pub_url, yd_path, local_path)

        # ── определяем файл-для-импорта + дату из ИМЕНИ ZIP/CSV ──
        if local_path.suffix.lower() == ".zip":
            if not ZIP_PASSWORD:
                _print("❌ ZIP_PASSWORD не задан – пропускаем файл")
                return
            working_file, _ = extract_zip(local_path, ZIP_PASSWORD)
            file_dt = ts_from_filename(local_path.name)  # из имени ZIP
        else:
            working_file = local_path
            file_dt = ts_from_filename(local_path.name)  # из имени CSV/XLS

        if not file_dt:
            _print(f"⚠️  {src}: не смогли извлечь дату из имени {working_file.name}")
            return

        _print(f"{src}: ✅ импортируем, актуально на {file_dt:%d.%m.%Y %H:%M}")
        load_file(working_file, src=src, file_dt=file_dt)

        # ── чистим старые файлы ──────────────────────────────────
        for it in files:
            # if it["path"] == yd_path:
            #     continue
            # dt = ts_from_filename(it["name"])
            # if dt and dt < latest_dt:
            #     await _yd_delete(it["path"], src)
            #     _print(f"{src}: 🗑 удалён {it['name']} ({dt:%d.%m.%Y %H:%M})")

            dt = ts_from_filename(it["name"])
            # удаляем всё, что "не свежее" текущего latest_dt
            if dt and dt <= latest_dt:
                await _yd_delete(it["path"], src)
            _print(f"{src}: 🗑 удалён {it['name']} ({dt:%d.%m.%Y %H:%M})")

    except Exception as exc:
        _print(f"❌ {src}: ошибка – {exc}\n{traceback.format_exc()}")
    finally:
        # локальные временные файлы удаляем в любом случае
        for p in [locals().get("local_path"), locals().get("working_file")]:
            if isinstance(p, Path):
                p.unlink(missing_ok=True)


# ──────────── запуск планировщика ────────────────────────────
def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # первая попытка сразу
    loop.create_task(process_folder(YD_MAIN_FOLDER, "main"))
    loop.create_task(process_folder(YD_REMOTE_FOLDER, "remote"))

    sched = AsyncIOScheduler(event_loop=loop)
    sched.add_job(process_folder, "interval",
                  args=[YD_MAIN_FOLDER, "main"],
                  minutes=CRON_MAIN)
    sched.add_job(process_folder, "interval",
                  args=[YD_REMOTE_FOLDER, "remote"],
                  minutes=CRON_REMOTE)
    sched.start()

    _print(f"🕒 Планировщик запущен — main:{CRON_MAIN} мин, remote:{CRON_REMOTE} мин.")
    loop.run_forever()


if __name__ == "__main__":
    main()
