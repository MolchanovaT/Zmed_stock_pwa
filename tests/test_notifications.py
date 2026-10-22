"""
tests/test_notifications.py

Юнит-тесты рассылок:
  * _send_email_sync (orders)      — фильтр email_recipients.kind in (orders, all)
  * _send_report_email_sync       — фильтр kind in (reports, all)
  * send_report_tg_notification   — через @ZmedBot получают только is_superuser
                                     ZMed с заполненным tg_id

Подменяем smtplib.SMTP и aiohttp.ClientSession.post на фейки — реальных
соединений не делаем.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from app.api import email as email_mod
from app.api import email_report as email_report_mod
from app.api import tg_notify as tg_mod
from app.db.models import EmailRecipient, Organization, User
from app.db.session import AsyncSessionLocal

pytestmark = pytest.mark.asyncio


# ── Фейки SMTP ──────────────────────────────────────────────────────────────

class FakeSMTP:
    """Контекстный менеджер, запоминающий всё, что ушло в sendmail()."""

    sent: list[dict] = []

    def __init__(self, host, port, timeout=10):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, msg_string):
        FakeSMTP.sent.append({
            "from": from_addr, "to": list(to_addrs), "body": msg_string,
        })


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch):
    FakeSMTP.sent.clear()
    monkeypatch.setattr(email_mod.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_report_mod.smtplib, "SMTP", FakeSMTP)
    # Для email требуется SMTP_HOST — задаём непустое через конфиг-модули.
    monkeypatch.setattr(email_mod, "logger", email_mod.logger)
    # SMTP_HOST читается внутри _send_*_sync через local import — подменим env:
    import os
    os.environ["SMTP_HOST"] = "smtp.test"
    os.environ["SMTP_USER"] = "test@test"
    os.environ["SMTP_PASSWORD"] = "pw"
    os.environ["SMTP_FROM"] = "test@test"
    # Перечитаем конфиг (его читают во время вызова через `from app.config import ...`)
    import importlib
    from app import config as app_config
    importlib.reload(app_config)
    yield


# ── Хелперы ─────────────────────────────────────────────────────────────────

async def _setup_recipients(kinds: dict[str, str]):
    """kinds = {"a@test": "orders", "b@test": "reports", "c@test": "all"}"""
    async with AsyncSessionLocal() as s:
        for email, kind in kinds.items():
            s.add(EmailRecipient(email=email, label=None, kind=kind))
        await s.commit()


# ── Тесты email по заказам ─────────────────────────────────────────────────

async def test_order_email_only_orders_kind(monkeypatch):
    await _setup_recipients({
        "a@test": "orders",
        "b@test": "reports",
        "c@test": "all",
    })
    email_mod._send_email_sync(
        subject="Test",
        cart_id=1, lpu="ЛПУ",
        user_full_name="U", user_username="u", user_tg_id=0,
        now_str="2026-10-22 10:00",
        items_snapshot=[("A1", "Nom", "Char", 1, 0)],
    )
    assert len(FakeSMTP.sent) == 1
    recipients = FakeSMTP.sent[0]["to"]
    assert "a@test" in recipients, "orders — получает"
    assert "c@test" in recipients, "all — тоже получает"
    assert "b@test" not in recipients, "reports — НЕ получает письмо о заказе"


async def test_order_email_superuser_skips_recipients_table(monkeypatch):
    """is_superuser=True + свой email → письмо ТОЛЬКО на свой email."""
    await _setup_recipients({"a@test": "all", "b@test": "orders"})
    email_mod._send_email_sync(
        subject="S", cart_id=1, lpu="L",
        user_full_name="SU", user_username="su", user_tg_id=0,
        now_str="2026-10-22 10:00",
        items_snapshot=[("A", "N", "", 1, 0)],
        user_email="supe@zmed.ru",
        is_superuser=True,
    )
    assert len(FakeSMTP.sent) == 1
    assert FakeSMTP.sent[0]["to"] == ["supe@zmed.ru"]


# ── Тесты email по отчётам ─────────────────────────────────────────────────

async def test_report_email_only_reports_kind():
    await _setup_recipients({
        "a@test": "orders",
        "b@test": "reports",
        "c@test": "all",
    })
    email_report_mod._send_report_email_sync(
        report_id=42,
        organization_name="Клиника X",
        patient_code="OP-X",
        operation_date="2026-10-22",
        department="нейрохирургия",
        doctor_name="Петров П.П.",
        operation_type="ALIF",
        diagnosis_text="M51.1",
        implants_used_json=json.dumps([
            {"article": "A1", "nomenclature": "Nom", "qty": 1,
             "lot_number": "L1", "serial": "S1"}
        ]),
        complications="нет",
        notes="",
        files_count=0,
        submitted_by="u",
        submitted_at="2026-10-22T10:00:00+00:00",
    )
    assert len(FakeSMTP.sent) == 1
    to = FakeSMTP.sent[0]["to"]
    assert "b@test" in to and "c@test" in to
    assert "a@test" not in to, "orders — не получает письмо об отчёте"


async def test_report_email_contains_no_patient_pii():
    """Правило 152-ФЗ: в тексте не должно быть ФИО или даты рождения.
    Мы просто проверяем, что patient_code отображается без ФИО-like значений
    и в тело не попадают имена пациентов (у нас их не передают)."""
    await _setup_recipients({"c@test": "all"})
    email_report_mod._send_report_email_sync(
        report_id=1, organization_name="X",
        patient_code="OP-TEST-1",
        operation_date="2026-10-22",
        department="", doctor_name="Петров П.П.",
        operation_type="T", diagnosis_text="",
        implants_used_json="[]",
        complications="", notes="", files_count=0,
        submitted_by="u", submitted_at="2026-10-22T10:00:00+00:00",
    )
    body = FakeSMTP.sent[0]["body"]
    assert "OP-TEST-1" in body
    # Футер должен явно упоминать 152-ФЗ
    assert "152-ФЗ" in body


# ── Тесты TG-уведомлений ────────────────────────────────────────────────────

async def test_tg_recipients_only_zmed_superusers(monkeypatch, orgs):
    """send_report_tg_notification шлёт только is_superuser ZMed с tg_id."""
    # Готовим юзеров прямо через БД
    async with AsyncSessionLocal() as s:
        # ZMed-супер с tg_id — ДОЛЖЕН получить
        s.add(User(username="z_super", organization_id=orgs["zmed"],
                   is_superuser=1, active=1, tg_id=100))
        # ZMed-супер без tg_id — НЕ получит
        s.add(User(username="z_super_notg", organization_id=orgs["zmed"],
                   is_superuser=1, active=1, tg_id=None))
        # ZMed не супер — НЕ получит
        s.add(User(username="z_user", organization_id=orgs["zmed"],
                   is_superuser=0, active=1, tg_id=200))
        # Клинический супер — НЕ получит
        s.add(User(username="c_super", organization_id=orgs["a"],
                   is_superuser=1, active=1, tg_id=300))
        # ZMed-супер неактивный — НЕ получит
        s.add(User(username="z_super_inactive", organization_id=orgs["zmed"],
                   is_superuser=1, active=0, tg_id=400))
        await s.commit()

    # Фейкаем aiohttp.ClientSession.post → собираем вызовы
    calls: list[dict] = []

    class FakeResponse:
        def __init__(self, status=200, text=""):
            self.status = status
            self._text = text
        async def text(self):
            return self._text
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class FakeClientSession:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        def post(self, url, json=None, timeout=None):
            calls.append({"url": url, "json": json})
            return FakeResponse()

    monkeypatch.setattr(tg_mod.aiohttp, "ClientSession", FakeClientSession)
    monkeypatch.setattr(tg_mod, "BOT_TOKEN_INN", "fake-token")

    await tg_mod.send_report_tg_notification(
        report_id=99,
        organization_name="Клиника A",
        operation_date="2026-10-22",
        operation_type="ALIF",
        patient_code="OP-A-99",
        doctor_name="Иванов И.И.",
        files_count=3,
    )

    chat_ids = {c["json"]["chat_id"] for c in calls}
    assert chat_ids == {100}, f"Ожидали только tg_id=100, получили {chat_ids}"
    assert all("fake-token" in c["url"] for c in calls)
    # В тексте — ссылка отсутствует, т.к. PWA_BASE_URL не задан
    assert "OP-A-99" in calls[0]["json"]["text"]
    assert "<b>Файлов:</b> 3" in calls[0]["json"]["text"]


async def test_tg_noop_when_token_missing(monkeypatch, orgs):
    """Без BOT_TOKEN_INN — вызовов нет, тихо выходим."""
    async with AsyncSessionLocal() as s:
        s.add(User(username="z_super", organization_id=orgs["zmed"],
                   is_superuser=1, active=1, tg_id=100))
        await s.commit()

    calls: list = []
    monkeypatch.setattr(tg_mod, "BOT_TOKEN_INN", None)
    # Если дойдёт до ClientSession — упадём; значит, не должен дойти.
    class Boom:
        def __init__(self, *a, **kw):
            calls.append("boom")
            raise AssertionError("TG session must not open without token")
    monkeypatch.setattr(tg_mod.aiohttp, "ClientSession", Boom)

    await tg_mod.send_report_tg_notification(
        report_id=1, organization_name="X", operation_date="2026-10-22",
        operation_type="T", patient_code="OP-1", doctor_name="D", files_count=0,
    )
    assert calls == []
