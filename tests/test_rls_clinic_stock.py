"""
tests/test_rls_clinic_stock.py

Проверка row-level security модуля /api/clinic-stock.
"""

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _create_location(client, headers, name="Склад", kind="warehouse",
                            org_id=None):
    body = {"name": name, "kind": kind, "active": True}
    if org_id is not None:
        body["organization_id"] = org_id
    r = await client.post("/api/clinic-stock/locations", json=body, headers=headers)
    return r


async def _receive(client, headers, *, to_location_id, article="A-100",
                    nomenclature="Винт транспедикулярный", quantity=5,
                    lot_number="LOT1", barcode=None, org_id=None):
    body = {
        "article": article,
        "nomenclature": nomenclature,
        "lot_number": lot_number,
        "to_location_id": to_location_id,
        "quantity": quantity,
    }
    if barcode:
        body["barcode"] = barcode
    if org_id is not None:
        body["organization_id"] = org_id
    r = await client.post("/api/clinic-stock/receive", json=body, headers=headers)
    return r


# ── Тесты локаций ───────────────────────────────────────────────────────────

async def test_orphan_cannot_access_stock(client, auth):
    r = await client.get("/api/clinic-stock/locations", headers=auth["orphan"])
    assert r.status_code == 403


async def test_clinic_a_sees_only_own_locations(client, auth):
    """A1 создаёт локацию, B1 её не видит."""
    r = await _create_location(client, auth["a1"], name="Склад A")
    assert r.status_code == 201
    rb = await client.get("/api/clinic-stock/locations", headers=auth["b1"])
    assert rb.status_code == 200
    assert rb.json()["locations"] == []


async def test_zmed_sees_all_locations(client, auth, orgs):
    await _create_location(client, auth["a1"], name="Склад A")
    await _create_location(client, auth["b1"], name="Склад B")
    r = await client.get("/api/clinic-stock/locations", headers=auth["zmed_admin"])
    assert r.status_code == 200
    names = {l["name"] for l in r.json()["locations"]}
    assert names == {"Склад A", "Склад B"}


# ── Тесты товара ────────────────────────────────────────────────────────────

async def test_receive_creates_item_in_user_org(client, auth, orgs):
    loc_resp = await _create_location(client, auth["a1"], name="Склад")
    loc_id = loc_resp.json()["id"]
    r = await _receive(client, auth["a1"], to_location_id=loc_id)
    assert r.status_code == 201

    items_r = await client.get("/api/clinic-stock/items", headers=auth["a1"])
    assert len(items_r.json()["items"]) == 1
    assert items_r.json()["items"][0]["organization_id"] == orgs["a"]


async def test_clinic_cannot_use_foreign_location(client, auth):
    """B1 пытается оприходовать товар на локацию клиники A — 404."""
    loc_a = (await _create_location(client, auth["a1"], name="Склад A")).json()
    r = await _receive(client, auth["b1"], to_location_id=loc_a["id"])
    assert r.status_code == 404


async def test_clinic_cannot_see_items_of_other_clinic(client, auth):
    loc_a = (await _create_location(client, auth["a1"], name="Склад A")).json()
    await _receive(client, auth["a1"], to_location_id=loc_a["id"])
    # B1 запрашивает items — должно быть пусто
    r = await client.get("/api/clinic-stock/items", headers=auth["b1"])
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_scan_barcode_is_scoped(client, auth):
    loc_a = (await _create_location(client, auth["a1"], name="Склад A")).json()
    await _receive(client, auth["a1"], to_location_id=loc_a["id"],
                    barcode="4600000000019")
    # A1 находит по barcode
    ra = await client.get("/api/clinic-stock/scan",
                          params={"barcode": "4600000000019"},
                          headers=auth["a1"])
    assert ra.status_code == 200
    assert len(ra.json()["items"]) == 1
    # B1 — не находит
    rb = await client.get("/api/clinic-stock/scan",
                          params={"barcode": "4600000000019"},
                          headers=auth["b1"])
    assert rb.status_code == 200
    assert rb.json()["items"] == []


