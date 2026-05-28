import logging
import os
import tempfile
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.input_file import BufferedInputFile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from sqlalchemy import select, func

from app.db.models import Supplies as Stock
from app.db.session import AsyncSessionLocal
from .states import Form

# Регистрируем шрифт
pdfmetrics.registerFont(TTFont("DejaVuSans", "app/fonts/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "app/fonts/DejaVuSans-Bold.ttf"))

r = Router()

ROWS_PER_PAGE = 10

MD_SPECIAL = r"_*[]()~`>#+-=|{}.!"

FILTER_MAP = {
    "group": Stock.group_name,
    "region": Stock.region,
    "warehouse": Stock.warehouse,
    "category": Stock.category,
    "manufacturer": Stock.manufacturer,
    "brand": Stock.brand,
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def esc(text: str) -> str:
    """Экранировать спецсимволы для Markdown V2."""
    return ''.join(f"\\{c}" if c in MD_SPECIAL else c for c in text)


def get_breadcrumb_text(data: dict, current_step: str) -> str:
    labels = {
        "group": "Склад",
        "region": "Регион",
        "warehouse": "Склад внутри региона",
        "category": "Вид",
        "manufacturer": "Производитель",
        "brand": "Марка"
    }
    order = ["group", "region", "warehouse", "category", "manufacturer", "brand"]
    text = ""
    for field in order:
        val = data.get(field)
        if val is not None:
            text += f"{labels[field]}: {val}\n"
        if field == current_step:
            break
    return text.strip()


async def store_list(state: FSMContext, key: str, items: list[str]):
    full = ["все"] + sorted(set(items))
    await state.update_data(**{f"{key}_list": full})


async def build_group_keyboard(state: FSMContext, page: int = 1):
    """
    Получаем список групп складов из БД и формируем клавиатуру
    (в state он кэшируется, чтобы не ходить в БД каждый раз).
    """
    data = await state.get_data()
    if "group_list" not in data:  # ещё не кэшировали
        async with AsyncSessionLocal() as s:
            groups = await uniq("group_name", s)  # уже без None
        await store_list(state, "group", groups)
        data = await state.get_data()  # перечитать

    groups = data["group_list"]
    return paginated_keyboard(groups, page, "group")


def get_from_list(data: dict, key: str, index: int) -> Any | None:
    values = data.get(f"{key}_search_list") or data.get(f"{key}_list", [])
    if 0 <= index < len(values):
        return values[index]
    return None


def paginated_keyboard(
        items: list[str],
        page: int = 1,
        prefix: str = "",
        back_prefix: str = None,
        per_page: int = 10
) -> InlineKeyboardMarkup:
    total_pages = max(1, ceil(len(items) / per_page))
    page = max(1, min(page, total_pages))
    start_page = (page - 1) * per_page
    end = start_page + per_page
    current_items = items[start_page:end]

    rows = []

    for idx, item in enumerate(current_items):
        real_index = start_page + idx
        if item.lower() == "все":
            continue  # ⛔️ не добавляем в основной список
        rows.append([InlineKeyboardButton(text=item, callback_data=f"{prefix}_id:{real_index}")])

    # 🔄 Добавляем кнопку "все" вручную (один раз)
    if "все" in items:
        index_all = items.index("все")
        rows.insert(0, [InlineKeyboardButton(text="все", callback_data=f"{prefix}_id:{index_all}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}_id:page:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}_id:page:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="🔍 Поиск", callback_data=f"{prefix}_search")])

    if back_prefix:
        rows.append([InlineKeyboardButton(text="↩ Назад", callback_data=f"back:{back_prefix}")])

    rows.append([InlineKeyboardButton(text="🏠 В начало", callback_data="to_start")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


@r.callback_query(F.data.endswith("_search"))
async def search_prompt_handler(c: CallbackQuery, state: FSMContext):
    prefix = c.data.split("_search")[0]
    await state.update_data(search_mode=prefix)
    await c.message.answer(f"Введите часть названия для поиска по: {prefix}")


def search_back_step(prefix: str) -> str:
    return {
        "group": "",
        "region": "group",
        "warehouse": "region",
        "category": "warehouse",
        "manufacturer": "category",
        "brand": "manufacturer"
    }.get(prefix, "")


@r.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚀 Начать поиск", callback_data="begin")]]
    )
    await msg.answer("Добро пожаловать!\nНажмите кнопку, чтобы начать поиск остатков:", reply_markup=kb)


@r.callback_query(F.data == "begin")
async def cb_begin(c: CallbackQuery, state: FSMContext):
    # то, что раньше делал /start
    kb = await build_group_keyboard(state, 1)
    await c.message.edit_text("1️⃣ Выберите группу складов:", reply_markup=kb)
    await state.set_state(Form.group)


# ─── «Новый поиск» из результатов ─────────────────────────────────────
@r.callback_query(F.data == "restart")
async def cb_restart(c: CallbackQuery, state: FSMContext):
    await cmd_start(c.message, state)


@r.callback_query(F.data == "to_start")
async def cb_to_start(c: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚀 Начать поиск", callback_data="begin")]]
    )
    await c.message.answer("Добро пожаловать!\nНажмите кнопку, чтобы начать поиск остатков:", reply_markup=kb)


def result_nav_keyboard(current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    nav = []
    if current_page > 1:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"page:{current_page - 1}"))
    if current_page < total_pages:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"page:{current_page + 1}"))

    row1 = nav or [InlineKeyboardButton(text="—", callback_data="noop")]
    row1 += [InlineKeyboardButton(text="🔍 Поиск", callback_data="search")]

    row2 = [
        InlineKeyboardButton(text="📄 PDF Кратко", callback_data="download_pdf_simple"),
        InlineKeyboardButton(text="📄 PDF Детально", callback_data="download_pdf"),
    ]

    row3 = [InlineKeyboardButton(text="🔄 Новый поиск", callback_data="restart")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2, row3])


async def uniq(col: str, session, **f):
    stmt = select(getattr(Stock, col)).distinct()
    for k, v in f.items():
        if v and v.lower() != "все":
            stmt = stmt.filter(getattr(Stock, k) == v)

    res = await session.scalars(stmt)
    # ✨ убираем None и уже потом сортируем
    values = [x for x in res.all() if x is not None]
    values = [v for v in values if str(v).strip().lower() != "итого"]
    return sorted(values)


# @r.message(CommandStart())
# async def start(msg: Message, state: FSMContext):
#     await state.clear()
#     kb = await build_group_keyboard(state, 1)
#     await msg.answer("1️⃣ Выберите группу складов:", reply_markup=kb)
#     await state.set_state(Form.group)


@r.callback_query(Form.group, F.data.startswith("group_id:"))
async def handle_group(c: CallbackQuery, state: FSMContext):
    payload = c.data.split("group_id:")[1]
    data = await state.get_data()

    # постраничная навигация
    if payload.startswith("page:"):
        page = int(payload.split(":")[1])
        kb = await build_group_keyboard(state, page)
        await c.message.edit_text("1️⃣ Выберите группу складов:", reply_markup=kb)
        return

    idx = int(payload)
    group = get_from_list(data, "group", idx)
    if group is None:
        await c.answer("Ошибка группы")
        return

    await state.update_data(group=group)

    # дальше всё как было (строим список регионов и переходим на Form.region)
    async with AsyncSessionLocal() as s:
        regions = await uniq("region", s, group_name=None if group == "все" else group)

    await store_list(state, "region", regions)
    data = await state.get_data()
    region_kb = paginated_keyboard(
        data["region_list"], 1, "region", "group"
    )

    await c.message.edit_text(
        f"Склад: {group}\n\n2️⃣ Выберите регион:",
        reply_markup=region_kb
    )
    await state.set_state(Form.region)


@r.callback_query(Form.region, F.data.startswith("region_id:"))
async def handle_region(c: CallbackQuery, state: FSMContext):
    payload = c.data.split("region_id:")[1]
    data = await state.get_data()

    if payload.startswith("page:"):
        page = int(payload.split(":")[1])
        region_list = data.get("region_list", [])
        await c.message.edit_text(
            f"{get_breadcrumb_text(data, 'group')}\n\n2️⃣ Выберите регион:",
            reply_markup=paginated_keyboard(region_list, page, "region", "group"))
        return

    idx = int(payload)
    region = get_from_list(data, "region", idx)
    if region is None:
        await c.answer("Ошибка: регион не найден")
        return

    await state.update_data(region=region)

    async with AsyncSessionLocal() as s:
        warehouses = await uniq("warehouse", s, group_name=data["group"],
                                region=None if region == "все" else region)

    await store_list(state, "warehouse", warehouses)
    data = await state.get_data()
    warehouse_list = data.get("warehouse_list", [])

    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'region')}\n\n3️⃣ Выберите склад:",
        reply_markup=paginated_keyboard(warehouse_list, 1, "warehouse", "region")
    )
    await state.set_state(Form.warehouse)


