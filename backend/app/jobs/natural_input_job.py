from inspect import signature
from datetime import UTC, datetime, timedelta
from time import perf_counter
import traceback

from sqlalchemy import select, update

from app.core.financial_role_repair import normalize_outgoing_payment_role
from app.core import unified_pipeline
from app.core.observability_service import track_event
from app.core.runtime.request_cache import new_request_cache
from app.core.trace_context import (
    new_trace_id,
    reset_job_id,
    reset_trace_id,
    set_trace_context,
)
from app.db.session import SessionLocal
from app.models.core import (
    NaturalInputJob,
    NaturalInputJobStatus,
    PendingInterpretation,
    PendingInterpretationStatus,
    RawEntry,
    RawEntryStatus,
)
from app.schemas.projects import PendingInterpretationRead
from app.services.financial_reconciliation_service import record_dead_letter_job


FINAL_JOB_STATUSES = {NaturalInputJobStatus.DONE, NaturalInputJobStatus.FAILED}
RUNNING_JOB_RECOVERY_AFTER = timedelta(minutes=15)


def process_natural_input_job(job_id: str, project_id: int, text: str) -> dict:
    db = SessionLocal()
    trace_token = None
    job_token = None
    trace_id = None
    llm_started = False
    llm_finished = False

    try:
        job = db.scalar(
            select(NaturalInputJob)
            .where(NaturalInputJob.job_id == job_id)
            .with_for_update()
        )
        if job is None:
            job = NaturalInputJob(
                job_id=job_id,
                project_id=project_id,
                status=NaturalInputJobStatus.PENDING,
            )
            db.add(job)
            db.flush()
        if job.trace_id is None:
            job.trace_id = new_trace_id()
            db.flush()
        trace_id = job.trace_id
        if job.status in FINAL_JOB_STATUSES:
            return {
                "job_id": job.job_id,
                "status": job.status.value if hasattr(job.status, "value") else job.status,
                "result": job.result,
                "error": job.error,
                "trace_id": job.trace_id,
            }
        recovered_from_running = False
        if job.status == NaturalInputJobStatus.PENDING:
            if not _claim_pending_job(db, job_id):
                db.refresh(job)
                return {
                    "job_id": job.job_id,
                    "status": job.status.value if hasattr(job.status, "value") else job.status,
                    "result": job.result,
                    "error": job.error,
                    "trace_id": job.trace_id,
                }
            db.refresh(job)
        elif job.status == NaturalInputJobStatus.RUNNING:
            recovered_from_running = True
        if recovered_from_running and not _running_job_is_stale(job):
            return {
                "job_id": job.job_id,
                "status": NaturalInputJobStatus.RUNNING.value,
                "result": job.result,
                "error": job.error,
                "trace_id": job.trace_id,
            }
        track_event(db=db, trace_id=trace_id, event_name="job.started", payload={"job_id": job_id, "project_id": project_id})
        job_token, trace_token = set_trace_context(job_id, trace_id)
        if recovered_from_running:
            track_event(db=db, trace_id=trace_id, event_name="JOB_RECOVERED_FROM_RUNNING", payload={"project_id": project_id, "previous_status": NaturalInputJobStatus.RUNNING.value})
        track_event(db=db, trace_id=trace_id, event_name="JOB_STARTED", payload={"project_id": project_id})
        job.error = None
        commit_start = perf_counter()
        db.commit()
        track_event(db=db, trace_id=trace_id, event_name="DB_WRITE_SUCCESS", payload={"project_id": project_id, "status": NaturalInputJobStatus.RUNNING.value}, duration_ms=(perf_counter() - commit_start) * 1000)

        track_event(db=db, trace_id=trace_id, event_name="DOMAIN_ROUTER_START", payload={"project_id": project_id})
        pipeline_start = perf_counter()
        request_cache = new_request_cache()
        interpretations = []
        if recovered_from_running:
            interpretations = _existing_pending_interpretations_for_retry(db, project_id, text)
            if interpretations:
                track_event(
                    db=db,
                    trace_id=trace_id,
                    event_name="JOB_RETRY_REUSED_PENDING_INTERPRETATIONS",
                    payload={"project_id": project_id, "interpretation_count": len(interpretations)},
                )
        if not interpretations:
            interpretations = _process_input_once(db, project_id, text, request_cache)
        failed_llm_result = _failed_llm_result(request_cache)
        if failed_llm_result is not None and not interpretations:
            track_event(db=db, trace_id=trace_id, event_name="LLM_FAILED", payload={"project_id": project_id, "error_message": failed_llm_result.get("reasoning_summary") or "LLM output parsing failed"}, duration_ms=(perf_counter() - pipeline_start) * 1000)
            llm_finished = True
            track_event(db=db, trace_id=trace_id, event_name="LLM_FAILED", payload={"error": failed_llm_result.get("reasoning_summary")})
            raise RuntimeError(
                str(failed_llm_result.get("reasoning_summary") or "LLM output parsing failed")
            )
        pipeline_duration_ms = (perf_counter() - pipeline_start) * 1000

        timings = dict(request_cache.timings_ms)

        if timings.get("llm_v2_duration_ms", 0.0) > 0:
            track_event(db=db, trace_id=trace_id, event_name="LLM_COMPLETED", payload={"project_id": project_id, "interpretation_count": len(interpretations), **timings, "pipeline_duration_ms": round(pipeline_duration_ms, 1)}, duration_ms=pipeline_duration_ms)
        llm_finished = True
        fast_path_payload = _fast_path_payload(interpretations, timings)

        result = {
            "interpretations": [
                normalize_outgoing_payment_role(
                    PendingInterpretationRead.model_validate(interpretation).model_dump(mode="json")
                )
                for interpretation in interpretations
            ]
        }
        db.refresh(job)
        existing_events = list((job.result or {}).get("_events") or [])
        if existing_events:
            result["_events"] = existing_events
        job.status = NaturalInputJobStatus.DONE
        job.result = result
        job.error = None
        raw_entry = _raw_entry_for_job(db, job_id)
        if raw_entry is not None:
            raw_entry.status = RawEntryStatus.PROCESSED
        commit_start = perf_counter()
        db.commit()
        track_event(db=db, trace_id=trace_id, event_name="DB_WRITE_SUCCESS", payload={"project_id": project_id, "status": NaturalInputJobStatus.DONE.value}, duration_ms=(perf_counter() - commit_start) * 1000)
        track_event(db=db, trace_id=trace_id, event_name="JOB_COMPLETED", payload={"project_id": project_id, "status": NaturalInputJobStatus.DONE.value, **fast_path_payload})
        track_event(db=db, trace_id=trace_id, event_name="job.completed", payload={
            "job_id": job_id,
            "project_id": project_id,
            "interpretation_count": len(interpretations),
            "pipeline_duration_ms": round(pipeline_duration_ms, 1),
            **fast_path_payload,
        })
        return {"job_id": job_id, "status": "DONE", "result": result, "trace_id": job.trace_id}

    except Exception as e:
        db.rollback()
        if trace_id is not None and llm_started and not llm_finished:
            track_event(db=db, trace_id=trace_id, event_name="LLM_FAILED", payload={"project_id": project_id, "error_message": str(e)})
            llm_finished = True
        job = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == job_id).one_or_none()
        if job is not None:
            if job.trace_id is None:
                job.trace_id = trace_id or new_trace_id()
            trace_id = job.trace_id
            job.status = NaturalInputJobStatus.FAILED
            job.error = str(e)
            raw_entry = _raw_entry_for_job(db, job_id)
            if raw_entry is not None:
                raw_entry.status = RawEntryStatus.FAILED
            failed_result = dict(job.result or {})
            failed_result.setdefault("_events", [])
            job.result = failed_result
            commit_start = perf_counter()
            db.commit()
            track_event(db=db, trace_id=trace_id, event_name="DB_WRITE_SUCCESS", payload={"project_id": project_id, "status": NaturalInputJobStatus.FAILED.value}, duration_ms=(perf_counter() - commit_start) * 1000)
            record_dead_letter_job(
                db,
                job_id=job_id,
                project_id=project_id,
                payload={"job_id": job_id, "project_id": project_id, "text": text},
                error_trace="".join(traceback.format_exception(type(e), e, e.__traceback__)),
                retry_count=0,
                source="natural_input",
            )
        if trace_id is not None:
            track_event(db=db, trace_id=trace_id, event_name="job.failed", payload={"job_id": job_id, "error": str(e)})
            track_event(db=db, trace_id=trace_id, event_name="ERROR_OCCURRED", payload={"project_id": project_id, "error_message": str(e)})
        return {
            "job_id": job_id,
            "status": "FAILED",
            "error": str(e),
            "trace_id": trace_id,
        }

    finally:
        try:
            db.rollback()
            job = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == job_id).one_or_none()
            if job is not None and job.status not in FINAL_JOB_STATUSES:
                if job.trace_id is None:
                    job.trace_id = trace_id or new_trace_id()
                job.status = NaturalInputJobStatus.FAILED
                job.error = job.error or "job exited before reaching a terminal state"
                db.commit()
                track_event(db=db, trace_id=job.trace_id, event_name="JOB_FORCE_FAILED", payload={"project_id": project_id, "status": NaturalInputJobStatus.FAILED.value})
        except Exception:
            db.rollback()
        if job_token is not None:
            reset_job_id(job_token)
        if trace_token is not None:
            reset_trace_id(trace_token)
        db.close()


