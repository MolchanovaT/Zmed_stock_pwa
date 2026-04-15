import json
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Numeric, BigInteger, ForeignKey, Text

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import DateTime

from app.db.base import Base


class Stock(Base):
    __tablename__ = "implant_stock"

    id = Column(Integer, primary_key=True)
    group_name = Column(String, index=True)
    region = Column(String, index=True)
    warehouse = Column(String, index=True)
    category = Column(String, index=True)
    manufacturer = Column(String, index=True)
    brand = Column(String, index=True)
    nom_type = Column(String, index=True)
    nomenclature = Column(String)
    article = Column(String)
    characteristic = Column(String)
    balance = Column(Numeric)
    updated_at = Column(DateTime, nullable=False)
    source = Column(String)


class AdminUser(Base, UserMixin):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    # JSON-список доступных модулей: '["implants","supplies"]'
    # None / пустая строка = нет доступа ни к чему
    modules = Column(String, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_modules(self) -> list[str]:
        """Возвращает список разрешённых модулей."""
        if not self.modules:
            return []
        try:
            return json.loads(self.modules)
        except (ValueError, TypeError):
            return []


class Supplies(Base):
    """Остатки расходников и инструментов (таблица stock из zmed_stock_bot)."""
    __tablename__ = "stock"

    id = Column(Integer, primary_key=True)
    group_name = Column(String, index=True)
    region = Column(String, index=True)
    warehouse = Column(String, index=True)
    category = Column(String, index=True)
    manufacturer = Column(String, index=True)
    brand = Column(String, index=True)
    nomenclature = Column(String)
    characteristic = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    balance = Column(Numeric)
    updated_at = Column(DateTime, nullable=False)


class AllowedUser(Base):
    __tablename__ = "allowed_users"

    id = Column(Integer, primary_key=True)  # NEW
    tg_id = Column(BigInteger, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    title = Column(String, nullable=True)


class Cart(Base):
    __tablename__ = "carts"

    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BigInteger, index=True, nullable=False)
    lpu = Column(String, nullable=True)
    status = Column(String, default="active")  # active / submitted
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    delivery_date = Column(String, nullable=True)
    delivery_time = Column(String, nullable=True)
    doctor = Column(String, nullable=True)
    instrument = Column(String, nullable=True)


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey("carts.id"), nullable=False)
    article = Column(String)
    nomenclature = Column(String)
    characteristic = Column(String)
    quantity = Column(Integer, default=1)
    available_balance = Column(Numeric)


class InnDiler(Base):
    """Дилеры для проверки отгрузки по ИНН."""
    __tablename__ = "inn_dilers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    inn = Column(String, unique=True, nullable=False, index=True)
    allowed = Column(Integer, default=1)  # 1=да, 0=нет


class InnLpu(Base):
    """ЛПУ для проверки отгрузки по ИНН."""
    __tablename__ = "inn_lpu"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    inn = Column(String, unique=True, nullable=False, index=True)
    allowed = Column(Integer, default=1)


class InnPending(Base):
    """Заявки на рассмотрение."""
    __tablename__ = "inn_pending"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    inn = Column(String, unique=True, nullable=False, index=True)
    date = Column(String, nullable=True)   # строка "YYYY-MM-DD"
    approved = Column(Integer, default=0)  # 1=одобрено
    denied = Column(Integer, default=0)    # 1=отклонено


class PwaActivity(Base):
    __tablename__ = "pwa_activity"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String, nullable=True)
    action = Column(String(32), nullable=False)   # login|search|pdf_export|add_to_cart|place_order|clear_cart
    detail = Column(Text, nullable=True)           # JSON с подробностями
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