@r.callback_query(Form.warehouse, F.data.startswith("warehouse_id:"))
async def handle_warehouse(c: CallbackQuery, state: FSMContext):
    payload = c.data.split("warehouse_id:")[1]
    data = await state.get_data()

    if payload.startswith("page:"):
        page = int(payload.split(":")[1])
        warehouse_list = data.get("warehouse_list", [])
        await c.message.edit_text(
            f"{get_breadcrumb_text(data, 'region')}\n\n3️⃣ Выберите склад:",
            reply_markup=paginated_keyboard(warehouse_list, page, "warehouse", "region"))
        return

    idx = int(payload)
    warehouse = get_from_list(data, "warehouse", idx)
    if warehouse is None:
        await c.answer("Ошибка склада")
        return

    await state.update_data(warehouse=warehouse)

    async with AsyncSessionLocal() as s:
        cats = await uniq("category", s,
                          group_name=data["group"],
                          region=None if data["region"] == "все" else data["region"],
                          warehouse=None if warehouse == "все" else warehouse)

    await store_list(state, "category", cats)
    data = await state.get_data()
    category_list = data.get("category_list", [])

    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'warehouse')}\n\n4️⃣ Выберите вид:",
        reply_markup=paginated_keyboard(category_list, 1, "category", "warehouse")
    )
    await state.set_state(Form.category)


