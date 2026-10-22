"""
tests/test_rls_clinic_reports.py

Проверка row-level security модуля /api/clinic-reports.
"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


# ── Helper: создать отчёт от имени юзера ────────────────────────────────────

async def _create_report(client, headers, *, extra=None, status="draft"):
    body = {
        "patient_code": "OP-TEST-1",
        "operation_date": "2026-10-20",
        "doctor_name": "Иванов И.И.",
        "operation_type": "Транспедикулярная фиксация",
        "status": status,
    }
    if extra:
        body.update(extra)
    r = await client.post("/api/clinic-reports", json=body, headers=headers)
    return r


# ── Тесты ───────────────────────────────────────────────────────────────────

async def test_orphan_user_gets_403(client, auth):
    """Юзер без organization_id не допускается к модулю."""
    r = await client.get("/api/clinic-reports", headers=auth["orphan"])
    assert r.status_code == 403


async def test_clinic_user_can_create_report(client, auth, orgs):
    r = await _create_report(client, auth["a1"])
    assert r.status_code == 201
    data = r.json()
    assert data["organization_id"] == orgs["a"], (
        "Отчёт должен уйти в организацию юзера"
    )
    assert data["patient_code"] == "OP-TEST-1"


async def test_clinic_user_cannot_choose_other_org(client, auth, orgs):
    """Юзер клиники A передаёт organization_id клиники B — должен быть
    записан всё равно в A (параметр игнорируется, не ошибка)."""
    r = await _create_report(
        client, auth["a1"],
        extra={"organization_id": orgs["b"]},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["organization_id"] == orgs["a"], (
        "resolve_target_org_id должен принудительно подставить свою"
    )


async def test_clinic_user_sees_only_own_reports(client, auth):
    """A1 создаёт отчёт, B1 его не видит в списке."""
    r = await _create_report(client, auth["a1"])
    assert r.status_code == 201
    # Список для B1
    rb = await client.get("/api/clinic-reports", headers=auth["b1"])
    assert rb.status_code == 200
    assert rb.json()["reports"] == []


async def test_clinic_user_cannot_read_foreign_report(client, auth):
    """A1 создаёт отчёт, B1 пытается прочитать по id — 404."""
    created = await _create_report(client, auth["a1"])
    report_id = created.json()["id"]
    r = await client.get(f"/api/clinic-reports/{report_id}", headers=auth["b1"])
    assert r.status_code == 404


async def test_clinic_user_can_see_colleagues_reports(client, auth):
    """A1 создаёт отчёт — A2 (та же клиника) его видит."""
    created = await _create_report(client, auth["a1"])
    report_id = created.json()["id"]
    r = await client.get(f"/api/clinic-reports/{report_id}", headers=auth["a2"])
    assert r.status_code == 200, (
        "Все юзеры клиники видят все отчёты своей клиники"
    )


async def test_clinic_user_cannot_edit_colleagues_draft(client, auth):
    """A1 создал draft — A2 (та же клиника) НЕ может его редактировать."""
    created = await _create_report(client, auth["a1"])
    report_id = created.json()["id"]
    r = await client.patch(
        f"/api/clinic-reports/{report_id}",
        json={"notes": "changed by a2"},
        headers=auth["a2"],
    )
    assert r.status_code == 403, "Чужой draft нельзя редактировать"


async def test_submitted_report_is_readonly_for_author(client, auth):
    """Автор не может редактировать отчёт после submit."""
    created = await _create_report(client, auth["a1"], status="submitted")
    report_id = created.json()["id"]
    r = await client.patch(
        f"/api/clinic-reports/{report_id}",
        json={"notes": "late edit"},
        headers=auth["a1"],
    )
    assert r.status_code == 409


async def test_zmed_staff_sees_all_clinics(client, auth, orgs):
    """ZMed-staff без фильтра видит отчёты обеих клиник."""
    await _create_report(client, auth["a1"])
    await _create_report(client, auth["b1"], extra={"patient_code": "OP-B-1"})
    r = await client.get("/api/clinic-reports", headers=auth["zmed_admin"])
    assert r.status_code == 200
    orgs_in_list = {rep["organization_id"] for rep in r.json()["reports"]}
    assert orgs["a"] in orgs_in_list
    assert orgs["b"] in orgs_in_list


async def test_zmed_staff_can_filter_by_organization(client, auth, orgs):
    """ZMed-staff c ?organization_id=A видит только клинику A."""
    await _create_report(client, auth["a1"])
    await _create_report(client, auth["b1"], extra={"patient_code": "OP-B-1"})
    r = await client.get(
        "/api/clinic-reports",
        params={"organization_id": orgs["a"]},
        headers=auth["zmed_admin"],
    )
    assert r.status_code == 200
    for rep in r.json()["reports"]:
        assert rep["organization_id"] == orgs["a"]


async def test_zmed_staff_can_edit_foreign_submitted(client, auth):
    """ZMed-staff может редактировать submitted чужой клиники."""
    created = await _create_report(client, auth["a1"], status="submitted")
    report_id = created.json()["id"]
    r = await client.patch(
        f"/api/clinic-reports/{report_id}",
        json={"notes": "zmed note"},
        headers=auth["zmed_admin"],
    )
    assert r.status_code == 200
    assert r.json()["notes"] == "zmed note"


async def test_zmed_staff_must_specify_org_when_creating(client, auth):
    """ZMed-staff не может создать отчёт без organization_id."""
    r = await _create_report(client, auth["zmed_admin"])
    assert r.status_code == 400


async def test_clinic_user_can_delete_only_own_draft(client, auth):
    """Только автор может удалить свой draft (не коллега)."""
    created = await _create_report(client, auth["a1"])
    rid = created.json()["id"]
    # A2 (коллега) — нельзя
    r = await client.delete(f"/api/clinic-reports/{rid}", headers=auth["a2"])
    assert r.status_code == 403
    # A1 (автор) — ок
    r = await client.delete(f"/api/clinic-reports/{rid}", headers=auth["a1"])
    assert r.status_code == 204


async def test_clinic_user_cannot_delete_submitted(client, auth):
    """Клинический юзер не может удалить submitted (даже свой)."""
    created = await _create_report(client, auth["a1"], status="submitted")
    rid = created.json()["id"]
    r = await client.delete(f"/api/clinic-reports/{rid}", headers=auth["a1"])
    assert r.status_code == 403


async def test_patient_code_length_validation(client, auth):
    """patient_code max 32 — больше отбивается валидатором Pydantic."""
    r = await _create_report(client, auth["a1"],
                              extra={"patient_code": "x" * 33})
    assert r.status_code == 422
