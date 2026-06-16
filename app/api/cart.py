"""
app/api/cart.py

REST-эндпоинты для работы с корзиной и оформления заказа.
Email-уведомление через send_order_notification из app.api.email.

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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from app.api.activity import log_activity
from app.api.auth import get_current_user
from app.api.email import send_order_notification
from app.db.models import User, Cart, CartItem
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/cart", tags=["cart"])

ALLOWED_KINDS = {"implants", "supplies"}


def _validate_kind(kind: str) -> str:
    if kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail=f"Неизвестный kind: {kind}")
    return kind


# ── Pydantic-схемы ─────────────────────────────────────────────────────────────

class CartItemIn(BaseModel):
    article: str = ""
    nomenclature: str
    characteristic: str = ""
    quantity: int = Field(1, ge=1)
    available_balance: float = 0.0
    lpu: Optional[str] = None          # склад-источник (фиксируется на первой позиции)


class QuantityPatch(BaseModel):
    quantity: int = Field(..., ge=1)


class OrderIn(BaseModel):
    lpu: str                           # ЛПУ-получатель (куда везём)
    delivery_date: str                 # формат ДД.ММ.ГГГГ
    delivery_time: str                 # слот или произвольный диапазон, напр. "07:00-08:30"
    doctor: str
    instrument: str = "нет"           # "да" | "нет"
    comment: str = ""                  # свободный комментарий


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize_cart(cart: Cart, items: list[CartItem]) -> dict:
    return {
        "id": cart.id,
        "kind": cart.kind,
        "lpu": cart.lpu,
        "source_lpu": cart.source_lpu,
        "status": cart.status,
        "created_at": cart.created_at.isoformat() if cart.created_at else None,
        "delivery_date": cart.delivery_date,
        "delivery_time": cart.delivery_time,
        "doctor": cart.doctor,
        "instrument": cart.instrument,
        "comment": cart.comment,
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


async def _get_active_cart(user_id: int, session, kind: str = "implants") -> Optional[Cart]:
    result = await session.execute(
        select(Cart)
        .where(
            Cart.tg_user_id == user_id,
            Cart.status == "active",
            Cart.kind == kind,
        )
        .order_by(Cart.created_at.desc())
    )
    return result.scalars().first()


# ── Эндпоинты ─────────────────────────────────────────────────────────────────

@router.get("")
async def get_cart(
    kind: str = Query("implants"),
    current_user: User = Depends(get_current_user),
):
    """Возвращает активную корзину пользователя вместе со всеми позициями."""
    kind = _validate_kind(kind)
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s, kind)
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
    kind: str = Query("implants"),
    current_user: User = Depends(get_current_user),
):
    """
    Добавляет позицию в активную корзину заданного типа (implants|supplies).
    Если активной корзины нет — создаёт новую с переданным lpu.
    """
    kind = _validate_kind(kind)
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s, kind)

        if cart is None:
            cart = Cart(
                tg_user_id=current_user.id,
                kind=kind,
                # lpu (получатель) выберется на этапе оформления заказа.
                # source_lpu (источник) фиксируем здесь — потом не меняем.
                source_lpu=(body.lpu or "").strip() or None,
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
async def clear_cart(
    kind: str = Query("implants"),
    current_user: User = Depends(get_current_user),
):
    """Удаляет все позиции из активной корзины и саму корзину."""
    kind = _validate_kind(kind)
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s, kind)
        if not cart:
            return
        await s.execute(
            delete(CartItem).where(CartItem.cart_id == cart.id)
        )
        await s.delete(cart)
        await s.commit()


@router.get("/orders")
async def get_orders(
    kind: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """Возвращает оформленные заказы текущего пользователя (status=submitted).

    Если передан kind — фильтрует по нему; иначе отдаёт все.
    """
    if kind is not None:
        kind = _validate_kind(kind)
    async with AsyncSessionLocal() as s:
        stmt = select(Cart).where(
            Cart.tg_user_id == current_user.id,
            Cart.status == "submitted",
        )
        if kind is not None:
            stmt = stmt.where(Cart.kind == kind)
        carts_res = await s.execute(stmt.order_by(Cart.created_at.desc()))
        carts = list(carts_res.scalars().all())

        orders = []
        for cart in carts:
            items_res = await s.execute(
                select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
            )
            items = list(items_res.scalars().all())
            orders.append(_serialize_cart(cart, items))

    return {"orders": orders}


@router.post("/order")
async def place_order(
    body: OrderIn,
    kind: str = Query("implants"),
    current_user: User = Depends(get_current_user),
):
    """
    Оформляет заказ:
    - сохраняет дату/время доставки, врача, инструмент в корзину
    - меняет статус корзины на "submitted"
    - отправляет email-уведомление (логика из handlers.send_order_notification)
    """
    kind = _validate_kind(kind)
    async with AsyncSessionLocal() as s:
        cart = await _get_active_cart(current_user.id, s, kind)
        if not cart:
            raise HTTPException(status_code=404, detail="Активная корзина не найдена")

        items_res = await s.execute(
            select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.id)
        )
        items = list(items_res.scalars().all())
        if not items:
            raise HTTPException(status_code=400, detail="Корзина пуста")

        cart_id_val = cart.id
        cart_lpu = body.lpu.strip() or "не указано"
        source_lpu = (cart.source_lpu or "").strip()

        # Получатель не должен совпадать со складом-источником.
        # Проверка только если оба известны — старые корзины без source_lpu пропускаем.
        if source_lpu and cart_lpu.lower() == source_lpu.lower():
            raise HTTPException(
                status_code=400,
                detail="Склад-получатель должен отличаться от склада-источника",
            )

        comment_val = (body.comment or "").strip() or None
        items_snapshot = [
            (it.article, it.nomenclature, it.characteristic, it.quantity, int(it.available_balance or 0))
            for it in items
        ]

        cart.lpu = cart_lpu
        cart.delivery_date = body.delivery_date
        cart.delivery_time = body.delivery_time
        cart.doctor = body.doctor
        cart.instrument = body.instrument
        cart.comment = comment_val
        cart.status = "submitted"
        s.add(cart)
        await s.commit()

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    kind_label = "расходники" if kind == "supplies" else "импланты"
    subject = f"Заказ #{cart_id_val} ({kind_label}) | ЛПУ: {cart_lpu} | {now_str}"

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
        source_lpu=source_lpu or "не указано",
        comment=comment_val or "",
        kind=kind,
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