@r.callback_query(Form.category, F.data.startswith("category_id:"))
async def handle_category(c: CallbackQuery, state: FSMContext):
    payload = c.data.split("category_id:")[1]
    data = await state.get_data()

    if payload.startswith("page:"):
        page = int(payload.split(":")[1])
        category_list = data.get("category_list", [])
        await c.message.edit_text(
            f"{get_breadcrumb_text(data, 'warehouse')}\n\n4️⃣ Выберите вид:",
            reply_markup=paginated_keyboard(category_list, page, "category", "warehouse"))
        return

    idx = int(payload)
    category = get_from_list(data, "category", idx)
    if category is None:
        await c.answer("Ошибка вида")
        return

    await state.update_data(category=category)

    async with AsyncSessionLocal() as s:
        mans = await uniq("manufacturer", s,
                          group_name=data["group"],
                          region=None if data["region"] == "все" else data["region"],
                          warehouse=None if data["warehouse"] == "все" else data["warehouse"],
                          category=None if category == "все" else category)

    await store_list(state, "manufacturer", mans)
    data = await state.get_data()
    manufacturer_list = data.get("manufacturer_list", [])

    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'category')}\n\n5️⃣ Выберите производителя:",
        reply_markup=paginated_keyboard(manufacturer_list, 1, "manufacturer", "category")
    )
    await state.set_state(Form.manufacturer)


@r.callback_query(Form.manufacturer, F.data.startswith("manufacturer_id:"))
async def handle_manufacturer(c: CallbackQuery, state: FSMContext):
    payload = c.data.split("manufacturer_id:")[1]
    data = await state.get_data()

    if payload.startswith("page:"):
        page = int(payload.split(":")[1])
        manufacturer_list = data.get("manufacturer_list", [])
        await c.message.edit_text(
            f"{get_breadcrumb_text(data, 'category')}\n\n5️⃣ Выберите производителя:",
            reply_markup=paginated_keyboard(manufacturer_list, page, "manufacturer", "category"))
        return

    idx = int(payload)
    manufacturer = get_from_list(data, "manufacturer", idx)
    if manufacturer is None:
        await c.answer("Ошибка производителя")
        return

    await state.update_data(manufacturer=manufacturer)

    async with AsyncSessionLocal() as s:
        brands = await uniq("brand", s,
                            group_name=data["group"],
                            region=None if data["region"] == "все" else data["region"],
                            warehouse=None if data["warehouse"] == "все" else data["warehouse"],
                            category=None if data["category"] == "все" else data["category"],
                            manufacturer=None if manufacturer == "все" else manufacturer)

    await store_list(state, "brand", brands)
    data = await state.get_data()
    brand_list = data.get("brand_list", [])

    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'manufacturer')}\n\n6️⃣ Выберите марку (бренд):",
        reply_markup=paginated_keyboard(brand_list, 1, "brand", "manufacturer")
    )
    await state.set_state(Form.brand)


