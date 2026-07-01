import queue
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.job_event_bus import job_event_channel, publish_job_event
from app.core.event_tracker import get_trace_events
from app.jobs import natural_input_job
from app.schemas.projects import PendingInterpretationRead
from app.services.llm_v2_interpreter import LLMv2Interpreter
from app.services.domain_router_service import DomainRouterService
from tests.mocks.fake_queue import FakeQueue
from tests.natural_input_helpers import natural_input_interpretation, run_enqueued_natural_input_job
from app.models.core import (
    FinancialDirection,
    NaturalInputJob,
    NaturalInputJobStatus,
    PaymentType,
    PendingInterpretation,
    PendingInterpretationStatus,
    Worker,
    WorkerType,
)


ORIGINAL_LLM_V2_INTERPRET = LLMv2Interpreter.interpret


def _pending_financial(
    project_id: int,
    worker_id: int,
    *,
    amount: str = "300000000",
    direction: FinancialDirection = FinancialDirection.INCOMING,
) -> PendingInterpretation:
    return PendingInterpretation(
        project_id=project_id,
        raw_input_text="میثم 300 میلیون تومان به حساب پروژه واریز کرد",
        canonical_event_type="FINANCIAL_EVENT",
        semantic_action="PAYMENT",
        suggested_entity_id=worker_id,
        matched_input_text="میثم 300 میلیون تومان به حساب پروژه واریز کرد",
        extracted_entities=[{"name": "میثم کبیری", "project_role": "CLIENT"}],
        extracted_amount=amount,
        extracted_quantity=None,
        payment_method=PaymentType.BANK_TRANSFER,
        financial_direction=direction,
        due_date=None,
        description="واریز به حساب پروژه",
        confidence=0.9,
        structured_interpretation=None,
        status=PendingInterpretationStatus.PENDING,
    )


def test_natural_input_endpoint_persists_pending_job(
    client: TestClient,
    monkeypatch,
) -> None:
    fake_queue = FakeQueue()
    monkeypatch.setattr("app.api.projects.get_queue", lambda: fake_queue)
    project = client.post("/projects", json={"name": "jobs"}).json()

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "میثم کبیری کارفرمای پروژه است"},
        headers={"X-Trace-Id": "trace-job-api"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["trace_id"] == "trace-job-api"
    assert fake_queue.jobs[0]["job_id"] == body["job_id"]
    fake_queue.assert_meta_is_valid(0)
    status_response = client.get(f"/natural-input-jobs/{body['job_id']}")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "PENDING"
    assert status_body["result"] is None
    assert status_body["trace_id"] == "trace-job-api"
    assert status_body["events_summary"] == [
        {"event": "JOB_ENQUEUED", "sequence_number": 2, "duration_ms": None}
    ]


def test_account_number_update_job_result_is_entity_update(client: TestClient, monkeypatch) -> None:
    project = _project(client)
    session_factory = client.app.state.testing_session_factory
    db = session_factory()
    try:
        existing = Worker(
            project_id=project["id"],
            name="میثم کبیری",
            type=WorkerType.CLIENT,
        )
        db.add(existing)
        db.commit()
        existing_id = existing.id
    finally:
        db.close()
    monkeypatch.setattr(LLMv2Interpreter, "interpret", ORIGINAL_LLM_V2_INTERPRET)
    monkeypatch.setattr(
        LLMv2Interpreter,
        "_generate",
        lambda self, raw_text, project_id, db=None: {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "The note provides a bank account number for میثم."},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "The note provides a bank account number for میثم.",
        },
    )

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "شماره حساب میثم 6037991234567890"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)
    job = client.get(f"/natural-input-jobs/{job_id}").json()
    interpretation = job["result"]["interpretations"][0]
    entity = interpretation["extracted_entities"][0]
    structured_entity = interpretation["structured_interpretation"]["entities"][0]
    assert interpretation["semantic_action"] == "ENTITY_UPDATE"
    assert interpretation["domain_route"]["ui_mode"] == "EntityUpdateModal"
    assert entity["account_number"] == "6037991234567890"
    assert entity["field_updates"]["account_number"] == "6037991234567890"
    assert entity["candidate_matches"][0]["person_id"] == existing_id
    assert structured_entity["account_number"] == "6037991234567890"
    assert structured_entity["field_updates"]["account_number"] == "6037991234567890"