def _process_input_once(db, project_id: int, text: str, request_cache):
    process_input = unified_pipeline.process_input
    if "request_cache" in signature(process_input).parameters:
        return process_input(db, project_id, text, request_cache=request_cache)
    return process_input(db, project_id, text)


def _raw_entry_for_job(db, job_id: str) -> RawEntry | None:
    return db.query(RawEntry).filter(RawEntry.job_id == job_id).one_or_none()


def _claim_pending_job(db, job_id: str) -> bool:
    result = db.execute(
        update(NaturalInputJob)
        .where(
            NaturalInputJob.job_id == job_id,
            NaturalInputJob.status == NaturalInputJobStatus.PENDING,
        )
        .values(status=NaturalInputJobStatus.RUNNING, error=None)
    )
    db.commit()
    return result.rowcount == 1


def _running_job_is_stale(job: NaturalInputJob) -> bool:
    updated_at = job.updated_at
    if updated_at is None:
        return True
    if updated_at.tzinfo is not None:
        updated_at = updated_at.astimezone(UTC).replace(tzinfo=None)
    cutoff = datetime.now(UTC).replace(tzinfo=None) - RUNNING_JOB_RECOVERY_AFTER
    return updated_at < cutoff


def _existing_pending_interpretations_for_retry(db, project_id: int, text: str) -> list[PendingInterpretation]:
    return (
        db.query(PendingInterpretation)
        .filter(
            PendingInterpretation.project_id == project_id,
            PendingInterpretation.raw_input_text == text,
            PendingInterpretation.status.in_(
                [PendingInterpretationStatus.PENDING, PendingInterpretationStatus.EDITED]
            ),
        )
        .order_by(PendingInterpretation.id.asc())
        .all()
    )