@r.callback_query(Form.brand, F.data.startswith("brand_id:"))
async def handle_brand(c: CallbackQuery, state: FSMContext):
    payload = c.data.split("brand_id:")[1]
    data = await state.get_data()

    if payload.startswith("page:"):
        page = int(payload.split(":")[1])
        brand_list = data.get("brand_list", [])
        await c.message.edit_text(
            f"{get_breadcrumb_text(data, 'manufacturer')}\n\n6️⃣ Выберите марку (бренд):",
            reply_markup=paginated_keyboard(brand_list, page, "brand", "manufacturer"))
        return

    idx = int(payload)
    brand = get_from_list(data, "brand", idx)
    if brand is None:
        await c.answer("Ошибка бренда")
        return

    await state.update_data(brand=brand, page=1, search=None)
    await state.set_state(Form.result_page)
    await show_result(c, state)


@r.callback_query(F.data.startswith("back:"))
async def go_back(c: CallbackQuery, state: FSMContext):
    step = c.data.split("back:")[1]
    data = await state.get_data()

    # Очистим возможный *_search_list
    await state.update_data({
        f"{step}_search_list": None,
        "search_mode": None
    })

    async with AsyncSessionLocal():
        match step:
            case "group":
                await cmd_start(c.message, state)

            case "region":
                regions = data.get("region_list", [])
                await c.message.edit_text(
                    f"{get_breadcrumb_text(data, 'group')}\n\n2️⃣ Выберите регион:",
                    reply_markup=paginated_keyboard(regions, 1, "region", "group"))
                await state.set_state(Form.region)

            case "warehouse":
                warehouses = data.get("warehouse_list", [])
                await c.message.edit_text(
                    f"{get_breadcrumb_text(data, 'region')}\n\n3️⃣ Выберите склад:",
                    reply_markup=paginated_keyboard(warehouses, 1, "warehouse", "region"))
                await state.set_state(Form.warehouse)

            case "category":
                cats = data.get("category_list", [])
                await c.message.edit_text(
                    f"{get_breadcrumb_text(data, 'warehouse')}\n\n4️⃣ Выберите вид:",
                    reply_markup=paginated_keyboard(cats, 1, "category", "warehouse"))
                await state.set_state(Form.category)

            case "manufacturer":
                mans = data.get("manufacturer_list", [])
                await c.message.edit_text(
                    f"{get_breadcrumb_text(data, 'category')}\n\n5️⃣ Выберите производителя:",
                    reply_markup=paginated_keyboard(mans, 1, "manufacturer", "category"))
                await state.set_state(Form.manufacturer)

            case "brand":
                brands = data.get("brand_list", [])
                await c.message.edit_text(
                    f"{get_breadcrumb_text(data, 'manufacturer')}\n\n6️⃣ Выберите марку (бренд):",
                    reply_markup=paginated_keyboard(brands, 1, "brand", "manufacturer"))
                await state.set_state(Form.brand)


@r.callback_query(Form.group, F.data.startswith("group_page:"))
async def handle_group_page(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[1])
    kb = await build_group_keyboard(state, page)
    await c.message.edit_text("1️⃣ Выберите группу складов:", reply_markup=kb)


@r.callback_query(Form.region, F.data.startswith("region_page:"))
async def handle_region_page(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[1])
    data = await state.get_data()
    regions = data.get("region_list", [])
    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'group')}\n\n2️⃣ Выберите регион:",
        reply_markup=paginated_keyboard(regions, page, "region", "group")
    )