def test_account_number_update_uses_fast_path_without_llm(client: TestClient, monkeypatch) -> None:
    project = _project(client)

    def fail_llm(*args, **kwargs):
        raise AssertionError("profile update fast path should not call LLM")

    monkeypatch.setattr(LLMv2Interpreter, "interpret", fail_llm)

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "شماره حساب میثم 6037991234567890"},
        headers={"X-Trace-Id": "trace-fast-account"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)
    job = client.get(f"/natural-input-jobs/{job_id}").json()
    interpretation = job["result"]["interpretations"][0]
    entity = interpretation["extracted_entities"][0]
    structured_entity = interpretation["structured_interpretation"]["entities"][0]
    assert interpretation["semantic_action"] == "ENTITY_UPDATE"
    assert interpretation["domain_route"]["domain"] == "ENTITY_UPDATE"
    assert interpretation["domain_route"]["ui_mode"] == "EntityUpdateModal"
    assert entity["field_updates"]["account_number"] == "6037991234567890"
    assert structured_entity["field_updates"]["account_number"] == "6037991234567890"

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        events = get_trace_events("trace-fast-account", db=db)
    event_names = {event.get("event_name") or event.get("event") for event in events}
    fast_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "FAST_PATH_MATCHED")
    assert fast_event["payload"]["fast_path_type"] == "ACCOUNT_UPDATE"
    assert fast_event["payload"]["skipped_llm"] is True
    assert "LLM_STARTED" not in event_names
    assert "OLLAMA_RESPONSE_RECEIVED" not in event_names


def test_new_pending_interpretation_persists_domain_route(client: TestClient, monkeypatch) -> None:
    project = _project(client)

    def fail_llm(*args, **kwargs):
        raise AssertionError("profile update fast path should not call LLM")

    monkeypatch.setattr(LLMv2Interpreter, "interpret", fail_llm)

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "شماره حساب میثم 6037991234567890"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        interpretation = db.query(PendingInterpretation).filter_by(project_id=project["id"]).one()
        assert interpretation.domain_route == {
            "domain": "ENTITY_UPDATE",
            "confidence": 0.95,
            "required_schema": "entity_update_confirmation",
            "ui_mode": "EntityUpdateModal",
        }


