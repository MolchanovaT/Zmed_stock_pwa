from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Дилер", callback_data="diler"),
     InlineKeyboardButton(text="ЛПУ", callback_data="lpu")],
])