@r.callback_query(Form.warehouse, F.data.startswith("warehouse_page:"))
async def handle_warehouse_page(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[1])
    data = await state.get_data()
    warehouses = data.get("warehouse_list", [])
    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'region')}\n\n3️⃣ Выберите склад:",
        reply_markup=paginated_keyboard(warehouses, page, "warehouse", "region")
    )


@r.callback_query(Form.category, F.data.startswith("category_page:"))
async def handle_category_page(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[1])
    data = await state.get_data()
    categories = data.get("category_list", [])
    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'warehouse')}\n\n4️⃣ Выберите вид:",
        reply_markup=paginated_keyboard(categories, page, "category", "warehouse")
    )


@r.callback_query(Form.manufacturer, F.data.startswith("manufacturer_page:"))
async def handle_manufacturer_page(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[1])
    data = await state.get_data()
    manufacturers = data.get("manufacturer_list", [])
    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'category')}\n\n5️⃣ Выберите производителя:",
        reply_markup=paginated_keyboard(manufacturers, page, "manufacturer", "category")
    )


@r.callback_query(Form.brand, F.data.startswith("brand_page:"))
async def handle_brand_page(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[1])
    data = await state.get_data()
    brands = data.get("brand_list", [])
    await c.message.edit_text(
        f"{get_breadcrumb_text(data, 'manufacturer')}\n\n6️⃣ Выберите марку (бренд):",
        reply_markup=paginated_keyboard(brands, page, "brand", "manufacturer")
    )


