from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Numeric, BigInteger, ForeignKey

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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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
