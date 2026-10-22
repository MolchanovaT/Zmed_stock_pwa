"""
app/api/clinic_reports.py

Модуль «Отчёты клиник об операциях» (modules.clinic_reports).

Эндпоинты:
  GET    /api/clinic-reports                       — список с фильтрами (RLS)
  POST   /api/clinic-reports                       — создать draft
  GET    /api/clinic-reports/{id}                  — один отчёт + файлы
  PATCH  /api/clinic-reports/{id}                  — обновить (draft или submit)
  DELETE /api/clinic-reports/{id}                  — удалить (draft; ZMed может любой)
  POST   /api/clinic-reports/{id}/files            — загрузить файл (multipart)
  GET    /api/clinic-reports/{id}/files/{file_id}  — скачать файл
  DELETE /api/clinic-reports/{id}/files/{file_id}  — удалить файл

Правила доступа (RLS, см. app.api.scoping):
  - Юзер клиники: видит и правит отчёты своей организации.
  - ZMed-staff:   видит все клиники; при создании должен передать
                   organization_id явно.
  - draft редактирует только автор (или ZMed); submitted — read-only для автора.

Файлы:
  Хранятся в <DATA_DIR>/reports/<year>/<month>/<report_id>_<uuid>.<ext>.
  Отдаются только через этот модуль с проверкой доступа — не через StaticFiles.
"""

import asyncio
import json
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, Query, UploadFile, status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.activity import log_activity
from app.api.auth import get_current_user
from app.api.scoping import (
    OrgScope, require_org_scope, resolve_target_org_id,
)
from app.db.models import OperationReport, OperationReportFile, User
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/clinic-reports", tags=["clinic_reports"])

# ── Константы ────────────────────────────────────────────────────────────────

ALLOWED_STATUSES = {"draft", "submitted"}
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/pjpeg", "image/png", "image/webp",
    "image/heic", "image/heif", "application/pdf",
}
MAX_FILE_BYTES = 20 * 1024 * 1024   # 20 МБ на файл
MAX_FILES_PER_REPORT = 10

# Папка-корень под файлы отчётов. По умолчанию внутри PWA-репо (data/reports/),
# на проде `data/` замаплен на /root/zmed_pwa/data через bind-mount.
_DATA_DIR = Path(os.getenv("REPORTS_DIR") or
                 Path(__file__).resolve().parent.parent.parent / "data" / "reports")

# UI-подсказка: разрешаем patient_code до 32 символов.
_PATIENT_CODE_RE = re.compile(r"^.{1,32}$")

# МКБ-10 / «похожесть на ФИО» — не блокируем, только мягко предупреждаем в UI.


# ── Pydantic ─────────────────────────────────────────────────────────────────

class ImplantUsed(BaseModel):
    article: str = ""
    nomenclature: str = ""
    qty: int = Field(1, ge=1)
    lot_number: str = ""
    serial: str = ""


class ReportCreate(BaseModel):
    organization_id: Optional[int] = None  # обязателен только для ZMed-staff
    patient_code: str = Field(..., min_length=1, max_length=32)
    operation_date: str                                    # YYYY-MM-DD
    department: Optional[str] = Field(None, max_length=100)
    doctor_name: str = Field(..., min_length=1, max_length=100)
    operation_type: str = Field(..., min_length=1, max_length=200)
    diagnosis_text: Optional[str] = Field(None, max_length=500)
    implants_used: list[ImplantUsed] = []
    complications: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)
    status: str = "draft"


class ReportPatch(BaseModel):
    patient_code: Optional[str] = Field(None, min_length=1, max_length=32)
    operation_date: Optional[str] = None
    department: Optional[str] = Field(None, max_length=100)
    doctor_name: Optional[str] = Field(None, max_length=100)
    operation_type: Optional[str] = Field(None, max_length=200)
    diagnosis_text: Optional[str] = Field(None, max_length=500)
    implants_used: Optional[list[ImplantUsed]] = None
    complications: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_iso_date(s: str) -> str:
    """Валидирует YYYY-MM-DD, возвращает её же (строкой) — так хранится в БД."""
    try:
        date.fromisoformat(s)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"operation_date должна быть в формате YYYY-MM-DD, получено: {s!r}",
        )
    return s