# ─────────────────────────────────────────────────────────────
async def show_result(c: CallbackQuery | Message, state: FSMContext):
    """
    Выводит страницу остатков + дату-актуальности (берём из Stock.updated_at,
    куда при импорте заносится дата/время создания исходного файла).
    """
    data = await state.get_data()
    page = data.get("page", 1)
    search = data.get("search")

    async with AsyncSessionLocal() as s:
        # ── сами остатки
        stmt = (
            select(Stock.nomenclature,
                   func.sum(Stock.balance).label("bal"))
            .where(Stock.nomenclature.is_not(None))
            .group_by(Stock.nomenclature)
        )

        for key, column in FILTER_MAP.items():
            val = data.get(key)
            if val and val.lower() != "все":
                stmt = stmt.filter(column == val)

        if search:
            stmt = stmt.filter(Stock.nomenclature.ilike(f"%{search}%"))

        all_rows = (await s.execute(stmt)).all()

        # ── максимальная updated_at (дата файла-источника)
        ts_stmt = select(func.max(Stock.updated_at))
        for key, column in FILTER_MAP.items():
            val = data.get(key)
            if val and val.lower() != "все":
                ts_stmt = ts_stmt.filter(column == val)

        max_ts = await s.scalar(ts_stmt)
        if max_ts:
            # если в колонке хранится timestamp WITH TIME ZONE,
            # приводим к московскому поясу; если tz-info нет — выводим как есть
            if max_ts.tzinfo is not None:
                max_ts = max_ts.astimezone(ZoneInfo("Europe/Moscow"))
            ts_str = max_ts.strftime("%d.%m.%Y %H:%M")
        else:
            ts_str = "—"

    # ── пагинация
    total = len(all_rows)
    total_pages = max(1, (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
    page = max(1, min(page, total_pages))
    start_i = (page - 1) * ROWS_PER_PAGE
    end_i = start_i + ROWS_PER_PAGE
    chunk = all_rows[start_i:end_i]

    # ── текстовая таблица
    header = f"{'Номенклатура':<50} {'Остаток':>10}"
    line = f"{'-' * 50} {'-' * 10}"
    body = [
        f"{str(n or '')[:50]:<50} {b:>10,.0f}" for n, b in chunk
    ]

    breadcrumbs = esc(get_breadcrumb_text(data, "brand"))
    ts_str_md = esc(ts_str)

    text = (
            f"{breadcrumbs}\n"
            f"*Актуально на:* {ts_str_md}\n\n"
            f"```text\n"
            f"Страница {page} из {total_pages}\n"
            f"{header}\n{line}\n" +
            "\n".join(body) +
            "\n```"
    )

    markup = result_nav_keyboard(page, total_pages)

    if isinstance(c, CallbackQuery):
        await c.message.edit_text(text,
                                  parse_mode="MarkdownV2",
                                  reply_markup=markup)
    else:
        await c.answer(text,
                       parse_mode="MarkdownV2",
                       reply_markup=markup)


# ─────────────────────────────────────────────────────────────
# 2) PDF-отчёт
@r.callback_query(Form.result_page, F.data == "download_pdf")
async def download_pdf(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    # какие колонки выводим
    select_fields = [Stock.region, Stock.warehouse,
                     Stock.nomenclature, Stock.characteristic, Stock.photo_url,
                     func.sum(Stock.balance).label("bal")]
    group_by_cols = [Stock.region, Stock.warehouse,
                     Stock.nomenclature, Stock.characteristic, Stock.photo_url]

    async with AsyncSessionLocal() as s:
        # --- данные об остатках
        stmt = select(*select_fields).group_by(*group_by_cols)

        for key, column in FILTER_MAP.items():
            val = data.get(key)
            if val and val.lower() != "все":
                stmt = stmt.filter(column == val)

        if data.get("search"):
            stmt = stmt.filter(Stock.nomenclature.ilike(f"%{data['search']}%"))

        rows = (await s.execute(stmt)).all()

        # --- максимальная updated_at
        ts_stmt = select(func.max(Stock.updated_at))
        for key, column in FILTER_MAP.items():
            val = data.get(key)
            if val and val.lower() != "все":
                ts_stmt = ts_stmt.filter(column == val)

        max_ts = await s.scalar(ts_stmt)
        if max_ts:
            if max_ts.tzinfo is not None:
                max_ts = max_ts.astimezone(ZoneInfo("Europe/Moscow"))
            ts_str = max_ts.strftime("%d.%m.%Y %H:%M")
        else:
            ts_str = "—"

    # ─── PDF ───
    font_path = os.path.join("app", "fonts", "DejaVuSans.ttf")
    pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "app/fonts/DejaVuSans-Bold.ttf"))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        doc = SimpleDocTemplate(tmp.name, pagesize=A4)
        styles = getSampleStyleSheet()

        normal = styles["Normal"]
        normal.fontName = "DejaVuSans"
        bold = ParagraphStyle(
            name="GroupHeader",
            parent=styles["Normal"],
            fontName="DejaVuSans-Bold",
            fontSize=11, leading=13)

        elems = []

        # ▸ шапка
        breadcrumbs = get_breadcrumb_text(data, "brand").replace("\n", "<br/>")
        elems.append(Paragraph(breadcrumbs, bold))
        elems.append(Paragraph(f"Актуально на: {ts_str}", bold))
        elems.append(Spacer(1, 8))

        # ▸ группировка Region / Warehouse
        from collections import defaultdict
        grouped = defaultdict(list)
        for row in rows:
            key = f"{row.region or '—'} / {row.warehouse or '—'}"
            grouped[key].append((row.nomenclature, row.characteristic, row.photo_url, row.bal))

        for idx, (title, grp) in enumerate(grouped.items()):
            if idx:  # небольшой промежуток между группами
                elems.append(Spacer(1, 10))

            elems.append(Paragraph(title, bold))
            table_data = (
                    [[Paragraph("Номенклатура", normal),
                      Paragraph("Характеристика", normal),
                      Paragraph("Фото", normal),
                      Paragraph("Остаток", normal)]] +
                    [[Paragraph(str(n or ""), normal),
                      Paragraph(str(ch or ""), normal),
                      Paragraph(f'<a href="{ph}" color="blue"><u>Ссылка</u></a>' if ph else "", normal),
                      f"{b:,.0f}"]
                     for n, ch, ph, b in grp]
            )
            t = Table(table_data, colWidths=[200, 130, 100, 80])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]))
            elems.append(t)

        doc.build(elems)

        with open(tmp.name, "rb") as f:
            await c.message.answer_document(
                BufferedInputFile(f.read(), filename="report.pdf"),
                caption="📄 PDF-отчёт с датой актуальности"
            )