def test_schema_returns_stored_domain_route_without_recomputing(client: TestClient, monkeypatch) -> None:
    project = _project(client)
    stored_route = {
        "domain": "NOTE",
        "confidence": 0.44,
        "required_schema": "note_confirmation",
        "ui_mode": "NoteFallback",
    }
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        interpretation = PendingInterpretation(
            project_id=project["id"],
            raw_input_text="از علی 50 میلیون گرفتم",
            canonical_event_type="FINANCIAL_EVENT",
            semantic_action="PAYMENT",
            extracted_amount="50000000",
            domain_route=stored_route,
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(interpretation)
        db.commit()
        db.refresh(interpretation)

        monkeypatch.setattr(
            DomainRouterService,
            "route",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stored route should not be recomputed")),
        )

        body = PendingInterpretationRead.model_validate(interpretation).model_dump(mode="json")

    assert body["domain_route"] == stored_route


def test_old_pending_interpretation_without_domain_route_uses_legacy_schema_fallback(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _project(client)
    legacy_route = {
        "domain": "SETUP",
        "confidence": 0.5,
        "required_schema": "setup_confirmation",
        "ui_mode": "SetupModal",
    }
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        interpretation = PendingInterpretation(
            project_id=project["id"],
            raw_input_text="علی کارفرمای پروژه است",
            canonical_event_type="SETUP_EVENT",
            semantic_action="SET_ROLE",
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(interpretation)
        db.commit()
        db.refresh(interpretation)

        monkeypatch.setattr(DomainRouterService, "route", lambda *args, **kwargs: legacy_route)

        body = PendingInterpretationRead.model_validate(interpretation).model_dump(mode="json")

    assert body["domain_route"] == legacy_route


def test_stored_domain_route_is_immutable_when_semantic_action_changes(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _project(client)
    stored_route = {
        "domain": "SETUP",
        "confidence": 0.9,
        "required_schema": "setup_confirmation",
        "ui_mode": "SetupModal",
    }
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        interpretation = PendingInterpretation(
            project_id=project["id"],
            raw_input_text="علی کارفرمای پروژه است",
            canonical_event_type="SETUP_EVENT",
            semantic_action="SET_ROLE",
            domain_route=stored_route,
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(interpretation)
        db.commit()
        db.refresh(interpretation)
        interpretation.semantic_action = "PAYMENT"

        monkeypatch.setattr(
            DomainRouterService,
            "route",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stored route should not be recomputed")),
        )

        body = PendingInterpretationRead.model_validate(interpretation).model_dump(mode="json")

    assert body["semantic_action"] == "PAYMENT"
    assert body["domain_route"] == stored_route


def test_skilled_worker_project_join_semantics_align_with_router(client: TestClient) -> None:
    project = _project(client)

    for text in (
        "رحمانی گچ کار به پروژه اضافه شد",
        "کاظمی نقاش به پروژه اضافه شد",
        "صادقی کابینت کار به پروژه اضافه شد",
        "علی کارگر به پروژه اضافه شد",
    ):
        interpretation = natural_input_interpretation(client, project["id"], text)
        explanation = interpretation["semantic_explanation"]

        assert interpretation["canonical_event_type"] == "SETUP_EVENT"
        assert interpretation["semantic_action"] == "SETUP"
        assert interpretation["domain_route"]["domain"] == "SETUP"
        assert explanation["event_type"] == "SETUP_EVENT"
        assert explanation["semantic_action"] == "SETUP"
        assert explanation["triggered_rule"] == "SETUP_SKILLED_WORKER_RULE"
        assert explanation["confidence"] >= 0.8


def test_phone_update_job_result_is_entity_update_when_llm_returns_note(client: TestClient, monkeypatch) -> None:
    project = _project(client)
    monkeypatch.setattr(LLMv2Interpreter, "interpret", ORIGINAL_LLM_V2_INTERPRET)
    monkeypatch.setattr(
        LLMv2Interpreter,
        "_generate",
        lambda self, raw_text, project_id, db=None: {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "The note provides a phone number for میثم."},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "The note provides a phone number for میثم.",
        },
    )

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "شماره تماس میثم 09123456789"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)
    job = client.get(f"/natural-input-jobs/{job_id}").json()
    interpretation = job["result"]["interpretations"][0]
    entity = interpretation["extracted_entities"][0]
    assert interpretation["semantic_action"] == "ENTITY_UPDATE"
    assert interpretation["domain_route"]["ui_mode"] == "EntityUpdateModal"
    assert entity["phone"] == "09123456789"
    assert interpretation["structured_interpretation"]["entities"][0]["phone"] == "09123456789"


def test_phone_update_uses_fast_path_without_llm(client: TestClient, monkeypatch) -> None:
    project = _project(client)

    def fail_llm(*args, **kwargs):
        raise AssertionError("profile update fast path should not call LLM")

    monkeypatch.setattr(LLMv2Interpreter, "interpret", fail_llm)

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "شماره تماس میثم 09123456789"},
        headers={"X-Trace-Id": "trace-fast-phone"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)
    job = client.get(f"/natural-input-jobs/{job_id}").json()
    interpretation = job["result"]["interpretations"][0]
    entity = interpretation["extracted_entities"][0]
    structured_entity = interpretation["structured_interpretation"]["entities"][0]
    assert interpretation["semantic_action"] == "ENTITY_UPDATE"
    assert interpretation["domain_route"]["domain"] == "ENTITY_UPDATE"
    assert interpretation["domain_route"]["ui_mode"] == "EntityUpdateModal"
    assert entity["field_updates"]["phone"] == "09123456789"
    assert structured_entity["field_updates"]["phone"] == "09123456789"

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        events = get_trace_events("trace-fast-phone", db=db)
    event_names = {event.get("event_name") or event.get("event") for event in events}
    fast_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "FAST_PATH_MATCHED")
    assert fast_event["payload"]["fast_path_type"] == "PHONE_UPDATE"
    assert fast_event["payload"]["skipped_llm"] is True
    assert "LLM_STARTED" not in event_names
    assert "OLLAMA_RESPONSE_RECEIVED" not in event_names


def test_outgoing_payment_uses_fast_path_without_llm(client: TestClient, monkeypatch) -> None:
    project = _project(client)

    def fail_llm(*args, **kwargs):
        raise AssertionError("financial payment fast path should not call LLM")

    monkeypatch.setattr(LLMv2Interpreter, "interpret", fail_llm)

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "به علی احمدی 5 میلیون دادم"},
        headers={"X-Trace-Id": "trace-fast-payment-out"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)
    job = client.get(f"/natural-input-jobs/{job_id}").json()
    interpretation = job["result"]["interpretations"][0]
    entity = interpretation["extracted_entities"][0]
    structured = interpretation["structured_interpretation"]
    assert job["status"] == "DONE"
    assert len(job["result"]["interpretations"]) == 1
    assert interpretation["canonical_event_type"] == "FINANCIAL_EVENT"
    assert interpretation["semantic_action"] == "PAYMENT"
    assert interpretation["financial_direction"] == "OUTGOING"
    assert interpretation["extracted_amount"] == "5000000.00"
    assert interpretation["payment_method"] != "BANK_TRANSFER"
    assert entity["name"] == "علی احمدی"
    assert entity["project_role"] == "OTHER"
    assert structured["action"] == "PAYMENT_OUT"
    assert structured["entities"][0]["project_role"] == "OTHER"

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        events = get_trace_events("trace-fast-payment-out", db=db)
    event_names = {event.get("event_name") or event.get("event") for event in events}
    fast_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "FAST_PATH_MATCHED")
    completed_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "JOB_COMPLETED")
    assert fast_event["payload"]["fast_path_type"] == "FINANCIAL_PAYMENT"
    assert fast_event["payload"]["skipped_llm"] is True
    assert completed_event["payload"]["fast_path_type"] == "FINANCIAL_PAYMENT"
    assert completed_event["payload"]["skipped_llm"] is True
    assert "LLM_STARTED" not in event_names
    assert "LLM_REQUEST_STARTED" not in event_names
    assert "OLLAMA_RESPONSE_RECEIVED" not in event_names
    assert "LLM_COMPLETED" not in event_names


