"""
app/api/scoping.py

Row-level security для клинических модулей (clinic_reports, clinic_stock).

Логика:
  - Сотрудник ZMed (organization.kind='zmed') видит данные всех клиник;
    может опционально фильтровать по ?organization_id=<id>.
  - Юзер клиники видит ТОЛЬКО свою organization_id — параметр запроса
    игнорируется (чтобы нельзя было подменой руками «подсмотреть» чужое).
  - Юзер без organization_id вообще не может работать с клиническими
    модулями: 403.

Применяется как FastAPI-dependency во всех эндпоинтах клинических модулей.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.auth import get_current_user
from app.db.models import Organization, User
from app.db.session import AsyncSessionLocal


class OrgScope:
    """Контекст запрашивающего пользователя для клинических модулей.

    organization_id — id, по которому фильтруются выборки:
      * у юзера клиники — всегда его собственный org_id;
      * у сотрудника ZMed — None (без фильтра), либо явно переданный
        ?organization_id= для просмотра одной конкретной клиники.
    is_zmed — True, если пользователь принадлежит организации ZMed.
    user_id — id запрашивающего (для записи авторства).
    user — сам объект User (на случай когда нужны email/full_name).
    """

    __slots__ = ("organization_id", "is_zmed", "user_id", "user")

    def __init__(self, *, organization_id: Optional[int], is_zmed: bool,
                 user: User):
        self.organization_id = organization_id
        self.is_zmed = is_zmed
        self.user_id = user.id
        self.user = user


async def require_org_scope(
    organization_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
) -> OrgScope:
    """FastAPI-dependency: возвращает OrgScope.

    Если у пользователя нет organization_id — 403 (клинические модули
    требуют принадлежности к организации).

    Если пользователь не из ZMed, но передал ?organization_id — параметр
    игнорируется и подменяется на его собственный organization_id.
    """
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь не привязан к организации",
        )

    async with AsyncSessionLocal() as s:
        org = await s.get(Organization, current_user.organization_id)

    if org is None or not org.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Организация пользователя не найдена или деактивирована",
        )

    is_zmed = (org.kind == "zmed")

    if is_zmed:
        # Сотрудник ZMed: без фильтра = видит все клиники;
        # с ?organization_id= = одна конкретная клиника.
        scoped_id = organization_id
    else:
        # Юзер клиники: всегда только своя организация.
        scoped_id = current_user.organization_id

    return OrgScope(
        organization_id=scoped_id,
        is_zmed=is_zmed,
        user=current_user,
    )


async def resolve_target_org_id(scope: OrgScope,
                                 explicit_org_id: Optional[int] = None) -> int:
    """Для операций записи (POST/PATCH): определить, в чью organization_id
    пишем новый ресурс.

    - Юзер клиники: всегда своя (переданный аргумент игнорируется).
    - Сотрудник ZMed: обязан явно передать organization_id (нельзя создать
      «ничей» ресурс), иначе 400.
    """
    if not scope.is_zmed:
        return scope.user.organization_id

    if explicit_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для сотрудника ZMed нужно указать organization_id",
        )

    async with AsyncSessionLocal() as s:
        org = await s.get(Organization, explicit_org_id)
    if org is None or not org.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Организация id={explicit_org_id} не найдена или неактивна",
        )
    return explicit_org_id