@r.callback_query(Form.result_page, F.data == "download_pdf_simple")
async def download_pdf_simple(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    select_fields = [Stock.region, Stock.warehouse,
                     Stock.nomenclature,
                     func.sum(Stock.balance).label("bal")]
    group_by_cols = [Stock.region, Stock.warehouse, Stock.nomenclature]

    async with AsyncSessionLocal() as s:
        stmt = select(*select_fields).group_by(*group_by_cols)

        for key, column in FILTER_MAP.items():
            val = data.get(key)
            if val and val.lower() != "все":
                stmt = stmt.filter(column == val)

        if data.get("search"):
            stmt = stmt.filter(Stock.nomenclature.ilike(f"%{data['search']}%"))

        rows = (await s.execute(stmt)).all()

        ts_stmt = select(func.max(Stock.updated_at))
        for key, column in FILTER_MAP.items():
            val = data.get(key)
            if val and val.lower() != "все":
                ts_stmt = ts_stmt.filter(column == val)

        max_ts = await s.scalar(ts_stmt)
        if max_ts:
            if max_ts.tzinfo is not None:
                max_ts = max_ts.astimezone(ZoneInfo("Europe/Moscow"))
            ts_str = max_ts.strftime("%d.%m.%Y %H:%M")
        else:
            ts_str = "—"

    font_path = os.path.join("app", "fonts", "DejaVuSans.ttf")
    pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "app/fonts/DejaVuSans-Bold.ttf"))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        doc = SimpleDocTemplate(tmp.name, pagesize=A4)
        styles = getSampleStyleSheet()

        normal = styles["Normal"]
        normal.fontName = "DejaVuSans"
        bold = ParagraphStyle(
            name="GroupHeader",
            parent=styles["Normal"],
            fontName="DejaVuSans-Bold",
            fontSize=11, leading=13)

        elems = []

        breadcrumbs = get_breadcrumb_text(data, "brand").replace("\n", "<br/>")
        elems.append(Paragraph(breadcrumbs, bold))
        elems.append(Paragraph(f"Актуально на: {ts_str}", bold))
        elems.append(Spacer(1, 8))

        from collections import defaultdict
        grouped = defaultdict(list)
        for row in rows:
            key = f"{row.region or '—'} / {row.warehouse or '—'}"
            grouped[key].append((row.nomenclature, row.bal))

        for idx, (title, grp) in enumerate(grouped.items()):
            if idx:
                elems.append(Spacer(1, 10))

            elems.append(Paragraph(title, bold))
            table_data = (
                    [[Paragraph("Номенклатура", normal),
                      Paragraph("Остаток", normal)]] +
                    [[Paragraph(str(n or ""), normal),
                      f"{b:,.0f}"]
                     for n, b in grp]
            )
            t = Table(table_data, colWidths=[430, 80])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]))
            elems.append(t)

        doc.build(elems)

        with open(tmp.name, "rb") as f:
            await c.message.answer_document(
                BufferedInputFile(f.read(), filename="report.pdf"),
                caption="📄 PDF-отчёт с датой актуальности"
            )


@r.callback_query(Form.result_page, F.data.startswith("page:"))
async def change_page(c: CallbackQuery, state: FSMContext):
    page = int(c.data.split(":")[1])
    await state.update_data(page=page)
    await show_result(c, state)


@r.callback_query(Form.result_page, F.data == "search")
async def ask_search(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Введите часть названия для поиска по Номенклатуре:")
    await state.set_state(Form.result_page)


@r.message(Form.result_page)
async def search_query(msg: Message, state: FSMContext):
    await state.update_data(search=msg.text, page=1)
    await show_result(msg, state)


@r.message(F.text & ~F.text.startswith("/"))
async def handle_search_input(msg: Message, state: FSMContext):
    data = await state.get_data()

    prefix = data.get("search_mode")
    if not prefix:
        # Не в поиске — пропускаем сообщение, даём другим хендлерам (например, /start) обработать
        return

    original = data.get(f"{prefix}_list", [])
    query = msg.text.strip().lower()

    filtered = [item for item in original if query in item.lower()]
    if not filtered:
        await msg.answer("Ничего не найдено.")
        return

    await state.update_data({
        f"{prefix}_search_list": filtered,
        "search_mode": None
    })

    await msg.answer(
        f"Результаты поиска по: {query}",
        reply_markup=paginated_keyboard(filtered, 1, prefix, back_prefix=search_back_step(prefix))
    )
