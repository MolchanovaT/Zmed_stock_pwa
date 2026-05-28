from aiogram.fsm.state import StatesGroup, State


class Form(StatesGroup):
    group = State()
    region = State()
    warehouse = State()
    category = State()
    manufacturer = State()
    brand = State()
    nom_type = State()
    result_page = State()