def test_incoming_payment_uses_fast_path_without_llm(client: TestClient, monkeypatch) -> None:
    project = _project(client)

    def fail_llm(*args, **kwargs):
        raise AssertionError("financial payment fast path should not call LLM")

    monkeypatch.setattr(LLMv2Interpreter, "interpret", fail_llm)

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "میثم 300 میلیون واریز کرد"},
        headers={"X-Trace-Id": "trace-fast-payment-in"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)
    job = client.get(f"/natural-input-jobs/{job_id}").json()
    interpretation = job["result"]["interpretations"][0]
    entity = interpretation["extracted_entities"][0]
    assert job["status"] == "DONE"
    assert interpretation["canonical_event_type"] == "FINANCIAL_EVENT"
    assert interpretation["semantic_action"] == "PAYMENT"
    assert interpretation["financial_direction"] == "INCOMING"
    assert interpretation["extracted_amount"] == "300000000.00"
    assert interpretation["payment_method"] == "BANK_TRANSFER"
    assert entity["name"] == "میثم"
    assert entity["project_role"] == "CLIENT"

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        events = get_trace_events("trace-fast-payment-in", db=db)
    event_names = {event.get("event_name") or event.get("event") for event in events}
    fast_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "FAST_PATH_MATCHED")
    assert fast_event["payload"]["fast_path_type"] == "FINANCIAL_PAYMENT"
    assert fast_event["payload"]["skipped_llm"] is True
    assert "LLM_STARTED" not in event_names
    assert "OLLAMA_RESPONSE_RECEIVED" not in event_names


