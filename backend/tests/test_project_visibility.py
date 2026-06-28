from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.core import (
    ExtractedEvent,
    ExtractedEventStatus,
    ExtractedEventType,
    HistoryEntry,
    HistoryChangeType,
    PendingInterpretation,
    PendingInterpretationStatus,
    Project,
)


def create_project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "ویلا دماوند"})
    assert response.status_code == 201
    return response.json()


def create_worker(client: TestClient, project_id: int, payload: dict) -> dict:
    response = client.post(f"/projects/{project_id}/workers", json=payload)
    assert response.status_code == 201, f"Worker creation failed: {response.text}"
    return response.json()


def create_payment(client: TestClient, project_id: int, payload: dict) -> dict:
    response = client.post(f"/projects/{project_id}/payments", json=payload)
    assert response.status_code == 201, f"Payment creation failed: {response.text}"
    return response.json()


def create_invoice(client: TestClient, project_id: int, payload: dict) -> dict:
    response = client.post(f"/projects/{project_id}/invoices", json=payload)
    assert response.status_code == 201, f"Invoice creation failed: {response.text}"
    return response.json()


class TestProjectVisibility:
    """Verify project visibility after confirmed records."""

    def test_project_summary_after_confirmed_records(self, client: TestClient):
        """Full project visibility test with direct API calls."""
        project = create_project(client)
        project_id = project["id"]

        # 1) Create client profile
        client_worker = create_worker(client, project_id, {
            "name": "میثم کبیری",
            "type": "CLIENT",
            "phone": "09123456789",
            "account_number": "6037991234567890",
        })

        # 2) Create skilled worker (سرامیک‌کار)
        skilled_worker = create_worker(client, project_id, {
            "name": "ریاحی",
            "type": "SKILLED_WORKER",
            "role_detail": "سرامیک‌کار",
            "phone": "09121111111",
        })

        # 3) Create daily worker
        daily_worker = create_worker(client, project_id, {
            "name": "مش رحیم",
            "type": "DAILY_WORKER",
            "daily_rate": "1200000",
        })

        # 4) Create vendor: هادی پور
        vendor1 = create_worker(client, project_id, {
            "name": "هادی پور",
            "type": "VENDOR",
        })

        # 5) Create vendor: آهنچی
        vendor2 = create_worker(client, project_id, {
            "name": "آهنچی",
            "type": "VENDOR",
        })

        # 6) Client incoming payment: 300,000,000
        create_payment(client, project_id, {
            "entity_id": client_worker["id"],
            "amount": "300000000",
            "type": "BANK_TRANSFER",
            "direction": "INCOMING",
        })

        # 7) Paid purchase: pay هادی پور 25,000,000
        create_invoice(client, project_id, {
            "vendor_id": vendor1["id"],
            "total_amount": "25000000",
            "description": "سیم",
        })
        # Pay the invoice
        create_payment(client, project_id, {
            "entity_id": vendor1["id"],
            "amount": "25000000",
            "type": "CASH",
            "direction": "OUTGOING",
            "related_invoice_id": 1,
        })

        # 8) Unpaid purchase: invoice from آهنچی 80,000,000 (not paid)
        create_invoice(client, project_id, {
            "vendor_id": vendor2["id"],
            "total_amount": "80000000",
            "description": "میلگرد",
        })

        # 9) Worker payment: pay ریاحی 20,000,000
        create_payment(client, project_id, {
            "entity_id": skilled_worker["id"],
            "amount": "20000000",
            "type": "CASH",
            "direction": "OUTGOING",
        })

        # ── Verify visibility endpoints ──

        # A) Workers list
        workers_resp = client.get(f"/projects/{project_id}/workers")
        assert workers_resp.status_code == 200
        workers = workers_resp.json()
        assert len(workers) >= 5, f"Expected >=5 workers, got {len(workers)}"

        # Build lookup
        workers_by_name = {}
        for w in workers:
            # Normalize names
            for key in [w["name"], w["name"].strip()]:
                workers_by_name[key] = w
            # Also store by partial match
            for name_part in w["name"].split():
                workers_by_name.setdefault(name_part, w)

        def find_worker(name_fragment: str) -> dict | None:
            for w in workers:
                if name_fragment in w["name"]:
                    return w
            return None

        # Client visible with phone/account
        meysam = find_worker("میثم")
        assert meysam is not None, "میثم not found"
        assert meysam["type"] == "CLIENT", f"میثم should be CLIENT, got {meysam['type']}"
        assert meysam["phone"] == "09123456789", f"میثم phone: {meysam['phone']}"
        assert meysam["account_number"] == "6037991234567890", f"میثم account: {meysam['account_number']}"

        # ریاحی visible as skilled worker
        riyahi = find_worker("ریاحی")
        assert riyahi is not None, "ریاحی not found"
        assert riyahi["type"] == "SKILLED_WORKER", f"ریاحی type: {riyahi['type']}"
        assert riyahi["role_detail"] == "سرامیک‌کار", f"ریاحی role_detail: {riyahi['role_detail']}"
        assert riyahi["phone"] == "09121111111", f"ریاحی phone: {riyahi['phone']}"

        # مش رحیم visible as daily worker with daily_rate
        rahim = find_worker("رحیم")
        assert rahim is not None, "مش رحیم not found"
        assert rahim["type"] == "DAILY_WORKER", f"مش رحیم type: {rahim['type']}"
        daily_rate = Decimal(str(rahim["daily_rate"])) if rahim.get("daily_rate") else Decimal("0")
        assert daily_rate == Decimal("1200000"), f"مش رحیم daily_rate: {daily_rate}"

        # Vendors visible
        vendor_names = [w["name"] for w in workers if w["type"] == "VENDOR"]
        assert any("هادی" in n for n in vendor_names), f"هادی not in vendors: {vendor_names}"
        assert any("آهنچی" in n for n in vendor_names), f"آهنچی not in vendors: {vendor_names}"

        # B) Operating summary
        summary_resp = client.get(f"/projects/{project_id}/operating-summary")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()

        total_received = Decimal(str(summary["total_received"]))
        total_paid_out = Decimal(str(summary["total_paid_out"]))
        open_payables = Decimal(str(summary["open_payables"]))
        project_balance = Decimal(str(summary["project_balance"]))

        # money_in = 300,000,000
        assert total_received == Decimal("300000000"), f"total_received={total_received}"

        # paid_out = 25,000,000 (purchase) + 20,000,000 (worker payment)
        assert total_paid_out == Decimal("45000000"), f"total_paid_out={total_paid_out}"

        # open_payables = 80,000,000 (unpaid purchase)
        assert open_payables == Decimal("80000000"), f"open_payables={open_payables}"

        # balance = 300M - 45M - 80M = 175M
        assert project_balance == Decimal("175000000"), f"project_balance={project_balance}"

        # C) Vendor debts include آهنچی with 80M debt
        vendor_debts = summary.get("vendor_debts", [])
        assert len(vendor_debts) >= 1, f"No vendor debts: {vendor_debts}"
        ahanghi_debt = next((d for d in vendor_debts if "آهنچی" in d["vendor_name"]), None)
        assert ahanghi_debt is not None, f"آهنچی not in vendor_debts: {vendor_debts}"
        assert Decimal(str(ahanghi_debt["debt"])) == Decimal("80000000"), f"آهنچی debt={ahanghi_debt['debt']}"

        # D) Payments
        payments_resp = client.get(f"/projects/{project_id}/payments")
        assert payments_resp.status_code == 200
        payments = payments_resp.json()
        assert len(payments) >= 3, f"Expected >=3 payments, got {len(payments)}"

        incoming = [p for p in payments if p["direction"] == "INCOMING"]
        outgoing = [p for p in payments if p["direction"] == "OUTGOING"]
        assert len(incoming) >= 1, "No incoming payments"
        assert len(outgoing) >= 2, f"Expected >=2 outgoing, got {len(outgoing)}"

        # E) Invoices (open payables)
        invoices_resp = client.get(f"/projects/{project_id}/invoices")
        assert invoices_resp.status_code == 200
        invoices = invoices_resp.json()
        open_invoices = [inv for inv in invoices if inv["status"] == "OPEN"]
        assert len(open_invoices) >= 1, "Expected >=1 open invoice"
        open_amount = sum(Decimal(str(inv["total_amount"])) for inv in open_invoices)
        assert open_amount == Decimal("80000000"), f"Open invoices total={open_amount}"

        # F) No fake person named "کارفرما"
        assert all("کارفرما" not in w["name"] for w in workers), "Fake 'کارفرما' found"

    def test_empty_project_visibility(self, client: TestClient):
        """Verify visibility for a fresh project with no records."""
        project = create_project(client)
        project_id = project["id"]

        workers_resp = client.get(f"/projects/{project_id}/workers")
        assert workers_resp.status_code == 200
        assert workers_resp.json() == []

        payments_resp = client.get(f"/projects/{project_id}/payments")
        assert payments_resp.status_code == 200
        assert payments_resp.json() == []

        invoices_resp = client.get(f"/projects/{project_id}/invoices")
        assert invoices_resp.status_code == 200
        assert invoices_resp.json() == []

        summary_resp = client.get(f"/projects/{project_id}/operating-summary")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert Decimal(str(summary["total_received"])) == Decimal("0")
        assert Decimal(str(summary["total_paid_out"])) == Decimal("0")
        assert Decimal(str(summary["open_payables"])) == Decimal("0")

        pending_resp = client.get(f"/projects/{project_id}/pending-interpretations")
        assert pending_resp.status_code == 200
        assert pending_resp.json() == []

    def test_pending_items_excluded_from_confirmed(self, client: TestClient, db_session):
        """Verify pending interpretations are not counted in confirmed records."""
        project = create_project(client)
        project_id = project["id"]

        # Create a pending interpretation directly in DB
        pending = PendingInterpretation(
            project_id=project_id,
            raw_input_text="میثم 100 میلیون تومان به حساب پروژه واریز کرد",
            canonical_event_type="FINANCIAL_EVENT",
            semantic_action="PAYMENT_IN",
            status=PendingInterpretationStatus.PENDING,
        )
        db_session.add(pending)
        db_session.commit()

        # Verify no confirmed payments
        payments_resp = client.get(f"/projects/{project_id}/payments")
        assert payments_resp.status_code == 200
        assert payments_resp.json() == []

        # Verify operating summary shows zero totals
        summary_resp = client.get(f"/projects/{project_id}/operating-summary")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert Decimal(str(summary["total_received"])) == Decimal("0")

        # Verify pending interpretations exist
        pending_resp = client.get(f"/projects/{project_id}/pending-interpretations")
        assert pending_resp.status_code == 200
        pending_list = pending_resp.json()
        assert len(pending_list) >= 1, "Expected >=1 pending interpretation"

    def test_note_visible_in_history(self, client: TestClient, db_session):
        """Verify a confirmed note shows up in history."""
        project = create_project(client)
        project_id = project["id"]

        # Add a history entry directly as a NOTE
        entry = HistoryEntry(
            project_id=project_id,
            input_text="کارفرما درخواست تغییر محل پریزهای پذیرایی را داد",
            change_type=HistoryChangeType.NOTE,
        )
        db_session.add(entry)
        db_session.commit()

        # Verify note visible in history
        history_resp = client.get(f"/projects/{project_id}/history")
        assert history_resp.status_code == 200
        history = history_resp.json()
        notes = [h for h in history if h["change_type"] == "NOTE"]
        assert len(notes) >= 1, "Expected >=1 note"
        note_texts = [n["input_text"] for n in notes]
        has_note = any("پریز" in text or "پذیرایی" in text for text in note_texts)
        assert has_note, f"Note about پریز not found: {note_texts}"

    def test_project_detail_includes_summary(self, client: TestClient):
        """Verify the enriched project detail response includes summary."""
        project = create_project(client)
        project_id = project["id"]

        detail_resp = client.get(f"/projects/{project_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()

        # Should include summary
        assert "summary" in detail, "Expected summary field in project detail"
        assert detail["summary"] is not None, "Expected summary to be non-null"
        s = detail["summary"]
        assert "total_received" in s
        assert "total_paid_out" in s
        assert "open_payables" in s
        assert "deferred_amount" in s
        assert "check_amount" in s
        assert "project_balance" in s

        # All numeric values should be valid decimals
        from decimal import Decimal
        for key in ("total_received", "total_paid_out", "open_payables",
                     "deferred_amount", "check_amount", "project_balance"):
            Decimal(str(s[key]))

        # Lists should exist
        assert isinstance(s.get("vendor_debts"), list)
        assert isinstance(s.get("worker_payables"), list)