def _ensure_access_to_report(report: OperationReport, scope: OrgScope) -> None:
    """Проверка: пользователь может видеть этот отчёт."""
    if report is None:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    if scope.is_zmed:
        if scope.organization_id is not None and report.organization_id != scope.organization_id:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        return
    if report.organization_id != scope.user.organization_id:
        raise HTTPException(status_code=404, detail="Отчёт не найден")


def _ensure_can_edit(report: OperationReport, scope: OrgScope) -> None:
    """Проверка: пользователь может редактировать этот отчёт.

    Правила:
      - ZMed-staff — всегда может.
      - Автор draft — может.
      - Автор submitted — нет (отчёт считается подписанным).
      - Не-автор клинический юзер — нет.
    """
    _ensure_access_to_report(report, scope)
    if scope.is_zmed:
        return
    if report.user_id != scope.user_id:
        raise HTTPException(status_code=403, detail="Чужой отчёт не редактируется")
    if report.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Отправленный отчёт нельзя редактировать",
        )


def _serialize_report(report: OperationReport, files: list[OperationReportFile]) -> dict:
    return {
        "id": report.id,
        "organization_id": report.organization_id,
        "user_id": report.user_id,
        "patient_code": report.patient_code,
        "operation_date": report.operation_date,
        "department": report.department,
        "doctor_name": report.doctor_name,
        "operation_type": report.operation_type,
        "diagnosis_text": report.diagnosis_text,
        "implants_used": json.loads(report.implants_used_json) if report.implants_used_json else [],
        "complications": report.complications,
        "notes": report.notes,
        "status": report.status,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        "files": [
            {
                "id": f.id,
                "original_name": f.original_name,
                "content_type": f.content_type,
                "size_bytes": f.size_bytes,
                "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
            }
            for f in files
        ],
    }


def _storage_path_for(report_id: int, orig_name: str) -> tuple[Path, str]:
    """Строит путь на диске и относительный путь (для хранения в БД)."""
    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    month = now.strftime("%m")
    ext = Path(orig_name or "").suffix.lower()
    # Белый список расширений — защита от произвольных расширений в имени
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"}:
        ext = ".bin"
    safe = f"{report_id}_{uuid.uuid4().hex}{ext}"
    rel_path = f"{year}/{month}/{safe}"
    disk_path = _DATA_DIR / rel_path
    return disk_path, rel_path


# ── Эндпоинты ────────────────────────────────────────────────────────────────

@router.get("")
async def list_reports(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    scope: OrgScope = Depends(require_org_scope),
):
    """Список отчётов с фильтрами и RLS."""
    async with AsyncSessionLocal() as s:
        stmt = select(OperationReport).order_by(
            OperationReport.operation_date.desc(),
            OperationReport.id.desc(),
        ).limit(limit)

        if scope.organization_id is not None:
            stmt = stmt.where(OperationReport.organization_id == scope.organization_id)
        if date_from:
            stmt = stmt.where(OperationReport.operation_date >= _parse_iso_date(date_from))
        if date_to:
            stmt = stmt.where(OperationReport.operation_date <= _parse_iso_date(date_to))
        if status_filter:
            if status_filter not in ALLOWED_STATUSES:
                raise HTTPException(status_code=400, detail=f"Неизвестный status: {status_filter}")
            stmt = stmt.where(OperationReport.status == status_filter)

        reports = list((await s.execute(stmt)).scalars().all())

        # Файлы одним запросом
        files_by_report: dict[int, list[OperationReportFile]] = {}
        if reports:
            files_res = await s.execute(
                select(OperationReportFile)
                .where(OperationReportFile.report_id.in_([r.id for r in reports]))
                .order_by(OperationReportFile.id)
            )
            for f in files_res.scalars().all():
                files_by_report.setdefault(f.report_id, []).append(f)

    return {"reports": [_serialize_report(r, files_by_report.get(r.id, [])) for r in reports]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_report(
    body: ReportCreate,
    scope: OrgScope = Depends(require_org_scope),
):
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Неизвестный status: {body.status}")

    op_date = _parse_iso_date(body.operation_date)
    target_org_id = await resolve_target_org_id(scope, body.organization_id)

    now = datetime.now(timezone.utc)
    report = OperationReport(
        organization_id=target_org_id,
        user_id=scope.user_id,
        patient_code=body.patient_code.strip(),
        operation_date=op_date,
        department=(body.department or "").strip() or None,
        doctor_name=body.doctor_name.strip(),
        operation_type=body.operation_type.strip(),
        diagnosis_text=(body.diagnosis_text or "").strip() or None,
        implants_used_json=json.dumps(
            [i.model_dump() for i in body.implants_used], ensure_ascii=False
        ) if body.implants_used else None,
        complications=(body.complications or "").strip() or None,
        notes=(body.notes or "").strip() or None,
        status=body.status,
        created_at=now,
        submitted_at=now if body.status == "submitted" else None,
    )
    async with AsyncSessionLocal() as s:
        s.add(report)
        await s.commit()
        await s.refresh(report)

    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_report_create",
        {"report_id": report.id, "status": report.status,
         "organization_id": target_org_id},
    ))
    return _serialize_report(report, [])