# ── Тесты движений ──────────────────────────────────────────────────────────

async def test_transfer_blocked_across_orgs(client, auth):
    """Нельзя переместить item клиники A, подсунув to_location клиники B.

    На практике это невозможно, т.к. B-локация для A пройдёт как «не найдена»
    (RLS). Но на уровне HTTP проверяем 404.
    """
    loc_a = (await _create_location(client, auth["a1"], name="Склад A")).json()
    loc_b = (await _create_location(client, auth["b1"], name="Склад B")).json()
    receive_resp = await _receive(client, auth["a1"], to_location_id=loc_a["id"])
    item_id = receive_resp.json()["item_id"]

    r = await client.post("/api/clinic-stock/transfer",
                          json={
                              "item_id": item_id,
                              "from_location_id": loc_a["id"],
                              "to_location_id": loc_b["id"],
                              "quantity": 1,
                          },
                          headers=auth["a1"])
    assert r.status_code == 404


async def test_consume_rejects_foreign_report(client, auth):
    """consume с operation_report_id из чужой клиники — 404."""
    loc_a = (await _create_location(client, auth["a1"], name="Склад A")).json()
    rec = await _receive(client, auth["a1"], to_location_id=loc_a["id"])
    item_id = rec.json()["item_id"]

    # Создаём отчёт в клинике B
    rb = await client.post("/api/clinic-reports", json={
        "patient_code": "OP-B-1",
        "operation_date": "2026-10-20",
        "doctor_name": "Петров П.П.",
        "operation_type": "ALIF",
    }, headers=auth["b1"])
    assert rb.status_code == 201
    foreign_report_id = rb.json()["id"]

    # Пытаемся consume в клинике A со ссылкой на чужой отчёт
    r = await client.post("/api/clinic-stock/consume",
                          json={
                              "item_id": item_id,
                              "from_location_id": loc_a["id"],
                              "quantity": 1,
                              "operation_report_id": foreign_report_id,
                          },
                          headers=auth["a1"])
    assert r.status_code == 404


async def test_insufficient_balance_rejected(client, auth):
    """Нельзя списать больше, чем есть на локации — 409."""
    loc_a = (await _create_location(client, auth["a1"], name="Склад A")).json()
    rec = await _receive(client, auth["a1"], to_location_id=loc_a["id"],
                          quantity=3)
    item_id = rec.json()["item_id"]

    r = await client.post("/api/clinic-stock/consume",
                          json={
                              "item_id": item_id,
                              "from_location_id": loc_a["id"],
                              "quantity": 10,  # больше чем есть
                          },
                          headers=auth["a1"])
    assert r.status_code == 409


async def test_losses_scoped_for_clinic(client, auth):
    """Клинический юзер видит потери только своей клиники."""
    loc_a = (await _create_location(client, auth["a1"], name="Склад A")).json()
    loc_b = (await _create_location(client, auth["b1"], name="Склад B")).json()
    rec_a = (await _receive(client, auth["a1"], to_location_id=loc_a["id"])).json()
    rec_b = (await _receive(client, auth["b1"], to_location_id=loc_b["id"],
                             article="B-1")).json()
    # Списать и там, и там
    await client.post("/api/clinic-stock/write-off",
                      json={"item_id": rec_a["item_id"],
                            "from_location_id": loc_a["id"],
                            "quantity": 1, "note": "test"},
                      headers=auth["a1"])
    await client.post("/api/clinic-stock/write-off",
                      json={"item_id": rec_b["item_id"],
                            "from_location_id": loc_b["id"],
                            "quantity": 1, "note": "test"},
                      headers=auth["b1"])
    # A1 видит только своё
    r = await client.get("/api/clinic-stock/losses", headers=auth["a1"])
    assert r.status_code == 200
    for m in r.json()["movements"]:
        assert m["organization_name"] == "Клиника A"
    # ZMed-staff видит оба
    r = await client.get("/api/clinic-stock/losses", headers=auth["zmed_admin"])
    assert len(r.json()["movements"]) >= 2
