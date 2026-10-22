"""
app/api/email_report.py

Email-уведомление для ZMed при отправке клиникой отчёта об операции
(status: draft → submitted). Fire-and-forget из app/api/clinic_reports.py.

Адресаты — EmailRecipient.kind in ('reports', 'all').
По 152-ФЗ: ПДн пациента не передаём (только patient_code — обезличенный).
"""

import asyncio
import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _send_report_email_sync(
    report_id: int,
    organization_name: str,
    patient_code: str,
    operation_date: str,
    department: str,
    doctor_name: str,
    operation_type: str,
    diagnosis_text: str,
    implants_used_json: str,
    complications: str,
    notes: str,
    files_count: int,
    submitted_by: str,
    submitted_at: str,
) -> None:
    from sqlalchemy.orm import Session
    from app.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    from app.db.session import sync_engine
    from app.db.models import EmailRecipient

    if not SMTP_HOST:
        logger.info("SMTP не настроен, письмо об отчёте не отправлено.")
        return

    with Session(sync_engine) as s:
        recipients = [
            r.email.strip()
            for r in s.query(EmailRecipient).filter(
                EmailRecipient.kind.in_(("reports", "all"))
            ).all()
            if r.email and r.email.strip()
        ]
    if not recipients:
        logger.info("Нет адресатов для рассылки отчётов, пропуск.")
        return

    try:
        implants = json.loads(implants_used_json) if implants_used_json else []
    except (ValueError, TypeError):
        implants = []

    implants_html = ""
    if implants:
        rows = []
        for i, imp in enumerate(implants, 1):
            bg = "#ffffff" if i % 2 == 0 else "#fdf4f5"
            rows.append(
                f'<tr style="background:{bg}">'
                f'<td style="padding:6px 10px;border:1px solid #ddd;text-align:center">{i}</td>'
                f'<td style="padding:6px 10px;border:1px solid #ddd">{imp.get("article","")}</td>'
                f'<td style="padding:6px 10px;border:1px solid #ddd">{imp.get("nomenclature","")}</td>'
                f'<td style="padding:6px 10px;border:1px solid #ddd;text-align:center">{imp.get("qty",1)}</td>'
                f'<td style="padding:6px 10px;border:1px solid #ddd">{imp.get("lot_number","")}</td>'
                f'<td style="padding:6px 10px;border:1px solid #ddd">{imp.get("serial","")}</td>'
                f'</tr>'
            )
        implants_html = (
            '<h3 style="color:#9a2a3a">Использованные импланты</h3>'
            '<table style="border-collapse:collapse;width:100%;margin-bottom:16px">'
            '<thead><tr style="background:#9a2a3a;color:#fff">'
            '<th style="padding:8px 10px;border:1px solid #7a1a2a">№</th>'
            '<th style="padding:8px 10px;border:1px solid #7a1a2a">Артикул</th>'
            '<th style="padding:8px 10px;border:1px solid #7a1a2a">Номенклатура</th>'
            '<th style="padding:8px 10px;border:1px solid #7a1a2a">Кол-во</th>'
            '<th style="padding:8px 10px;border:1px solid #7a1a2a">Lot</th>'
            '<th style="padding:8px 10px;border:1px solid #7a1a2a">Серийник</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
        )
    else:
        implants_html = '<p style="color:#888"><em>Импланты не указаны</em></p>'

    def _row(label, value):
        if not value:
            return ""
        return (f'<tr><td style="padding:4px 16px 4px 0;color:#666">{label}:</td>'
                f'<td><b>{value}</b></td></tr>')

    html_body = f"""<html><body style="font-family:Arial,sans-serif;font-size:14px;color:#333">
<h2 style="color:#9a2a3a">📋 Отчёт об операции #{report_id}</h2>
<p style="color:#888;font-size:12px">Клиника отправила новый отчёт. Нажмите в PWA, чтобы открыть.</p>
<table style="border-collapse:collapse;margin-bottom:16px">
  {_row("Клиника", organization_name)}
  {_row("Код операции", patient_code)}
  {_row("Дата операции", operation_date)}
  {_row("Отделение", department)}
  {_row("Врач", doctor_name)}
  {_row("Тип операции", operation_type)}
  {_row("Диагноз", diagnosis_text)}
  {_row("Осложнения", complications)}
  {_row("Заметки", notes)}
  {_row("Файлов прикреплено", files_count if files_count else "0")}
  {_row("Отправил", submitted_by)}
  {_row("Отправлен", submitted_at)}
</table>
{implants_html}
<p style="color:#888;font-size:11px;margin-top:24px">
По 152-ФЗ ПДн пациента в этом письме не передаются — только обезличенный код операции.
</p>
</body></html>"""

    plain = (
        f"Отчёт об операции #{report_id}\n"
        f"Клиника: {organization_name}\n"
        f"Код операции: {patient_code}\n"
        f"Дата: {operation_date}  Отделение: {department or '—'}\n"
        f"Врач: {doctor_name}\n"
        f"Тип операции: {operation_type}\n"
        f"Диагноз: {diagnosis_text or '—'}\n"
        f"Осложнения: {complications or '—'}\n"
        f"Заметки: {notes or '—'}\n"
        f"Файлов прикреплено: {files_count}\n"
        f"Отправил: {submitted_by}\n"
        f"Отправлен: {submitted_at}\n"
    )
    if implants:
        plain += "\nИспользованные импланты:\n"
        for i, imp in enumerate(implants, 1):
            plain += (f"{i}. [{imp.get('article','')}] {imp.get('nomenclature','')} "
                      f"— {imp.get('qty',1)} шт.  lot={imp.get('lot_number','')} "
                      f"serial={imp.get('serial','')}\n")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Отчёт #{report_id} · {organization_name} · {operation_date}"
    msg["From"] = SMTP_FROM or SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], recipients, msg.as_string())
        logger.info("Отчёт #%s отправлен на email: %s", report_id, recipients)
    except Exception as e:
        logger.error("Ошибка отправки письма об отчёте #%s: %s", report_id, e)


async def send_report_notification(
    report_id: int,
    organization_name: str,
    patient_code: str,
    operation_date: str,
    department: str,
    doctor_name: str,
    operation_type: str,
    diagnosis_text: str,
    implants_used_json: str,
    complications: str,
    notes: str,
    files_count: int,
    submitted_by: str,
    submitted_at: str,
) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _send_report_email_sync,
        report_id, organization_name, patient_code, operation_date,
        department or "", doctor_name, operation_type,
        diagnosis_text or "", implants_used_json or "",
        complications or "", notes or "", files_count,
        submitted_by, submitted_at,
    )