@router.get("/{report_id}")
async def get_report(
    report_id: int,
    scope: OrgScope = Depends(require_org_scope),
):
    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_access_to_report(report, scope)
        files_res = await s.execute(
            select(OperationReportFile)
            .where(OperationReportFile.report_id == report_id)
            .order_by(OperationReportFile.id)
        )
        files = list(files_res.scalars().all())
    return _serialize_report(report, files)


@router.patch("/{report_id}")
async def patch_report(
    report_id: int,
    body: ReportPatch,
    scope: OrgScope = Depends(require_org_scope),
):
    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_can_edit(report, scope)

        if body.operation_date is not None:
            report.operation_date = _parse_iso_date(body.operation_date)
        if body.patient_code is not None:
            report.patient_code = body.patient_code.strip()
        if body.department is not None:
            report.department = body.department.strip() or None
        if body.doctor_name is not None:
            report.doctor_name = body.doctor_name.strip()
        if body.operation_type is not None:
            report.operation_type = body.operation_type.strip()
        if body.diagnosis_text is not None:
            report.diagnosis_text = body.diagnosis_text.strip() or None
        if body.complications is not None:
            report.complications = body.complications.strip() or None
        if body.notes is not None:
            report.notes = body.notes.strip() or None
        if body.implants_used is not None:
            report.implants_used_json = json.dumps(
                [i.model_dump() for i in body.implants_used], ensure_ascii=False
            ) if body.implants_used else None

        if body.status is not None:
            if body.status not in ALLOWED_STATUSES:
                raise HTTPException(status_code=400, detail=f"Неизвестный status: {body.status}")
            if body.status == "submitted" and report.status == "draft":
                report.submitted_at = datetime.now(timezone.utc)
            report.status = body.status

        s.add(report)
        await s.commit()
        await s.refresh(report)

        files_res = await s.execute(
            select(OperationReportFile)
            .where(OperationReportFile.report_id == report_id)
            .order_by(OperationReportFile.id)
        )
        files = list(files_res.scalars().all())

    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_report_update",
        {"report_id": report.id, "status": report.status},
    ))
    return _serialize_report(report, files)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int,
    scope: OrgScope = Depends(require_org_scope),
):
    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_access_to_report(report, scope)
        # Клинический юзер — только свои драфты
        if not scope.is_zmed and (report.user_id != scope.user_id
                                   or report.status != "draft"):
            raise HTTPException(status_code=403, detail="Нельзя удалить этот отчёт")

        # Снести файлы на диске
        files_res = await s.execute(
            select(OperationReportFile).where(OperationReportFile.report_id == report_id)
        )
        for f in files_res.scalars().all():
            try:
                (_DATA_DIR / f.stored_path).unlink(missing_ok=True)
            except Exception:
                pass

        await s.execute(
            delete(OperationReportFile).where(OperationReportFile.report_id == report_id)
        )
        await s.delete(report)
        await s.commit()


# ── Файлы ───────────────────────────────────────────────────────────────────

