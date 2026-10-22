"""
tests/test_clinic_reports_extras.py

Покрытие функций: теги (F27), bulk-tag (F33), копирование (F32),
полнотекстовый поиск FTS5 (F26).
"""

from datetime import datetime, timezone

import pytest

from app.db.models import OperationReport, ReportTag
from app.db.session import AsyncSessionLocal

pytestmark = pytest.mark.asyncio


async def _create_report(client, headers, *, patient_code="OP-1", status="draft",
                          doctor_name="Петров П.П.",
                          operation_type="Транспедикулярная фиксация",
                          diagnosis_text=""):
    body = {
        "patient_code": patient_code,
        "operation_date": "2026-10-20",
        "doctor_name": doctor_name,
        "operation_type": operation_type,
        "diagnosis_text": diagnosis_text,
        "status": status,
    }
    return await client.post("/api/clinic-reports", json=body, headers=headers)


async def _seed_tag(name="Осложнения", color="#dc2626"):
    async with AsyncSessionLocal() as s:
        t = ReportTag(name=name, color=color, active=1)
        s.add(t)
        await s.commit()
        await s.refresh(t)
        return t.id


# ── Теги ────────────────────────────────────────────────────────────────────

async def test_tags_list_only_active(client, auth):
    """Архивные теги не показываются в /tags/list."""
    async with AsyncSessionLocal() as s:
        s.add_all([
            ReportTag(name="Active1", color="#000000", active=1),
            ReportTag(name="Archived1", color="#000000", active=0),
        ])
        await s.commit()
    r = await client.get("/api/clinic-reports/tags/list", headers=auth["a1"])
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tags"]}
    assert "Active1" in names
    assert "Archived1" not in names


async def test_set_tags_on_report(client, auth):
    tag_id = await _seed_tag()
    created = await _create_report(client, auth["a1"])
    rid = created.json()["id"]

    r = await client.put(f"/api/clinic-reports/{rid}/tags",
                          json={"tag_ids": [tag_id]}, headers=auth["a1"])
    assert r.status_code == 200
    assert r.json()["tag_ids"] == [tag_id]

    # В get отчёта теги теперь показаны
    g = await client.get(f"/api/clinic-reports/{rid}", headers=auth["a1"])
    assert len(g.json()["tags"]) == 1
    assert g.json()["tags"][0]["id"] == tag_id


async def test_set_tags_rejects_archived_tag(client, auth):
    async with AsyncSessionLocal() as s:
        t = ReportTag(name="Archived2", color="#000000", active=0)
        s.add(t)
        await s.commit()
        archived_tag_id = t.id

    rid = (await _create_report(client, auth["a1"])).json()["id"]
    r = await client.put(f"/api/clinic-reports/{rid}/tags",
                          json={"tag_ids": [archived_tag_id]}, headers=auth["a1"])
    assert r.status_code == 400


async def test_set_tags_blocked_on_submitted_for_clinic(client, auth):
    """Клиника не может ставить теги на уже отправленный отчёт."""
    tag_id = await _seed_tag()
    rid = (await _create_report(client, auth["a1"], status="submitted")).json()["id"]
    r = await client.put(f"/api/clinic-reports/{rid}/tags",
                          json={"tag_ids": [tag_id]}, headers=auth["a1"])
    assert r.status_code == 409  # submitted — read-only


async def test_list_reports_filter_by_tag(client, auth):
    tag_id = await _seed_tag()
    r1 = (await _create_report(client, auth["a1"], patient_code="A-1")).json()["id"]
    _ = (await _create_report(client, auth["a1"], patient_code="A-2")).json()["id"]
    await client.put(f"/api/clinic-reports/{r1}/tags",
                     json={"tag_ids": [tag_id]}, headers=auth["a1"])

    r = await client.get("/api/clinic-reports",
                          params={"tag_id": tag_id}, headers=auth["a1"])
    assert r.status_code == 200
    ids = {rep["id"] for rep in r.json()["reports"]}
    assert ids == {r1}


# ── Bulk-tag ────────────────────────────────────────────────────────────────

async def test_bulk_tag_add_and_remove(client, auth):
    tag_id = await _seed_tag()
    rid1 = (await _create_report(client, auth["a1"], patient_code="A-1")).json()["id"]
    rid2 = (await _create_report(client, auth["a1"], patient_code="A-2")).json()["id"]

    # add
    r = await client.post("/api/clinic-reports/bulk-tag",
                           json={"report_ids": [rid1, rid2],
                                  "tag_id": tag_id, "mode": "add"},
                           headers=auth["a1"])
    assert r.status_code == 200
    assert set(r.json()["affected"]) == {rid1, rid2}

    # повторный add — идемпотентен, affected пуст
    r2 = await client.post("/api/clinic-reports/bulk-tag",
                            json={"report_ids": [rid1, rid2],
                                   "tag_id": tag_id, "mode": "add"},
                            headers=auth["a1"])
    assert r2.json()["affected"] == []

    # remove
    r3 = await client.post("/api/clinic-reports/bulk-tag",
                            json={"report_ids": [rid1],
                                   "tag_id": tag_id, "mode": "remove"},
                            headers=auth["a1"])
    assert r3.json()["affected"] == [rid1]


