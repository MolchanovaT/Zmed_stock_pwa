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
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.activity import log_activity
from app.api.auth import get_current_user
from app.api.email_report import send_report_notification
from app.api.otp import consume_otp
from app.api.rate_limit import upload_rate_limit
from app.config import OTP_REQUIRED_FOR_SUBMIT
from app.api.scoping import (
    OrgScope, require_org_scope, resolve_target_org_id,
)
from app.api.tg_notify import send_report_tg_notification
from app.db.models import (
    Organization, OperationReport, OperationReportAudit, OperationReportFile,
    User,
)
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
    # OTP для подписания (требуется только если OTP_REQUIRED_FOR_SUBMIT=1
    # и status='submitted')
    otp_code: Optional[str] = Field(None, max_length=12)


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
    # OTP для подписания (требуется только если OTP_REQUIRED_FOR_SUBMIT=1
    # и status меняется на 'submitted' из draft)
    otp_code: Optional[str] = Field(None, max_length=12)


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


def _snapshot(report: OperationReport) -> dict:
    """Снимок OperationReport для audit log."""
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
        "implants_used_json": report.implants_used_json,
        "complications": report.complications,
        "notes": report.notes,
        "status": report.status,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
    }


async def _audit(session, report: OperationReport, scope: OrgScope,
                  action: str, note: Optional[str] = None) -> None:
    session.add(OperationReportAudit(
        report_id=report.id,
        organization_id=report.organization_id,
        action=action,
        user_id=scope.user_id,
        snapshot_json=json.dumps(_snapshot(report), ensure_ascii=False),
        note=note,
    ))


async def _notify_submitted(report: OperationReport, scope: OrgScope,
                             files_count: int) -> None:
    """Email + TG-уведомления ZMed о submitted-отчёте. Fire-and-forget."""
    async with AsyncSessionLocal() as s:
        org = await s.get(Organization, report.organization_id)
    org_name = org.name if org else f"org#{report.organization_id}"
    asyncio.create_task(send_report_notification(
        report_id=report.id,
        organization_name=org_name,
        patient_code=report.patient_code,
        operation_date=report.operation_date,
        department=report.department or "",
        doctor_name=report.doctor_name,
        operation_type=report.operation_type,
        diagnosis_text=report.diagnosis_text or "",
        implants_used_json=report.implants_used_json or "",
        complications=report.complications or "",
        notes=report.notes or "",
        files_count=files_count,
        submitted_by=scope.user.username or (scope.user.full_name or f"user:{scope.user_id}"),
        submitted_at=(report.submitted_at.isoformat() if report.submitted_at else ""),
    ))
    asyncio.create_task(send_report_tg_notification(
        report_id=report.id,
        organization_name=org_name,
        operation_date=report.operation_date,
        operation_type=report.operation_type,
        patient_code=report.patient_code,
        doctor_name=report.doctor_name,
        files_count=files_count,
    ))


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


def _safe_disk_path(stored_path: str) -> Path:
    """Защита от path-traversal: отдаём абсолютный путь ТОЛЬКО если он лежит
    внутри _DATA_DIR. Любой `..` или абсолютный путь в БД → 400.

    Параноично: защита от компрометации stored_path (напр. через SQL
    injection или ошибку в миграции).
    """
    base = _DATA_DIR.resolve()
    # Запрещаем абсолютные пути сразу
    p = Path(stored_path)
    if p.is_absolute() or ".." in p.parts:
        raise HTTPException(status_code=400, detail="Некорректный путь файла")
    full = (base / p).resolve()
    try:
        full.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный путь файла")
    return full


# ── Эндпоинты ────────────────────────────────────────────────────────────────