@router.post("/{report_id}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    report_id: int,
    file: UploadFile = File(...),
    scope: OrgScope = Depends(require_org_scope),
):
    """Загрузка одного файла (multipart). До 10 файлов на отчёт, 20 МБ каждый."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Тип файла не поддерживается: {file.content_type!r}. "
                   "Разрешены JPG, PNG, WEBP, HEIC, PDF.",
        )

    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_can_edit(report, scope)

        count_res = await s.execute(
            select(OperationReportFile.id).where(OperationReportFile.report_id == report_id)
        )
        if len(count_res.all()) >= MAX_FILES_PER_REPORT:
            raise HTTPException(
                status_code=409,
                detail=f"Можно прикрепить не более {MAX_FILES_PER_REPORT} файлов",
            )

        # Читаем с ограничением
        data = await file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Файл больше {MAX_FILE_BYTES // (1024*1024)} МБ",
            )

        disk_path, rel_path = _storage_path_for(report_id, file.filename or "file.bin")
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_bytes(data)

        rec = OperationReportFile(
            report_id=report_id,
            stored_path=rel_path,
            original_name=file.filename,
            content_type=file.content_type,
            size_bytes=len(data),
        )
        s.add(rec)
        await s.commit()
        await s.refresh(rec)

    return {
        "id": rec.id,
        "original_name": rec.original_name,
        "content_type": rec.content_type,
        "size_bytes": rec.size_bytes,
        "uploaded_at": rec.uploaded_at.isoformat() if rec.uploaded_at else None,
    }


@router.get("/{report_id}/files/{file_id}")
async def download_file(
    report_id: int,
    file_id: int,
    scope: OrgScope = Depends(require_org_scope),
):
    """Отдаёт файл с проверкой доступа. Прямого StaticFiles НЕТ — только через этот эндпоинт."""
    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_access_to_report(report, scope)
        rec = await s.get(OperationReportFile, file_id)
        if rec is None or rec.report_id != report_id:
            raise HTTPException(status_code=404, detail="Файл не найден")

    disk_path = _DATA_DIR / rec.stored_path
    if not disk_path.exists():
        raise HTTPException(status_code=410, detail="Файл утрачен на диске")

    return FileResponse(
        str(disk_path),
        media_type=rec.content_type or "application/octet-stream",
        filename=rec.original_name or f"file_{rec.id}",
    )


@router.delete("/{report_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    report_id: int,
    file_id: int,
    scope: OrgScope = Depends(require_org_scope),
):
    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_can_edit(report, scope)
        rec = await s.get(OperationReportFile, file_id)
        if rec is None or rec.report_id != report_id:
            raise HTTPException(status_code=404, detail="Файл не найден")

        try:
            (_DATA_DIR / rec.stored_path).unlink(missing_ok=True)
        except Exception:
            pass

        await s.delete(rec)
        await s.commit()


# ── Авто-подсказки (автокомплит) ─────────────────────────────────────────────

@router.get("/suggest/doctors")
async def suggest_doctors(
    q: str = Query("", min_length=0, max_length=100),
    scope: OrgScope = Depends(require_org_scope),
):
    """Уже введённые ФИО врачей (для автокомплита). Для текущей организации."""
    async with AsyncSessionLocal() as s:
        stmt = select(OperationReport.doctor_name).distinct()
        if scope.organization_id is not None:
            stmt = stmt.where(OperationReport.organization_id == scope.organization_id)
        if q:
            stmt = stmt.where(OperationReport.doctor_name.ilike(f"%{q}%"))
        rows = (await s.execute(stmt.limit(50))).all()
    return {"items": sorted({r[0] for r in rows if r[0]})}


@router.get("/suggest/operation-types")
async def suggest_operation_types(
    q: str = Query("", min_length=0, max_length=100),
    scope: OrgScope = Depends(require_org_scope),
):
    """Уже введённые типы операций (общий автокомплит по всем клиникам)."""
    async with AsyncSessionLocal() as s:
        stmt = select(OperationReport.operation_type).distinct()
        if q:
            stmt = stmt.where(OperationReport.operation_type.ilike(f"%{q}%"))
        rows = (await s.execute(stmt.limit(50))).all()
    return {"items": sorted({r[0] for r in rows if r[0]})}