def _failed_llm_result(request_cache) -> dict | None:
    for result in request_cache.llm_results.values():
        if isinstance(result, dict) and result.get("_llm_v2_failed"):
            return result
    return None


def _fast_path_payload(interpretations: list, timings: dict) -> dict:
    if not interpretations or timings.get("llm_v2_duration_ms", 0.0) > 0:
        return {}
    fast_path_types = {_interpretation_fast_path_type(interpretation) for interpretation in interpretations}
    fast_path_types.discard(None)
    if not fast_path_types:
        return {}
    if len(fast_path_types) == 1:
        return {"fast_path_type": next(iter(fast_path_types)), "skipped_llm": True}
    return {"fast_path_types": sorted(fast_path_types), "skipped_llm": True}


def _interpretation_fast_path_type(interpretation) -> str | None:
    if (
        interpretation.canonical_event_type == "FINANCIAL_EVENT"
        and interpretation.semantic_action == "PAYMENT"
    ):
        return "FINANCIAL_PAYMENT"
    entities = interpretation.extracted_entities or []
    first = entities[0] if entities and isinstance(entities[0], dict) else {}
    updates = first.get("field_updates") if isinstance(first, dict) else None
    if isinstance(updates, dict):
        if updates.get("phone"):
            return "PHONE_UPDATE"
        if updates.get("account_number"):
            return "ACCOUNT_UPDATE"
    return None