@router.get("")
async def list_reports(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    scope: OrgScope = Depends(require_org_scope),
):
    """Список отчётов с фильтрами, RLS и пагинацией.

    Возвращает:
      reports — страница результата;
      total   — всего строк, подходящих под фильтры (для прогресса в UI);
      limit, offset — эхо параметров.
    """
    from sqlalchemy import func as _f

    def _apply_filters(stmt):
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
        return stmt

    async with AsyncSessionLocal() as s:
        count_stmt = _apply_filters(select(_f.count(OperationReport.id)))
        total = (await s.execute(count_stmt)).scalar_one()

        stmt = _apply_filters(select(OperationReport)).order_by(
            OperationReport.operation_date.desc(),
            OperationReport.id.desc(),
        ).limit(limit).offset(offset)

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

    return {
        "reports": [_serialize_report(r, files_by_report.get(r.id, [])) for r in reports],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_report(
    body: ReportCreate,
    scope: OrgScope = Depends(require_org_scope),
):
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"Неизвестный status: {body.status}")

    op_date = _parse_iso_date(body.operation_date)
    target_org_id = await resolve_target_org_id(scope, body.organization_id)

    # OTP при сразу-submitted (клинический юзер; ZMed пропускаем)
    if (body.status == "submitted"
            and OTP_REQUIRED_FOR_SUBMIT
            and not scope.is_zmed):
        # purpose привязываем к target_org_id (отчёта ещё нет)
        await consume_otp(scope.user, f"report_submit_new:{target_org_id}",
                           body.otp_code or "")

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
        if report.status == "submitted":
            await _audit(s, report, scope, "submit")
            await s.commit()

    asyncio.create_task(log_activity(
        scope.user_id, scope.user.username or f"user:{scope.user_id}",
        "clinic_report_create",
        {"report_id": report.id, "status": report.status,
         "organization_id": target_org_id},
    ))
    if report.status == "submitted":
        await _notify_submitted(report, scope, files_count=0)
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

        was_submitted_before = (report.status == "submitted")
        just_submitted = False
        if body.status is not None:
            if body.status not in ALLOWED_STATUSES:
                raise HTTPException(status_code=400, detail=f"Неизвестный status: {body.status}")
            if body.status == "submitted" and report.status == "draft":
                # OTP: требуется только клинике, не ZMed
                if OTP_REQUIRED_FOR_SUBMIT and not scope.is_zmed:
                    await consume_otp(scope.user,
                                       f"report_submit:{report.id}",
                                       body.otp_code or "")
                report.submitted_at = datetime.now(timezone.utc)
                just_submitted = True
            report.status = body.status

        s.add(report)
        await s.commit()
        await s.refresh(report)

        # Audit: submit — всегда; edit submitted — если ZMed правил уже отправленный
        if just_submitted:
            await _audit(s, report, scope, "submit")
            await s.commit()
        elif was_submitted_before and scope.is_zmed:
            await _audit(s, report, scope, "edit_after_submit",
                          note=(body.notes or body.complications or None))
            await s.commit()

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
    if just_submitted:
        await _notify_submitted(report, scope, files_count=len(files))
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

        # Audit: удаление submitted отчёта (только ZMed такое может по правилам
        # _ensure_can_edit, но проверим снова для надёжности).
        if report.status == "submitted":
            await _audit(s, report, scope, "delete_submitted")
            await s.flush()

        # Снести файлы на диске (с защитой от path-traversal в stored_path)
        files_res = await s.execute(
            select(OperationReportFile).where(OperationReportFile.report_id == report_id)
        )
        for f in files_res.scalars().all():
            try:
                safe = _safe_disk_path(f.stored_path)
                safe.unlink(missing_ok=True)
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
    _rl: None = Depends(upload_rate_limit),
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

    disk_path = _safe_disk_path(rec.stored_path)
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
            safe = _safe_disk_path(rec.stored_path)
            safe.unlink(missing_ok=True)
        except Exception:
            pass

        await s.delete(rec)
        await s.commit()


# ── Audit log ───────────────────────────────────────────────────────────────

@router.get("/{report_id}/audit")
async def get_audit(
    report_id: int,
    scope: OrgScope = Depends(require_org_scope),
):
    """История действий над отчётом (submit / edit_after_submit / delete).

    Виден и клинике (свои отчёты), и ZMed (все).
    """
    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_access_to_report(report, scope)
        res = await s.execute(
            select(OperationReportAudit)
            .where(OperationReportAudit.report_id == report_id)
            .order_by(OperationReportAudit.id.desc())
        )
        entries = list(res.scalars().all())
        # Подтянем username'ы
        user_ids = {e.user_id for e in entries}
        users_map = {}
        if user_ids:
            u_res = await s.execute(select(User).where(User.id.in_(user_ids)))
            users_map = {u.id: u for u in u_res.scalars().all()}
    out = []
    for e in entries:
        u = users_map.get(e.user_id)
        out.append({
            "id": e.id,
            "action": e.action,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "user_id": e.user_id,
            "user_name": (u.username if u else None) or (u.full_name if u else None),
            "note": e.note,
            # snapshot возвращаем парсеным — удобнее на фронте
            "snapshot": (
                json.loads(e.snapshot_json) if e.snapshot_json else None
            ),
        })
    return {"entries": out}


# ── PDF-экспорт одного отчёта ───────────────────────────────────────────────

