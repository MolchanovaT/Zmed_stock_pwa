import aiohttp
import asyncio
import datetime
import pathlib

from app.config import YD_TOKEN, YD_PATH
from import_csv import load_file

TMP = pathlib.Path("/tmp/stock_latest.csv")


async def fetch_disk():
    headers = {"Authorization": f"OAuth {YD_TOKEN}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(
                "https://cloud-api.yandex.net/v1/disk/resources/download",
                headers=headers, params={"path": YD_PATH}) as r:
            href = (await r.json())["href"]
        async with s.get(href) as r, TMP.open("wb") as f:
            async for chunk in r.content.iter_chunked(1 << 15):
                f.write(chunk)
    load_file(TMP, replace=True)
    print("✅ Autofetch", datetime.datetime.now())


if __name__ == "__main__":
    asyncio.run(fetch_disk())
