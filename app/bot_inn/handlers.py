from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from app.db.models import InnDiler, InnLpu, InnPending
from app.db.session import AsyncSessionLocal

from . import keyboards as kb
from . import text

r = Router()

type_of_org: dict[int, str] = {}


async def check_inn_in_db(inn: str, table_class) -> str:
    """Возвращает: approved | denied | denied_date:<date> | pending:<date> | not_found."""
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            select(table_class.allowed).where(table_class.inn == inn)
        )).first()
        if row:
            return "approved" if row[0] else "denied"

        row = (await s.execute(
            select(InnPending.date, InnPending.approved, InnPending.denied)
            .where(InnPending.inn == inn)
        )).first()
        if row:
            date, _approved, denied = row
            if denied:
                return f"denied_date:{date}"
            return f"pending:{date}"

        return "not_found"


@r.message(Command("start"))
async def start_handler(msg: Message):
    type_of_org.pop(msg.from_user.id, None)
    await msg.answer(text.greet.format(name=msg.from_user.full_name), reply_markup=kb.menu)


@r.message(F.text & ~F.text.startswith("/"))
async def message_handler(msg: Message):
    user_id = msg.from_user.id
    inn = msg.text.strip()

    if user_id not in type_of_org:
        await msg.answer(text.missing_type, reply_markup=kb.menu)
        return

    table_class = InnDiler if type_of_org[user_id] == "diler" else InnLpu
    result = await check_inn_in_db(inn, table_class)

    if result == "approved":
        await msg.answer(text.text_yes, reply_markup=kb.menu)
    elif result == "denied":
        await msg.answer("❌ Отгрузка запрещена", reply_markup=kb.menu)
    elif result.startswith("denied_date:"):
        date = result.split(":", 1)[1]
        await msg.answer(f"❌ Отгрузка запрещена, дата запрета: {date}", reply_markup=kb.menu)
    elif result.startswith("pending:"):
        date = result.split(":", 1)[1]
        await msg.answer(f"⌛ На рассмотрении, подано: {date}", reply_markup=kb.menu)
    else:
        await msg.answer(text.text_no, reply_markup=kb.menu)

    type_of_org.pop(user_id, None)


@r.message(F.text == "Меню")
async def menu_handler(msg: Message):
    await msg.answer(text.menu, reply_markup=kb.menu)


@r.callback_query(F.data == "diler")
async def select_diler(callback: CallbackQuery):
    type_of_org[callback.from_user.id] = "diler"
    await callback.message.answer(text.gen_text, reply_markup=kb.menu)


@r.callback_query(F.data == "lpu")
async def select_lpu(callback: CallbackQuery):
    type_of_org[callback.from_user.id] = "lpu"
    await callback.message.answer(text.gen_text, reply_markup=kb.menu)