# Регистрируем шрифты один раз при импорте модуля (как в stock.py)
_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
try:
    from reportlab.pdfbase import pdfmetrics as _pdfm
    from reportlab.pdfbase.ttfonts import TTFont as _TTFont
    _pdfm.registerFont(_TTFont("DejaVuSans", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
    _pdfm.registerFont(_TTFont("DejaVuSans-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
except Exception:
    pass


@router.get("/{report_id}.pdf")
async def report_pdf(
    report_id: int,
    scope: OrgScope = Depends(require_org_scope),
):
    """PDF одного отчёта. Доступ — с теми же правилами, что GET /{id}."""
    import io
    from datetime import datetime as _dt
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    async with AsyncSessionLocal() as s:
        report = await s.get(OperationReport, report_id)
        _ensure_access_to_report(report, scope)
        org = await s.get(Organization, report.organization_id)
        files_res = await s.execute(
            select(OperationReportFile)
            .where(OperationReportFile.report_id == report_id)
            .order_by(OperationReportFile.id)
        )
        files = list(files_res.scalars().all())

    try:
        implants = json.loads(report.implants_used_json) if report.implants_used_json else []
    except (ValueError, TypeError):
        implants = []

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=36, rightMargin=36,
                             topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(name="N", parent=styles["Normal"],
                             fontName="DejaVuSans", fontSize=10, leading=14)
    bold = ParagraphStyle(name="B", parent=styles["Normal"],
                           fontName="DejaVuSans-Bold", fontSize=13, leading=16)
    h1 = ParagraphStyle(name="H1", parent=styles["Normal"],
                         fontName="DejaVuSans-Bold", fontSize=16, leading=20,
                         textColor=rl_colors.HexColor("#9a2a3a"))
    small = ParagraphStyle(name="S", parent=styles["Normal"],
                            fontName="DejaVuSans", fontSize=8, leading=11,
                            textColor=rl_colors.grey)

    status_label = {"draft": "Черновик", "submitted": "Отправлен"}
    story: list = [
        Paragraph(f"Отчёт об операции #{report_id}", h1),
        Paragraph(f"Статус: {status_label.get(report.status, report.status)}", normal),
        Spacer(1, 12),
    ]

    # Таблица «реквизиты»
    rows = [
        ["Клиника", org.name if org else f"org#{report.organization_id}"],
        ["Код операции", report.patient_code],
        ["Дата операции", report.operation_date],
        ["Отделение", report.department or "—"],
        ["Врач", report.doctor_name],
        ["Тип операции", report.operation_type],
    ]
    if report.diagnosis_text:
        rows.append(["Диагноз", report.diagnosis_text])
    if report.complications:
        rows.append(["Осложнения", report.complications])
    if report.notes:
        rows.append(["Заметки", report.notes])
    rows.append(["Создан",
                  report.created_at.strftime("%Y-%m-%d %H:%M")
                  if report.created_at else "—"])
    if report.submitted_at:
        rows.append(["Отправлен", report.submitted_at.strftime("%Y-%m-%d %H:%M")])
    rows.append(["Файлов прикреплено", str(len(files))])

    meta_table = Table(
        [[Paragraph(k, bold), Paragraph(str(v), normal)] for k, v in rows],
        colWidths=[130, 380],
    )
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, rl_colors.lightgrey),
    ]))
    story += [meta_table, Spacer(1, 18)]

    # Таблица имплантов
    if implants:
        story.append(Paragraph("Использованные импланты", bold))
        story.append(Spacer(1, 6))
        imp_header = ["№", "Артикул", "Номенклатура", "Кол-во", "Lot", "Серийник"]
        imp_rows = [imp_header]
        for i, imp in enumerate(implants, 1):
            imp_rows.append([
                str(i),
                imp.get("article", ""),
                Paragraph(imp.get("nomenclature", ""), normal),
                str(imp.get("qty", 1)),
                imp.get("lot_number", ""),
                imp.get("serial", ""),
            ])
        imp_table = Table(imp_rows, colWidths=[22, 70, 190, 40, 70, 90])
        imp_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
            ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#9a2a3a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("ALIGN", (3, 1), (3, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.3, rl_colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(imp_table)
    else:
        story.append(Paragraph("<i>Импланты не указаны</i>", normal))

    story += [
        Spacer(1, 24),
        Paragraph(
            "Этот документ сгенерирован системой ZMed Stock PWA. "
            "ПДн пациента в документе не содержатся (152-ФЗ): используется "
            "обезличенный код операции.",
            small,
        ),
        Paragraph(f"Сгенерирован: {_dt.now().strftime('%Y-%m-%d %H:%M')}", small),
    ]

    doc.build(story)
    buf.seek(0)
    filename = f"report_{report_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ── XLSX-экспорт ────────────────────────────────────────────────────────────

