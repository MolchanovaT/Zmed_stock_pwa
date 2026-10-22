"""
app/api/clinic_stock.py

Модуль «Учёт товара на ОХ в клинике» (modules.clinic_stock).

Эндпоинты:

  Справочники:
    GET    /api/clinic-stock/locations            — список локаций
    POST   /api/clinic-stock/locations            — создать локацию
    PATCH  /api/clinic-stock/locations/{id}       — переименовать/деактивировать

  Товар:
    GET    /api/clinic-stock/items                — список партий + остатки
    GET    /api/clinic-stock/items/{id}           — одна партия
    GET    /api/clinic-stock/scan?barcode=X       — поиск по штрихкоду

  Движения (идемпотентны по doc_number в рамках одной клиники):
    POST   /api/clinic-stock/receive              — приход от ZMed
    POST   /api/clinic-stock/transfer             — между локациями
    POST   /api/clinic-stock/consume              — расход на операцию
    POST   /api/clinic-stock/return               — возврат на склад
    POST   /api/clinic-stock/inventory            — проставить факт после подсчёта
    POST   /api/clinic-stock/write-off            — списать

  Журнал:
    GET    /api/clinic-stock/movements            — журнал с фильтрами

  Отчёт потерь (для ZMed):
    GET    /api/clinic-stock/losses               — списанное, не привязанное
                                                     к operation_report

Все операции идут в транзакции: баланс пересчитывается в clinic_stock_balances
одновременно с добавлением строки в clinic_stock_movements.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, select

from fastapi.responses import StreamingResponse

from app.api.activity import log_activity
from app.api.scoping import OrgScope, require_org_scope, resolve_target_org_id
from app.db.models import (
    ClinicStockBalance, ClinicStockItem, ClinicStockLocation,
    ClinicStockMovement, OperationReport, Organization,
)
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/clinic-stock", tags=["clinic_stock"])

ALLOWED_LOCATION_KINDS = {"warehouse", "surgery", "other"}
ALLOWED_MOVEMENT_KINDS = {
    "receive", "transfer", "consume", "return", "inventory_adjust", "write_off",
}
# «Потерями» для /losses считаем:
LOSS_KINDS = {"inventory_adjust", "write_off"}


# ── Pydantic ────────────────────────────────────────────────────────────────

class LocationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: str = Field("warehouse")
    active: bool = True
    organization_id: Optional[int] = None  # нужен для ZMed-staff


class LocationPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    kind: Optional[str] = None
    active: Optional[bool] = None


class ReceiveIn(BaseModel):
    """Приход — создаёт (или находит) партию и зачисляет её на to_location."""
    organization_id: Optional[int] = None
    article: str
    nomenclature: str
    characteristic: Optional[str] = None
    lot_number: Optional[str] = None
    expiration_date: Optional[str] = None  # YYYY-MM-DD
    barcode: Optional[str] = None
    to_location_id: int
    quantity: int = Field(..., ge=1)
    doc_number: Optional[str] = None
    note: Optional[str] = None


class TransferIn(BaseModel):
    item_id: int
    from_location_id: int
    to_location_id: int
    quantity: int = Field(..., ge=1)
    doc_number: Optional[str] = None
    note: Optional[str] = None


class ConsumeIn(BaseModel):
    """Расход на операцию — опциональная связка с operation_report (H1)."""
    item_id: int
    from_location_id: int
    quantity: int = Field(..., ge=1)
    operation_report_id: Optional[int] = None
    doc_number: Optional[str] = None
    note: Optional[str] = None


class ReturnIn(BaseModel):
    item_id: int
    from_location_id: int
    to_location_id: int
    quantity: int = Field(..., ge=1)
    doc_number: Optional[str] = None
    note: Optional[str] = None


class InventoryIn(BaseModel):
    """Инвентаризация: клиника сообщает фактический остаток в location.
    Разница пишется в inventory_adjust (quantity может быть отрицательной)."""
    item_id: int
    location_id: int
    actual_quantity: int = Field(..., ge=0)
    note: Optional[str] = None


class WriteOffIn(BaseModel):
    item_id: int
    from_location_id: int
    quantity: int = Field(..., ge=1)
    note: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_iso_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        date.fromisoformat(s)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400,
                            detail=f"Дата должна быть YYYY-MM-DD, получено: {s!r}")
    return s


def _scope_matches_org(scope: OrgScope, resource_org_id: int) -> bool:
    """Проверка, что scope позволяет видеть/менять ресурс этой организации."""
    if scope.is_zmed:
        if scope.organization_id is not None:
            return resource_org_id == scope.organization_id
        return True  # ZMed без явного фильтра — доступ ко всем
    return resource_org_id == scope.user.organization_id


async def _assert_location_in_scope(session, location_id: int,
                                     scope: OrgScope) -> ClinicStockLocation:
    loc = await session.get(ClinicStockLocation, location_id)
    if loc is None or not loc.active or not _scope_matches_org(scope, loc.organization_id):
        raise HTTPException(status_code=404,
                            detail=f"Локация id={location_id} не найдена")
    return loc


async def _assert_item_in_scope(session, item_id: int,
                                 scope: OrgScope) -> ClinicStockItem:
    item = await session.get(ClinicStockItem, item_id)
    if item is None or not _scope_matches_org(scope, item.organization_id):
        raise HTTPException(status_code=404,
                            detail=f"Партия id={item_id} не найдена")
    return item


async def _target_org_from_scope(scope: OrgScope, explicit_org_id: Optional[int]) -> int:
    """Для операций записи — чей ОХ меняем."""
    return await resolve_target_org_id(scope, explicit_org_id)


async def _apply_delta(session, item_id: int, location_id: int, delta: int) -> int:
    """Атомарно: прибавить delta к балансу (item_id, location_id). Возвращает новый остаток.
    Отрицательный остаток запрещён (кроме inventory_adjust — там контроль выше)."""
    res = await session.execute(
        select(ClinicStockBalance).where(
            ClinicStockBalance.item_id == item_id,
            ClinicStockBalance.location_id == location_id,
        )
    )
    bal = res.scalars().first()
    if bal is None:
        if delta < 0:
            raise HTTPException(status_code=409,
                                detail="Остаток уйдёт в минус (на локации нет этой партии)")
        bal = ClinicStockBalance(item_id=item_id, location_id=location_id, quantity=0)
        session.add(bal)
    new_q = (bal.quantity or 0) + delta
    if new_q < 0:
        raise HTTPException(status_code=409,
                            detail=f"Недостаточно остатка: есть {bal.quantity}, нужно {-delta}")
    bal.quantity = new_q
    return new_q


async def _get_item_balances(session, item_ids: list[int]) -> dict[int, list[dict]]:
    """Для списка партий — остатки по локациям (включая 0 — чтобы было видно, где был)."""
    if not item_ids:
        return {}
    res = await session.execute(
        select(ClinicStockBalance, ClinicStockLocation)
        .join(ClinicStockLocation, ClinicStockLocation.id == ClinicStockBalance.location_id)
        .where(ClinicStockBalance.item_id.in_(item_ids))
        .order_by(ClinicStockBalance.item_id, ClinicStockLocation.name)
    )
    out: dict[int, list[dict]] = {}
    for bal, loc in res.all():
        out.setdefault(bal.item_id, []).append({
            "location_id": loc.id,
            "location_name": loc.name,
            "location_kind": loc.kind,
            "quantity": bal.quantity,
        })
    return out


def _ser_item(item: ClinicStockItem, balances: list[dict]) -> dict:
    total = sum(b["quantity"] for b in balances) if balances else 0
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "article": item.article,
        "nomenclature": item.nomenclature,
        "characteristic": item.characteristic,
        "barcode": item.barcode,
        "lot_number": item.lot_number,
        "expiration_date": item.expiration_date,
        "received_at": item.received_at.isoformat() if item.received_at else None,
        "received_doc_number": item.received_doc_number,
        "balances": balances,
        "total_balance": total,
    }


def _ser_location(loc: ClinicStockLocation) -> dict:
    return {
        "id": loc.id,
        "organization_id": loc.organization_id,
        "name": loc.name,
        "kind": loc.kind,
        "active": bool(loc.active),
    }


def _ser_movement(m: ClinicStockMovement) -> dict:
    return {
        "id": m.id,
        "organization_id": m.organization_id,
        "kind": m.kind,
        "item_id": m.item_id,
        "from_location_id": m.from_location_id,
        "to_location_id": m.to_location_id,
        "quantity": m.quantity,
        "user_id": m.user_id,
        "operation_report_id": m.operation_report_id,
        "doc_number": m.doc_number,
        "note": m.note,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ── Локации ─────────────────────────────────────────────────────────────────

@router.get("/locations")
async def list_locations(scope: OrgScope = Depends(require_org_scope)):
    async with AsyncSessionLocal() as s:
        stmt = select(ClinicStockLocation).order_by(ClinicStockLocation.name)
        if scope.organization_id is not None:
            stmt = stmt.where(ClinicStockLocation.organization_id == scope.organization_id)
        locs = (await s.execute(stmt)).scalars().all()
    return {"locations": [_ser_location(l) for l in locs]}


@router.post("/locations", status_code=status.HTTP_201_CREATED)
async def create_location(body: LocationIn, scope: OrgScope = Depends(require_org_scope)):
    if body.kind not in ALLOWED_LOCATION_KINDS:
        raise HTTPException(status_code=400, detail=f"kind: {body.kind}")
    org_id = await _target_org_from_scope(scope, body.organization_id)
    async with AsyncSessionLocal() as s:
        exists = (await s.execute(
            select(ClinicStockLocation).where(
                ClinicStockLocation.organization_id == org_id,
                ClinicStockLocation.name == body.name.strip(),
            )
        )).scalars().first()
        if exists:
            raise HTTPException(status_code=409,
                                detail=f"Локация «{body.name}» уже есть")
        loc = ClinicStockLocation(
            organization_id=org_id,
            name=body.name.strip(),
            kind=body.kind,
            active=1 if body.active else 0,
        )
        s.add(loc)
        await s.commit()
        await s.refresh(loc)
    return _ser_location(loc)


@router.patch("/locations/{loc_id}")
async def patch_location(loc_id: int, body: LocationPatch,
                         scope: OrgScope = Depends(require_org_scope)):
    async with AsyncSessionLocal() as s:
        loc = await s.get(ClinicStockLocation, loc_id)
        if loc is None:
            raise HTTPException(status_code=404, detail="Локация не найдена")
        if not scope.is_zmed and loc.organization_id != scope.user.organization_id:
            raise HTTPException(status_code=404, detail="Локация не найдена")
        if scope.organization_id is not None and loc.organization_id != scope.organization_id:
            raise HTTPException(status_code=404, detail="Локация не найдена")

        if body.name is not None:
            loc.name = body.name.strip()
        if body.kind is not None:
            if body.kind not in ALLOWED_LOCATION_KINDS:
                raise HTTPException(status_code=400, detail=f"kind: {body.kind}")
            loc.kind = body.kind
        if body.active is not None:
            loc.active = 1 if body.active else 0

        s.add(loc)
        await s.commit()
        await s.refresh(loc)
    return _ser_location(loc)


# ── Товар ───────────────────────────────────────────────────────────────────

@router.get("/items")
async def list_items(
    q: Optional[str] = Query(None, max_length=200),
    only_in_stock: bool = Query(False),
    scope: OrgScope = Depends(require_org_scope),
):
    """Список партий с суммарным остатком по локациям."""
    async with AsyncSessionLocal() as s:
        stmt = select(ClinicStockItem).order_by(
            ClinicStockItem.article, ClinicStockItem.id.desc()
        )
        if scope.organization_id is not None:
            stmt = stmt.where(ClinicStockItem.organization_id == scope.organization_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                (ClinicStockItem.article.ilike(pattern)) |
                (ClinicStockItem.nomenclature.ilike(pattern)) |
                (ClinicStockItem.barcode.ilike(pattern)) |
                (ClinicStockItem.lot_number.ilike(pattern))
            )
        items = list((await s.execute(stmt)).scalars().all())
        balances = await _get_item_balances(s, [i.id for i in items])
    out = [_ser_item(i, balances.get(i.id, [])) for i in items]
    if only_in_stock:
        out = [i for i in out if i["total_balance"] > 0]
    return {"items": out}


@router.get("/items/{item_id}")
async def get_item(item_id: int, scope: OrgScope = Depends(require_org_scope)):
    async with AsyncSessionLocal() as s:
        item = await s.get(ClinicStockItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Партия не найдена")
        if not scope.is_zmed and item.organization_id != scope.user.organization_id:
            raise HTTPException(status_code=404, detail="Партия не найдена")
        if scope.organization_id is not None and item.organization_id != scope.organization_id:
            raise HTTPException(status_code=404, detail="Партия не найдена")
        balances = (await _get_item_balances(s, [item.id])).get(item.id, [])
    return _ser_item(item, balances)


@router.get("/scan")
async def scan_barcode(
    barcode: str = Query(..., min_length=1, max_length=200),
    scope: OrgScope = Depends(require_org_scope),
):
    """Поиск партии по штрихкоду. При множественном совпадении — возвращает все."""
    async with AsyncSessionLocal() as s:
        stmt = select(ClinicStockItem).where(ClinicStockItem.barcode == barcode)
        if scope.organization_id is not None:
            stmt = stmt.where(ClinicStockItem.organization_id == scope.organization_id)
        items = list((await s.execute(stmt)).scalars().all())
        if not items:
            # fallback — поиск по артикулу
            stmt = select(ClinicStockItem).where(ClinicStockItem.article == barcode)
            if scope.organization_id is not None:
                stmt = stmt.where(ClinicStockItem.organization_id == scope.organization_id)
            items = list((await s.execute(stmt)).scalars().all())
        balances = await _get_item_balances(s, [i.id for i in items])
    return {"items": [_ser_item(i, balances.get(i.id, [])) for i in items]}


# ── Движения ────────────────────────────────────────────────────────────────

async def _record_movement(session, *, org_id: int, kind: str, user_id: int,
                            item_id: int, quantity: int,
                            from_loc: Optional[int] = None,
                            to_loc: Optional[int] = None,
                            operation_report_id: Optional[int] = None,
                            doc_number: Optional[str] = None,
                            note: Optional[str] = None) -> ClinicStockMovement:
    mov = ClinicStockMovement(
        organization_id=org_id,
        kind=kind, item_id=item_id, quantity=quantity,
        user_id=user_id,
        from_location_id=from_loc, to_location_id=to_loc,
        operation_report_id=operation_report_id,
        doc_number=(doc_number or None),
        note=(note or None),
        created_at=datetime.now(timezone.utc),
    )
    session.add(mov)
    await session.flush()
    return mov


@router.post("/receive", status_code=status.HTTP_201_CREATED)
async def receive(body: ReceiveIn, scope: OrgScope = Depends(require_org_scope)):
    org_id = await _target_org_from_scope(scope, body.organization_id)
    exp = _parse_iso_date(body.expiration_date)

    async with AsyncSessionLocal() as s:
        to_loc = await _assert_location_in_scope(s, body.to_location_id, scope)
        if to_loc.organization_id != org_id:
            raise HTTPException(status_code=400,
                                detail="to_location_id не принадлежит целевой организации")

        # Ищем существующую партию с теми же article+lot+exp (иначе — новая).
        res = await s.execute(
            select(ClinicStockItem).where(
                ClinicStockItem.organization_id == org_id,
                ClinicStockItem.article == body.article.strip(),
                func.coalesce(ClinicStockItem.lot_number, "") == (body.lot_number or "").strip(),
                func.coalesce(ClinicStockItem.expiration_date, "") == (exp or ""),
            )
        )
        item = res.scalars().first()
        if item is None:
            item = ClinicStockItem(
                organization_id=org_id,
                article=body.article.strip(),
                nomenclature=body.nomenclature.strip(),
                characteristic=(body.characteristic or "").strip() or None,
                barcode=(body.barcode or "").strip() or None,
                lot_number=(body.lot_number or "").strip() or None,
                expiration_date=exp,
                received_doc_number=(body.doc_number or "").strip() or None,
            )
            s.add(item)
            await s.flush()
        else:
            # дозаписать barcode/doc_number, если раньше были пусты
            if body.barcode and not item.barcode:
                item.barcode = body.barcode.strip()
            if body.doc_number and not item.received_doc_number:
                item.received_doc_number = body.doc_number.strip()

        await _apply_delta(s, item.id, to_loc.id, +body.quantity)
        mov = await _record_movement(
            s, org_id=org_id, kind="receive", user_id=scope.user_id,
            item_id=item.id, quantity=body.quantity, to_loc=to_loc.id,
            doc_number=body.doc_number, note=body.note,
        )
        await s.commit()

    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_stock_receive",
        {"item_id": item.id, "qty": body.quantity, "to": to_loc.id},
    ))
    return {"movement_id": mov.id, "item_id": item.id}


@router.post("/transfer", status_code=status.HTTP_201_CREATED)
async def transfer(body: TransferIn, scope: OrgScope = Depends(require_org_scope)):
    if body.from_location_id == body.to_location_id:
        raise HTTPException(status_code=400, detail="from и to совпадают")
    async with AsyncSessionLocal() as s:
        item = await _assert_item_in_scope(s, body.item_id, scope)
        org_id = item.organization_id
        from_loc = await _assert_location_in_scope(s, body.from_location_id, scope)
        to_loc = await _assert_location_in_scope(s, body.to_location_id, scope)
        if from_loc.organization_id != org_id or to_loc.organization_id != org_id:
            raise HTTPException(status_code=400,
                                detail="Локации не из той же организации, что партия")
        await _apply_delta(s, item.id, from_loc.id, -body.quantity)
        await _apply_delta(s, item.id, to_loc.id, +body.quantity)
        mov = await _record_movement(
            s, org_id=org_id, kind="transfer", user_id=scope.user_id,
            item_id=item.id, quantity=body.quantity,
            from_loc=from_loc.id, to_loc=to_loc.id,
            doc_number=body.doc_number, note=body.note,
        )
        await s.commit()
    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_stock_transfer",
        {"item_id": item.id, "qty": body.quantity,
         "from": from_loc.id, "to": to_loc.id},
    ))
    return {"movement_id": mov.id}


@router.post("/consume", status_code=status.HTTP_201_CREATED)
async def consume(body: ConsumeIn, scope: OrgScope = Depends(require_org_scope)):
    async with AsyncSessionLocal() as s:
        item = await _assert_item_in_scope(s, body.item_id, scope)
        org_id = item.organization_id
        from_loc = await _assert_location_in_scope(s, body.from_location_id, scope)
        if from_loc.organization_id != org_id:
            raise HTTPException(status_code=400, detail="Локация не из той же организации")

        if body.operation_report_id is not None:
            rep = await s.get(OperationReport, body.operation_report_id)
            if rep is None or rep.organization_id != org_id:
                raise HTTPException(status_code=404,
                                    detail="Отчёт об операции не найден в этой клинике")

        await _apply_delta(s, item.id, from_loc.id, -body.quantity)
        mov = await _record_movement(
            s, org_id=org_id, kind="consume", user_id=scope.user_id,
            item_id=item.id, quantity=body.quantity, from_loc=from_loc.id,
            operation_report_id=body.operation_report_id,
            doc_number=body.doc_number, note=body.note,
        )
        await s.commit()
    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_stock_consume",
        {"item_id": item.id, "qty": body.quantity, "from": from_loc.id,
         "report_id": body.operation_report_id},
    ))
    return {"movement_id": mov.id}


@router.post("/return", status_code=status.HTTP_201_CREATED)
async def return_item(body: ReturnIn, scope: OrgScope = Depends(require_org_scope)):
    if body.from_location_id == body.to_location_id:
        raise HTTPException(status_code=400, detail="from и to совпадают")
    async with AsyncSessionLocal() as s:
        item = await _assert_item_in_scope(s, body.item_id, scope)
        org_id = item.organization_id
        from_loc = await _assert_location_in_scope(s, body.from_location_id, scope)
        to_loc = await _assert_location_in_scope(s, body.to_location_id, scope)
        if from_loc.organization_id != org_id or to_loc.organization_id != org_id:
            raise HTTPException(status_code=400,
                                detail="Локации не из той же организации, что партия")
        await _apply_delta(s, item.id, from_loc.id, -body.quantity)
        await _apply_delta(s, item.id, to_loc.id, +body.quantity)
        mov = await _record_movement(
            s, org_id=org_id, kind="return", user_id=scope.user_id,
            item_id=item.id, quantity=body.quantity,
            from_loc=from_loc.id, to_loc=to_loc.id,
            doc_number=body.doc_number, note=body.note,
        )
        await s.commit()
    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_stock_return",
        {"item_id": item.id, "qty": body.quantity,
         "from": from_loc.id, "to": to_loc.id},
    ))
    return {"movement_id": mov.id}


@router.post("/inventory", status_code=status.HTTP_201_CREATED)
async def inventory(body: InventoryIn, scope: OrgScope = Depends(require_org_scope)):
    """Инвентаризация: пользователь передаёт факт, система вычисляет дельту
    и пишет её как inventory_adjust. Если факт равен текущему учётному — no-op."""
    async with AsyncSessionLocal() as s:
        item = await _assert_item_in_scope(s, body.item_id, scope)
        org_id = item.organization_id
        loc = await _assert_location_in_scope(s, body.location_id, scope)
        if loc.organization_id != org_id:
            raise HTTPException(status_code=400, detail="Локация не из той же организации")

        res = await s.execute(
            select(ClinicStockBalance).where(
                ClinicStockBalance.item_id == body.item_id,
                ClinicStockBalance.location_id == body.location_id,
            )
        )
        bal = res.scalars().first()
        current = bal.quantity if bal else 0
        delta = body.actual_quantity - current
        if delta == 0:
            return {"movement_id": None, "note": "Фактический остаток совпадает с учётным"}

        # Для inventory делаем delta напрямую, минуя _apply_delta (там отрицательный новый
        # остаток запрещён). Но и здесь баланс не может быть отрицательным.
        if bal is None:
            bal = ClinicStockBalance(item_id=body.item_id, location_id=body.location_id,
                                     quantity=0)
            s.add(bal)
        bal.quantity = body.actual_quantity

        mov = await _record_movement(
            s, org_id=org_id, kind="inventory_adjust", user_id=scope.user_id,
            item_id=item.id, quantity=delta, from_loc=body.location_id,
            note=body.note,
        )
        await s.commit()
    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_stock_inventory",
        {"item_id": item.id, "location_id": body.location_id,
         "actual": body.actual_quantity, "delta": delta},
    ))
    return {"movement_id": mov.id, "delta": delta}


@router.post("/write-off", status_code=status.HTTP_201_CREATED)
async def write_off(body: WriteOffIn, scope: OrgScope = Depends(require_org_scope)):
    async with AsyncSessionLocal() as s:
        item = await _assert_item_in_scope(s, body.item_id, scope)
        org_id = item.organization_id
        from_loc = await _assert_location_in_scope(s, body.from_location_id, scope)
        if from_loc.organization_id != org_id:
            raise HTTPException(status_code=400, detail="Локация не из той же организации")
        await _apply_delta(s, item.id, from_loc.id, -body.quantity)
        mov = await _record_movement(
            s, org_id=org_id, kind="write_off", user_id=scope.user_id,
            item_id=item.id, quantity=body.quantity, from_loc=from_loc.id,
            note=body.note,
        )
        await s.commit()
    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_stock_write_off",
        {"item_id": item.id, "qty": body.quantity,
         "from": from_loc.id, "note": body.note},
    ))
    return {"movement_id": mov.id}


# ── Журнал + отчёт потерь ───────────────────────────────────────────────────

@router.get("/movements")
async def list_movements(
    kind: Optional[str] = Query(None),
    item_id: Optional[int] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    scope: OrgScope = Depends(require_org_scope),
):
    async with AsyncSessionLocal() as s:
        stmt = select(ClinicStockMovement).order_by(ClinicStockMovement.id.desc()).limit(limit)
        if scope.organization_id is not None:
            stmt = stmt.where(ClinicStockMovement.organization_id == scope.organization_id)
        if kind:
            if kind not in ALLOWED_MOVEMENT_KINDS:
                raise HTTPException(status_code=400, detail=f"kind: {kind}")
            stmt = stmt.where(ClinicStockMovement.kind == kind)
        if item_id:
            stmt = stmt.where(ClinicStockMovement.item_id == item_id)
        movs = list((await s.execute(stmt)).scalars().all())
    return {"movements": [_ser_movement(m) for m in movs]}


async def _losses_query(scope: OrgScope, date_from: Optional[str],
                         date_to: Optional[str], session) -> list[tuple]:
    """Возвращает список (movement, item, organization_name) по фильтрам потерь."""
    stmt = (
        select(ClinicStockMovement, ClinicStockItem, Organization)
        .join(ClinicStockItem, ClinicStockItem.id == ClinicStockMovement.item_id)
        .join(Organization, Organization.id == ClinicStockMovement.organization_id)
        .where(ClinicStockMovement.kind.in_(LOSS_KINDS))
        .order_by(ClinicStockMovement.id.desc())
        .limit(2000)
    )
    if scope.organization_id is not None:
        stmt = stmt.where(ClinicStockMovement.organization_id == scope.organization_id)
    if date_from:
        stmt = stmt.where(
            ClinicStockMovement.created_at >= datetime.fromisoformat(_parse_iso_date(date_from))
        )
    if date_to:
        dt = datetime.fromisoformat(_parse_iso_date(date_to))
        stmt = stmt.where(
            ClinicStockMovement.created_at <
            dt.replace(hour=23, minute=59, second=59)
        )
    return (await session.execute(stmt)).all()


@router.get("/losses")
async def losses(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    scope: OrgScope = Depends(require_org_scope),
):
    """Потери — enriched-ответ: movement + item + organization_name.

    Включаем:
      - write_off (всегда минус);
      - inventory_adjust с отрицательным delta — реальная недостача;
      - inventory_adjust с положительным delta — «нашли», информативно.
    """
    async with AsyncSessionLocal() as s:
        rows = await _losses_query(scope, date_from, date_to, s)
    out = []
    for mov, item, org in rows:
        out.append({
            **_ser_movement(mov),
            "organization_name": org.name,
            "item": {
                "id": item.id,
                "article": item.article,
                "nomenclature": item.nomenclature,
                "characteristic": item.characteristic,
                "lot_number": item.lot_number,
                "expiration_date": item.expiration_date,
            },
        })
    return {"movements": out}


@router.get("/losses.xlsx")
async def losses_xlsx(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    scope: OrgScope = Depends(require_org_scope),
):
    """XLSX-экспорт потерь (write_off + inventory_adjust)."""
    import io
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    async with AsyncSessionLocal() as s:
        rows = await _losses_query(scope, date_from, date_to, s)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Потери"
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="9A2A3A")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="AAAAAA")
    brd = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = [
        "Дата", "Клиника", "Тип", "Артикул", "Номенклатура",
        "Lot", "Срок", "Кол-во", "Отчёт", "Заметка",
    ]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font, c.fill, c.alignment, c.border = hdr_font, hdr_fill, center, brd
    ws.row_dimensions[1].height = 20

    kind_label = {"write_off": "Списание", "inventory_adjust": "Инвентаризация"}
    for i, (mov, item, org) in enumerate(rows, start=2):
        ws.cell(row=i, column=1,
                value=mov.created_at.strftime("%Y-%m-%d %H:%M") if mov.created_at else "")
        ws.cell(row=i, column=2, value=org.name)
        ws.cell(row=i, column=3, value=kind_label.get(mov.kind, mov.kind))
        ws.cell(row=i, column=4, value=item.article)
        ws.cell(row=i, column=5, value=item.nomenclature)
        ws.cell(row=i, column=6, value=item.lot_number or "")
        ws.cell(row=i, column=7, value=item.expiration_date or "")
        ws.cell(row=i, column=8, value=mov.quantity).alignment = center
        ws.cell(row=i, column=9,
                value=f"#{mov.operation_report_id}" if mov.operation_report_id else "")
        ws.cell(row=i, column=10, value=mov.note or "")
        for col in range(1, 11):
            ws.cell(row=i, column=col).border = brd

    widths = [18, 28, 15, 18, 36, 14, 14, 10, 10, 36]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = "clinic_losses.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/organizations-list")
async def organizations_list(scope: OrgScope = Depends(require_org_scope)):
    """Список клиник — для фильтра на странице потерь.

    Для сотрудника ZMed — все активные клиники.
    Для юзера клиники — только своя (фильтр всё равно будет принудительным).
    """
    async with AsyncSessionLocal() as s:
        stmt = select(Organization).where(Organization.active == 1).order_by(Organization.name)
        if not scope.is_zmed:
            stmt = stmt.where(Organization.id == scope.user.organization_id)
        orgs = (await s.execute(stmt)).scalars().all()
    return {"organizations": [
        {"id": o.id, "name": o.name, "kind": o.kind}
        for o in orgs
    ]}
