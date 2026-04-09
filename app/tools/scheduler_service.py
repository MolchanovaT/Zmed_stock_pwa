from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from .autofetch_yadisk import fetch_disk

sched = AsyncIOScheduler()
sched.add_job(fetch_disk, "cron", hour=3, minute=30)
sched.start()
asyncio.get_event_loop().run_forever()