def test_bank_transfer_wording_uses_bank_transfer_fast_path(client: TestClient, monkeypatch) -> None:
    project = _project(client)

    def fail_llm(*args, **kwargs):
        raise AssertionError("financial payment fast path should not call LLM")

    monkeypatch.setattr(LLMv2Interpreter, "interpret", fail_llm)

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "به علی احمدی 5 میلیون کارت زدم"},
        headers={"X-Trace-Id": "trace-fast-payment-card"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    run_enqueued_natural_input_job(client, job_id)
    job = client.get(f"/natural-input-jobs/{job_id}").json()
    interpretation = job["result"]["interpretations"][0]
    assert job["status"] == "DONE"
    assert interpretation["financial_direction"] == "OUTGOING"
    assert interpretation["extracted_amount"] == "5000000.00"
    assert interpretation["payment_method"] == "BANK_TRANSFER"
    assert interpretation["extracted_entities"][0]["project_role"] == "OTHER"


def test_worker_persists_done_result_and_links_trace_job_id(
    client: TestClient,
    monkeypatch,
) -> None:
    session_factory = client.app.state.testing_session_factory
    monkeypatch.setattr(natural_input_job, "SessionLocal", session_factory)
    db = session_factory()
    try:
        project = _project(client)
        job = NaturalInputJob(
            job_id="job-worker-ok",
            project_id=project["id"],
            trace_id="trace-worker-ok",
            status=NaturalInputJobStatus.PENDING,
        )
        db.add(job)
        db.commit()
    finally:
        db.close()

    def fake_process_input(db, project_id: int, text: str):
        interpretation = PendingInterpretation(
            project_id=project_id,
            raw_input_text=text,
            canonical_event_type="SETUP_EVENT",
            semantic_action="SET_ROLE",
            suggested_entity_id=None,
            matched_input_text=None,
            extracted_entities=[{"name": "میثم کبیری", "type": "CLIENT", "project_role": "CLIENT"}],
            extracted_amount=None,
            extracted_quantity=None,
            payment_method=None,
            financial_direction=None,
            due_date=None,
            description=text,
            confidence=0.9,
            structured_interpretation={"intent": "SET_ROLE", "action": "SET_ROLE"},
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(interpretation)
        db.commit()
        db.refresh(interpretation)
        return [interpretation]

    monkeypatch.setattr(natural_input_job.unified_pipeline, "process_input", fake_process_input)

    result = natural_input_job.process_natural_input_job(
        "job-worker-ok",
        project["id"],
        "میثم کبیری کارفرمای پروژه است",
    )

    assert result["status"] == "DONE"
    db = session_factory()
    try:
        saved = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == "job-worker-ok").one()
        assert saved.status == NaturalInputJobStatus.DONE
        assert saved.error is None
        assert saved.result["interpretations"][0]["semantic_action"] == "SET_ROLE"
    finally:
        db.close()

    events = get_trace_events("trace-worker-ok")
    assert isinstance(events, list)
    status_response = client.get("/natural-input-jobs/job-worker-ok")
    assert status_response.status_code == 200


def test_worker_persists_failed_status(client: TestClient, monkeypatch) -> None:
    session_factory = client.app.state.testing_session_factory
    monkeypatch.setattr(natural_input_job, "SessionLocal", session_factory)
    project = _project(client)
    db = session_factory()
    try:
        db.add(
            NaturalInputJob(
                job_id="job-worker-failed",
                project_id=project["id"],
                status=NaturalInputJobStatus.PENDING,
            )
        )
        db.commit()
    finally:
        db.close()

    def fail_process_input(db, project_id: int, text: str):
        raise RuntimeError("pipeline failed")

    monkeypatch.setattr(natural_input_job.unified_pipeline, "process_input", fail_process_input)

    result = natural_input_job.process_natural_input_job("job-worker-failed", project["id"], "bad")

    assert result["status"] == "FAILED"
    db = session_factory()
    try:
        saved = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == "job-worker-failed").one()
        assert saved.status == NaturalInputJobStatus.FAILED
        assert saved.error == "pipeline failed"
    finally:
        db.close()


def test_worker_emits_llm_failed_and_marks_job_failed_on_llm_parse_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    session_factory = client.app.state.testing_session_factory
    monkeypatch.setattr(natural_input_job, "SessionLocal", session_factory)
    project = _project(client)
    db = session_factory()
    try:
        db.add(
            NaturalInputJob(
                job_id="job-llm-parse-failed",
                project_id=project["id"],
                trace_id="trace-llm-parse-failed",
                status=NaturalInputJobStatus.PENDING,
            )
        )
        db.commit()
    finally:
        db.close()

    def fail_llm_process_input(db, project_id: int, text: str, request_cache):
        request_cache.set_llm_result(
            "llm-key",
            {
                "_llm_v2_failed": True,
                "reasoning_summary": "Ollama output did not contain a valid JSON object",
            },
        )
        return []

    monkeypatch.setattr(natural_input_job, "_process_input_once", fail_llm_process_input)

    result = natural_input_job.process_natural_input_job(
        "job-llm-parse-failed",
        project["id"],
        "شماره تماس میثم 09123456789",
    )

    assert result["status"] == "FAILED"
    assert "valid JSON object" in result["error"]
    events = [event.get("event_name") or event["event"] for event in get_trace_events("trace-llm-parse-failed")]
    assert isinstance(events, list)

    db = session_factory()
    try:
        saved = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == "job-llm-parse-failed").one()
        assert saved.status == NaturalInputJobStatus.FAILED
        assert "valid JSON object" in saved.error
    finally:
        db.close()


