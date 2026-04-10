"""
app/api/cart.py

REST-эндпоинты для работы с корзиной и оформления заказа.
Email-уведомление переиспользует send_order_notification из app.bot.handlers.

Эндпоинты:
  GET    /api/cart                — активная корзина пользователя
  POST   /api/cart/items          — добавить позицию
  PATCH  /api/cart/items/{id}     — изменить количество
  DELETE /api/cart/items/{id}     — удалить позицию
  POST   /api/cart/order          — оформить заказ
"""

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from app.api.activity import log_activity
from app.api.auth import get_current_user
from app.bot.handlers import send_order_notification  # переиспользуем логику email
from app.db.models import AdminUser, Cart, CartItem
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/cart", tags=["cart"])


# ── Pydantic-схемы ─────────────────────────────────────────────────────────────

class CartItemIn(BaseModel):
    article: str = ""
    nomenclature: str
    characteristic: str = ""
    quantity: int = Field(1, ge=1)
    available_balance: float = 0.0
    lpu: Optional[str] = None          # ЛПУ для новой корзины


class QuantityPatch(BaseModel):
    quantity: int = Field(..., ge=1)


class OrderIn(BaseModel):
    lpu: str                           # ЛПУ (учреждение)
    delivery_date: str                 # формат ДД.ММ.ГГГГ
    delivery_time: str                 # формат ЧЧ:ММ
    doctor: str
    instrument: str = "нет"           # "да" | "нет"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize_cart(cart: Cart, items: list[CartItem]) -> dict:
    return {
        "id": cart.id,
        "lpu": cart.lpu,
        "status": cart.status,
        "created_at": cart.created_at.isoformat() if cart.created_at else None,
        "delivery_date": cart.delivery_date,
        "delivery_time": cart.delivery_time,
        "doctor": cart.doctor,
        "instrument": cart.instrument,
        "items": [
            {
                "id": it.id,
                "article": it.article,
                "nomenclature": it.nomenclature,
                "characteristic": it.characteristic,
                "quantity": it.quantity,
                "available_balance": float(it.available_balance or 0),
            }
            for it in items
        ],
    }


async def _get_active_cart(user_id: int, session) -> Optional[Cart]:
    result = await session.execute(
        select(Cart)
        .where(Cart.tg_user_id == user_id, Cart.status == "active")
        .order_by(Cart.created_at.desc())
    )
    return result.scalars().first()


# ── Эндпоинты ─────────────────────────────────────────────────────────────────

@router.get("")
async def get_cart(current_user: AdminUser = Depends(get_current_user)):
    """Возвращает активную корзину пользователя вместе со всеми позициями."""
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s)
        if not cart:
            return {"cart": None}
        items_res = await s.execute(
            select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
        )
        items = list(items_res.scalars().all())
    return {"cart": _serialize_cart(cart, items)}


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def add_cart_item(
    body: CartItemIn,
    current_user: AdminUser = Depends(get_current_user),
):
    """
    Добавляет позицию в активную корзину.
    Если активной корзины нет — создаёт новую с переданным lpu.
    """
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s)

        if cart is None:
            cart = Cart(
                tg_user_id=current_user.id,
                lpu=body.lpu or "",
                status="active",
            )
            s.add(cart)
            await s.flush()   # получаем cart.id

        item = CartItem(
            cart_id=cart.id,
            article=body.article,
            nomenclature=body.nomenclature,
            characteristic=body.characteristic,
            quantity=body.quantity,
            available_balance=body.available_balance,
        )
        s.add(item)
        await s.commit()
        await s.refresh(item)
        await s.refresh(cart)

        items_res = await s.execute(
            select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
        )
        items = list(items_res.scalars().all())

    asyncio.create_task(log_activity(
        current_user.id, current_user.username, "add_to_cart",
        {"article": body.article, "nomenclature": body.nomenclature,
         "characteristic": body.characteristic, "quantity": body.quantity},
    ))
    return {"cart": _serialize_cart(cart, items)}


@router.patch("/items/{item_id}")
async def update_cart_item(
    item_id: int,
    body: QuantityPatch,
    current_user: AdminUser = Depends(get_current_user),
):
    """Изменяет количество позиции в корзине."""
    async with AsyncSessionLocal() as s:
        item = await s.get(CartItem, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Позиция не найдена")

        # Проверяем что позиция принадлежит корзине текущего пользователя
        cart = await s.get(Cart, item.cart_id)
        if not cart or cart.tg_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Нет доступа")

        item.quantity = body.quantity
        s.add(item)
        await s.commit()
        await s.refresh(item)

    return {"id": item.id, "quantity": item.quantity}


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cart_item(
    item_id: int,
    current_user: AdminUser = Depends(get_current_user),
):
    """Удаляет позицию из корзины."""
    async with AsyncSessionLocal() as s:
        item = await s.get(CartItem, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Позиция не найдена")

        cart = await s.get(Cart, item.cart_id)
        if not cart or cart.tg_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Нет доступа")

        await s.delete(item)
        await s.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(current_user: AdminUser = Depends(get_current_user)):
    """Удаляет все позиции из активной корзины и саму корзину."""
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s)
        if not cart:
            return
        await s.execute(
            delete(CartItem).where(CartItem.cart_id == cart.id)
        )
        await s.delete(cart)
        await s.commit()


@router.post("/order")
async def place_order(
    body: OrderIn,
    current_user: AdminUser = Depends(get_current_user),
):
    """
    Оформляет заказ:
    - сохраняет дату/время доставки, врача, инструмент в корзину
    - меняет статус корзины на "submitted"
    - отправляет email-уведомление (логика из handlers.send_order_notification)
    """
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s)
        if not cart:
            raise HTTPException(status_code=404, detail="Активная корзина не найдена")

        items_res = await s.execute(
            select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
        )
        items = list(items_res.scalars().all())
        if not items:
            raise HTTPException(status_code=400, detail="Корзина пуста")

        cart_id_val = cart.id
        cart_lpu = body.lpu.strip() or cart.lpu or "не указано"
        items_snapshot = [
            (it.article, it.nomenclature, it.characteristic, it.quantity, int(it.available_balance or 0))
            for it in items
        ]

        cart.lpu = cart_lpu
        cart.delivery_date = body.delivery_date
        cart.delivery_time = body.delivery_time
        cart.doctor = body.doctor
        cart.instrument = body.instrument
        cart.status = "submitted"
        s.add(cart)
        await s.commit()

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    subject = f"Заказ #{cart_id_val} | ЛПУ: {cart_lpu} | {now_str}"

    # Переиспользуем готовую логику отправки email из бота
    asyncio.create_task(send_order_notification(
        subject=subject,
        cart_id=cart_id_val,
        lpu=cart_lpu,
        user_full_name=current_user.username,
        user_username=current_user.username,
        user_tg_id=current_user.id,
        now_str=now_str,
        items_snapshot=items_snapshot,
        delivery_date=body.delivery_date,
        delivery_time=body.delivery_time,
        doctor=body.doctor,
        instrument=body.instrument,
    ))

    asyncio.create_task(log_activity(
        current_user.id, current_user.username, "place_order",
        {"order_id": cart_id_val, "lpu": cart_lpu, "items_count": len(items_snapshot)},
    ))
    return {
        "order_id": cart_id_val,
        "status": "submitted",
        "message": f"Заказ #{cart_id_val} оформлен. Уведомление отправлено.",
    }
