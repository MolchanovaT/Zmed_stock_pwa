from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from math import ceil


def paginated_keyboard(items: list[str], page: int = 1, per_page: int = 10, prefix: str = "", back_prefix: str = None) -> InlineKeyboardMarkup:
    from math import ceil
    total_pages = max(1, ceil(len(items) / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    current_items = items[start:end]

    rows = [[InlineKeyboardButton(text=item, callback_data=f"{prefix}:{item}")] for item in current_items]

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}:page:{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}:page:{page+1}"))
    if nav_row:
        rows.append(nav_row)

    # кнопка назад (если задано)
    if back_prefix:
        rows.append([InlineKeyboardButton("↩ Назад", callback_data=f"back:{back_prefix}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