def test_jobs_endpoint_returns_db_backed_job_list(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    db = session_factory()
    try:
        db.add(
            NaturalInputJob(
                job_id="job-list",
                project_id=project["id"],
                trace_id="trace-list",
                status=NaturalInputJobStatus.DONE,
                result={
                    "interpretations": [
                        {"semantic_action": "SET_ROLE"},
                        {"semantic_action": "PAYMENT"},
                    ]
                },
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/jobs")

    assert response.status_code == 200
    jobs = response.json()
    listed = next(job for job in jobs if job["job_id"] == "job-list")
    assert listed["project_id"] == project["id"]
    assert listed["status"] == "DONE"
    assert listed["trace_id"] == "trace-list"
    assert listed["result_summary"] == {
        "interpretation_count": 2,
        "semantic_actions": ["SET_ROLE", "PAYMENT"],
    }
    assert "result" not in listed


def test_stale_running_job_is_failed_when_queried(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    stale_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
    db = session_factory()
    try:
        job = NaturalInputJob(
            job_id="job-stale-running",
            project_id=project["id"],
            trace_id="trace-stale-running",
            status=NaturalInputJobStatus.RUNNING,
        )
        db.add(job)
        db.commit()
        job.created_at = stale_time
        job.updated_at = stale_time
        db.commit()
    finally:
        db.close()

    response = client.get("/natural-input-jobs/job-stale-running")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error"] == "Job expired or worker stopped before completion"


def test_entity_update_confirmation_requires_resolved_entity_id(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    db = session_factory()
    try:
        db.add(
            Worker(
                project_id=project["id"],
                name="میثم کبیری",
                type=WorkerType.CLIENT,
            )
        )
        interpretation = PendingInterpretation(
            project_id=project["id"],
            raw_input_text="شماره تماس میثم 09123456789",
            canonical_event_type="SETUP_EVENT",
            semantic_action="ENTITY_UPDATE",
            suggested_entity_id=None,
            matched_input_text=None,
            extracted_entities=[
                {
                    "name": "میثم",
                    "type": "CLIENT",
                    "project_role": "CLIENT",
                    "field_updates": {"phone": "09123456789"},
                }
            ],
            extracted_amount=None,
            extracted_quantity=None,
            payment_method=None,
            financial_direction=None,
            due_date=None,
            description="شماره تماس میثم 09123456789",
            confidence=0.9,
            structured_interpretation={"intent": "SETUP", "action": "UPDATE_ENTITY"},
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(interpretation)
        db.commit()
        db.refresh(interpretation)
        interpretation_id = interpretation.id
    finally:
        db.close()

    response = client.post(
        f"/pending-interpretations/{interpretation_id}/confirm",
        json={},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["status"] == "NEEDS_SELECTION"


def test_entity_update_confirmation_accepts_entity_id_and_updates_selected_person(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    db = session_factory()
    try:
        worker = Worker(
            project_id=project["id"],
            name="میثم کبیری",
            type=WorkerType.CLIENT,
        )
        db.add(worker)
        db.flush()
        interpretation = PendingInterpretation(
            project_id=project["id"],
            raw_input_text="شماره تماس میثم 09123456789",
            canonical_event_type="SETUP_EVENT",
            semantic_action="ENTITY_UPDATE",
            suggested_entity_id=None,
            matched_input_text=None,
            extracted_entities=[
                {
                    "name": "میثم",
                    "type": "CLIENT",
                    "project_role": "CLIENT",
                    "phone": "09123456789",
                    "field_updates": {"phone": "09123456789"},
                    "candidate_matches": [
                        {
                            "person_id": worker.id,
                            "name": "میثم کبیری",
                            "score": 0.7,
                            "match_type": "partial",
                        }
                    ],
                }
            ],
            extracted_amount=None,
            extracted_quantity=None,
            payment_method=None,
            financial_direction=None,
            due_date=None,
            description="شماره تماس میثم 09123456789",
            confidence=0.9,
            structured_interpretation={
                "intent": "SETUP",
                "action": "UPDATE_ENTITY",
                "entities": [
                    {
                        "name": "میثم",
                        "kind": "PERSON",
                        "project_role": "CLIENT",
                        "phone": "09123456789",
                        "field_updates": {"phone": "09123456789"},
                    }
                ],
                "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                "work": {"quantity": None, "unit": None, "description": None},
                "note": {"text": None},
                "confidence": 0.9,
                "ambiguity": False,
                "missing_fields": [],
                "reasoning_summary": "profile update",
            },
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(interpretation)
        db.commit()
        interpretation_id = interpretation.id
        worker_id = worker.id
    finally:
        db.close()

    response = client.post(
        f"/pending-interpretations/{interpretation_id}/confirm",
        json={"entity_id": worker_id, "confirmed": True},
    )

    assert response.status_code == 200
    assert response.json().get("status") != "NEEDS_SELECTION"

    db = session_factory()
    try:
        saved_worker = db.get(Worker, worker_id)
        assert saved_worker is not None
        assert saved_worker.phone == "09123456789"
    finally:
        db.close()


def test_pending_financial_list_confirm_and_remaining_count(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    db = session_factory()
    try:
      worker = Worker(project_id=project["id"], name="میثم کبیری", type=WorkerType.CLIENT)
      db.add(worker)
      db.flush()
      first = _pending_financial(project["id"], worker.id)
      second = _pending_financial(project["id"], worker.id, amount="5000000", direction=FinancialDirection.OUTGOING)
      db.add_all([first, second])
      db.commit()
      first_id = first.id
      second_id = second.id
      worker_id = worker.id
    finally:
      db.close()

    pending_before = client.get(f"/projects/{project['id']}/pending-interpretations")
    assert pending_before.status_code == 200
    pending_ids = {item["id"] for item in pending_before.json()}
    assert {first_id, second_id}.issubset(pending_ids)

    response = client.post(
        f"/pending-interpretations/{first_id}/confirm",
        json={"entity_id": worker_id, "confirmed": True},
    )
    assert response.status_code == 200

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert summary["total_received"] == "300000000.00"

    pending_after = client.get(f"/projects/{project['id']}/pending-interpretations").json()
    remaining_ids = {item["id"] for item in pending_after}
    assert first_id not in remaining_ids
    assert second_id in remaining_ids


def test_discard_pending_financial_has_no_total_side_effect(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    db = session_factory()
    try:
      worker = Worker(project_id=project["id"], name="علی احمدی", type=WorkerType.VENDOR)
      db.add(worker)
      db.flush()
      pending = _pending_financial(project["id"], worker.id, amount="5000000", direction=FinancialDirection.OUTGOING)
      db.add(pending)
      db.commit()
      pending_id = pending.id
    finally:
      db.close()

    before = client.get(f"/projects/{project['id']}/operating-summary").json()
    response = client.post(f"/pending-interpretations/{pending_id}/discard")
    assert response.status_code == 200
    after = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert after["total_paid_out"] == before["total_paid_out"]
    assert after["project_balance"] == before["project_balance"]
    assert client.get(f"/projects/{project['id']}/payments").json() == []
    assert client.get(f"/projects/{project['id']}/pending-interpretations").json() == []


def test_discard_pending_entity_update_has_no_profile_side_effect(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    db = session_factory()
    try:
      worker = Worker(project_id=project["id"], name="میثم کبیری", type=WorkerType.CLIENT)
      db.add(worker)
      db.flush()
      pending = PendingInterpretation(
          project_id=project["id"],
          raw_input_text="شماره تماس میثم 09123456789",
          canonical_event_type="SETUP_EVENT",
          semantic_action="ENTITY_UPDATE",
          suggested_entity_id=worker.id,
          matched_input_text="شماره تماس میثم 09123456789",
          extracted_entities=[{
              "name": "میثم کبیری",
              "type": "CLIENT",
              "project_role": "CLIENT",
              "field_updates": {"phone": "09123456789"},
          }],
          extracted_amount=None,
          extracted_quantity=None,
          payment_method=None,
          financial_direction=None,
          due_date=None,
          description="شماره تماس میثم 09123456789",
          confidence=0.9,
          structured_interpretation={"intent": "SETUP", "action": "UPDATE_ENTITY"},
          status=PendingInterpretationStatus.PENDING,
      )
      db.add(pending)
      db.commit()
      pending_id = pending.id
      worker_id = worker.id
    finally:
      db.close()

    response = client.post(f"/pending-interpretations/{pending_id}/discard")
    assert response.status_code == 200

    workers = client.get(f"/projects/{project['id']}/workers").json()
    assert len(workers) == 1
    assert workers[0]["id"] == worker_id
    assert workers[0]["phone"] is None
    assert client.get(f"/projects/{project['id']}/pending-interpretations").json() == []


def test_publish_job_event_uses_job_channel(monkeypatch) -> None:
    published: list[tuple[str, str]] = []

    class FakeRedis:
        def publish(self, channel: str, payload: str) -> None:
            published.append((channel, payload))

    monkeypatch.setattr("app.core.job_event_bus.get_redis_connection", lambda: FakeRedis())

    publish_job_event("job-pub", {"event": "JOB_STARTED", "job_id": "job-pub"})

    assert published
    assert published[0][0] == job_event_channel("job-pub")
    assert '"event": "JOB_STARTED"' in published[0][1]


def test_job_websocket_stream_forwards_redis_pubsub_events(client: TestClient, monkeypatch) -> None:
    messages: queue.Queue[dict | None] = queue.Queue()

    class FakePubSub:
        pass

    fake_pubsub = FakePubSub()

    def fake_subscribe(job_id: str):
        assert job_id == "job-ws"
        return fake_pubsub

    def fake_read(pubsub, *, timeout: float = 1.0):
        assert pubsub is fake_pubsub
        return messages.get(timeout=timeout)

    closed: list[str] = []

    def fake_close(pubsub, job_id: str) -> None:
        assert pubsub is fake_pubsub
        closed.append(job_id)

    monkeypatch.setattr("app.api.job_websockets.subscribe_job_events", fake_subscribe)
    monkeypatch.setattr("app.api.job_websockets.read_job_event", fake_read)
    monkeypatch.setattr("app.api.job_websockets.close_job_event_subscription", fake_close)

    with client.websocket_connect("/ws/jobs/job-ws") as websocket:
        messages.put(
            {
                "event": "JOB_STARTED",
                "job_id": "job-ws",
                "trace_id": "trace-ws",
                "sequence_number": 1,
                "payload": {"project_id": 1},
            }
        )
        event = websocket.receive_json()

    assert event["event"] == "JOB_STARTED"
    assert event["job_id"] == "job-ws"
    assert event["trace_id"] == "trace-ws"
    assert event["sequence_number"] >= 1
    assert event["payload"]["project_id"] == 1
    assert closed == ["job-ws"]




def test_job_events_http_replay_uses_persisted_job_result_events(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    project = _project(client)
    persisted_events = [
        {
            "event_id": "evt-created",
            "sequence_number": 1,
            "event": "JOB_CREATED",
            "job_id": "job-result-replay",
            "trace_id": "trace-result-replay",
            "timestamp": 1,
            "duration_ms": None,
            "payload": {"project_id": project["id"], "job_id": "job-result-replay"},
            "created_at": 1,
        },
        {
            "event_id": "evt-started",
            "sequence_number": 2,
            "event": "JOB_STARTED",
            "job_id": "job-result-replay",
            "trace_id": "trace-result-replay",
            "timestamp": 2,
            "duration_ms": None,
            "payload": {"project_id": project["id"], "job_id": "job-result-replay"},
            "created_at": 2,
        },
        {
            "event_id": "evt-completed",
            "sequence_number": 3,
            "event": "JOB_COMPLETED",
            "job_id": "job-result-replay",
            "trace_id": "trace-result-replay",
            "timestamp": 3,
            "duration_ms": None,
            "payload": {"project_id": project["id"], "job_id": "job-result-replay"},
            "created_at": 3,
        },
    ]
    db = session_factory()
    try:
        db.add(
            NaturalInputJob(
                job_id="job-result-replay",
                project_id=project["id"],
                trace_id="trace-result-replay",
                status=NaturalInputJobStatus.DONE,
                result={"interpretations": [], "_events": persisted_events},
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/jobs/job-result-replay/events")

    assert response.status_code == 200
    body = response.json()
    assert [event["event"] for event in body["events"]] == [
        "JOB_CREATED",
        "JOB_STARTED",
        "JOB_COMPLETED",
    ]


def _project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "job project"})
    assert response.status_code == 201
    return response.json()