@router.get("/export.xlsx")
async def export_reports_xlsx(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    scope: OrgScope = Depends(require_org_scope),
):
    """XLSX с отчётами + сводной информацией об имплантах.

    Два листа:
      «Отчёты» — одна строка на отчёт (включает кол-во имплантов и файлов);
      «Импланты» — развёрнутая таблица позиций.
    """
    import io
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    async with AsyncSessionLocal() as s:
        stmt = (
            select(OperationReport, Organization)
            .join(Organization, Organization.id == OperationReport.organization_id)
            .order_by(OperationReport.operation_date.desc(),
                       OperationReport.id.desc())
            .limit(5000)
        )
        if scope.organization_id is not None:
            stmt = stmt.where(OperationReport.organization_id == scope.organization_id)
        if date_from:
            stmt = stmt.where(OperationReport.operation_date >= _parse_iso_date(date_from))
        if date_to:
            stmt = stmt.where(OperationReport.operation_date <= _parse_iso_date(date_to))
        if status_filter:
            if status_filter not in ALLOWED_STATUSES:
                raise HTTPException(status_code=400, detail=f"status: {status_filter}")
            stmt = stmt.where(OperationReport.status == status_filter)
        rows = (await s.execute(stmt)).all()
        report_ids = [r[0].id for r in rows]

        file_counts: dict[int, int] = {}
        if report_ids:
            from sqlalchemy import func as _f
            fc = await s.execute(
                select(OperationReportFile.report_id,
                       _f.count(OperationReportFile.id))
                .where(OperationReportFile.report_id.in_(report_ids))
                .group_by(OperationReportFile.report_id)
            )
            file_counts = dict(fc.all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Отчёты"
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="9A2A3A")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="AAAAAA")
    brd = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = [
        "#", "Дата", "Клиника", "Код операции", "Отделение",
        "Врач", "Тип операции", "Диагноз", "Статус",
        "Имплантов (поз.)", "Файлов", "Создан", "Отправлен",
        "Осложнения", "Заметки",
    ]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font, c.fill, c.alignment, c.border = hdr_font, hdr_fill, center, brd
    ws.row_dimensions[1].height = 22

    status_label = {"draft": "Черновик", "submitted": "Отправлен"}

    for i, (rep, org) in enumerate(rows, start=2):
        try:
            implants = json.loads(rep.implants_used_json) if rep.implants_used_json else []
        except (ValueError, TypeError):
            implants = []
        values = [
            rep.id,
            rep.operation_date,
            org.name,
            rep.patient_code,
            rep.department or "",
            rep.doctor_name,
            rep.operation_type,
            rep.diagnosis_text or "",
            status_label.get(rep.status, rep.status),
            len(implants),
            file_counts.get(rep.id, 0),
            rep.created_at.strftime("%Y-%m-%d %H:%M") if rep.created_at else "",
            rep.submitted_at.strftime("%Y-%m-%d %H:%M") if rep.submitted_at else "",
            rep.complications or "",
            rep.notes or "",
        ]
        for col, val in enumerate(values, 1):
            c = ws.cell(row=i, column=col, value=val)
            c.border = brd

    widths = [6, 12, 28, 16, 20, 22, 32, 36, 12, 10, 8, 18, 18, 36, 36]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + col)].width = w

    # Второй лист — импланты развёрнуто
    ws2 = wb.create_sheet("Импланты")
    headers2 = [
        "Отчёт #", "Дата", "Клиника", "Артикул", "Номенклатура",
        "Кол-во", "Lot", "Серийник",
    ]
    for col, h in enumerate(headers2, 1):
        c = ws2.cell(row=1, column=col, value=h)
        c.font, c.fill, c.alignment, c.border = hdr_font, hdr_fill, center, brd
    ws2.row_dimensions[1].height = 22

    r2 = 2
    for (rep, org) in rows:
        try:
            implants = json.loads(rep.implants_used_json) if rep.implants_used_json else []
        except (ValueError, TypeError):
            implants = []
        for imp in implants:
            vals2 = [
                rep.id, rep.operation_date, org.name,
                imp.get("article", ""),
                imp.get("nomenclature", ""),
                imp.get("qty", 1),
                imp.get("lot_number", ""),
                imp.get("serial", ""),
            ]
            for col, val in enumerate(vals2, 1):
                c = ws2.cell(row=r2, column=col, value=val)
                c.border = brd
            r2 += 1

    widths2 = [10, 12, 28, 18, 36, 10, 16, 20]
    for col, w in enumerate(widths2, 1):
        ws2.column_dimensions[chr(64 + col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = "clinic_reports.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