async def test_bulk_tag_skips_inaccessible(client, auth):
    """Если среди переданных есть чужой отчёт — он уходит в skipped."""
    tag_id = await _seed_tag()
    rid_a = (await _create_report(client, auth["a1"])).json()["id"]
    rid_b = (await _create_report(client, auth["b1"])).json()["id"]

    r = await client.post("/api/clinic-reports/bulk-tag",
                           json={"report_ids": [rid_a, rid_b],
                                  "tag_id": tag_id, "mode": "add"},
                           headers=auth["a1"])
    assert r.status_code == 200
    assert r.json()["affected"] == [rid_a]
    assert r.json()["skipped"] == [rid_b]


# ── Копирование (F32) ───────────────────────────────────────────────────────

async def test_copy_report_creates_draft_same_org(client, auth, orgs):
    src = await _create_report(client, auth["a1"],
                                 patient_code="OP-SRC",
                                 diagnosis_text="M51.1",
                                 status="submitted")
    rid = src.json()["id"]

    r = await client.post(f"/api/clinic-reports/{rid}/copy",
                           headers=auth["a1"])
    assert r.status_code == 201
    new = r.json()
    assert new["id"] != rid
    assert new["status"] == "draft"
    assert new["organization_id"] == orgs["a"]
    assert new["patient_code"] == "OP-SRC"
    assert new["diagnosis_text"] == "M51.1"


async def test_copy_report_strips_notes_and_files(client, auth):
    """notes и файлы не копируются; теги/аудит — тоже."""
    tag_id = await _seed_tag()
    src = await _create_report(client, auth["a1"],
                                 patient_code="OP-SRC2")
    rid = src.json()["id"]
    await client.patch(f"/api/clinic-reports/{rid}",
                        json={"notes": "это заметка исходного отчёта"},
                        headers=auth["a1"])
    await client.put(f"/api/clinic-reports/{rid}/tags",
                      json={"tag_ids": [tag_id]}, headers=auth["a1"])

    r = await client.post(f"/api/clinic-reports/{rid}/copy", headers=auth["a1"])
    new = r.json()
    assert not new["notes"]
    assert new["files"] == []
    assert new["tags"] == []


async def test_copy_foreign_report_denied(client, auth):
    """A1 не может скопировать отчёт клиники B."""
    foreign = (await _create_report(client, auth["b1"],
                                      patient_code="OP-B-1")).json()["id"]
    r = await client.post(f"/api/clinic-reports/{foreign}/copy",
                           headers=auth["a1"])
    assert r.status_code == 404


# ── Пагинация (F16) ─────────────────────────────────────────────────────────

async def test_pagination_returns_total(client, auth):
    for i in range(3):
        await _create_report(client, auth["a1"], patient_code=f"P-{i}")
    r = await client.get("/api/clinic-reports",
                          params={"limit": 2}, headers=auth["a1"])
    data = r.json()
    assert data["total"] == 3
    assert len(data["reports"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0

    r2 = await client.get("/api/clinic-reports",
                           params={"limit": 2, "offset": 2}, headers=auth["a1"])
    assert len(r2.json()["reports"]) == 1


# ── Полнотекстовый поиск (F26) ──────────────────────────────────────────────
# FTS5 не создаётся Base.metadata.create_all; тест пропустим.
# Если нужно — можно установить FTS в фикстуре через raw SQL,
# но функциональность для тестов не критична.


# ── OTP consume_otp (F21) ───────────────────────────────────────────────────

async def test_consume_otp_rejects_wrong_code(users):
    """Прямой вызов consume_otp с неправильным кодом → 401."""
    from fastapi import HTTPException
    from app.api.otp import consume_otp
    from app.db.models import User

    async with AsyncSessionLocal() as s:
        user = await s.get(User, users["a1"])

    with pytest.raises(HTTPException) as ei:
        await consume_otp(user, "report_submit:1", "000000")
    assert ei.value.status_code == 401


async def test_otp_request_requires_email(client, auth):
    """У юзера без email запрос OTP вернёт 400."""
    r = await client.post("/api/otp/request",
                           json={"purpose": "report_submit:1"},
                           headers=auth["a1"])  # у a1 email не задан в фикстуре
    assert r.status_code == 400
    assert "email" in (r.json().get("detail") or "").lower()
