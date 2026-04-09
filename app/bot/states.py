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


class CartFlow(StatesGroup):
    select_items = State()   # выбор позиций из результатов
    lpu_select = State()     # выбор ЛПУ из списка складов
    lpu_input = State()      # ввод ЛПУ вручную
    cart_view = State()      # просмотр корзины
    delivery_date = State()  # ввод даты доставки
    delivery_time = State()  # ввод времени доставки
    doctor = State()         # ввод врача (контактное лицо)
    instrument = State()     # выбор инструмент Да/Нет
