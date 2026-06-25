from inspect import signature
from time import perf_counter

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
from app.models.core import NaturalInputJob, NaturalInputJobStatus
from app.schemas.projects import PendingInterpretationRead


FINAL_JOB_STATUSES = {NaturalInputJobStatus.DONE, NaturalInputJobStatus.FAILED}


def process_natural_input_job(job_id: str, project_id: int, text: str) -> dict:
    db = SessionLocal()
    trace_token = None
    job_token = None
    trace_id = None
    llm_started = False
    llm_finished = False

    try:
        job = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == job_id).one_or_none()
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
        track_event(db=db, trace_id=trace_id, event_name="job.started", payload={"job_id": job_id, "project_id": project_id})
        job_token, trace_token = set_trace_context(job_id, trace_id)
        if job.status == NaturalInputJobStatus.RUNNING:
            track_event(db=db, trace_id=trace_id, event_name="JOB_RECOVERED_FROM_RUNNING", payload={"project_id": project_id, "previous_status": NaturalInputJobStatus.RUNNING.value})
        track_event(db=db, trace_id=trace_id, event_name="JOB_STARTED", payload={"project_id": project_id})
        job.status = NaturalInputJobStatus.RUNNING
        job.error = None
        commit_start = perf_counter()
        db.commit()
        track_event(db=db, trace_id=trace_id, event_name="DB_WRITE_SUCCESS", payload={"project_id": project_id, "status": NaturalInputJobStatus.RUNNING.value}, duration_ms=(perf_counter() - commit_start) * 1000)

        track_event(db=db, trace_id=trace_id, event_name="DOMAIN_ROUTER_START", payload={"project_id": project_id})
        track_event(db=db, trace_id=trace_id, event_name="LLM_STARTED", payload={"project_id": project_id})
        llm_started = True
        pipeline_start = perf_counter()
        request_cache = new_request_cache()
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

        track_event(db=db, trace_id=trace_id, event_name="LLM_COMPLETED", payload={"project_id": project_id, "interpretation_count": len(interpretations), **timings, "pipeline_duration_ms": round(pipeline_duration_ms, 1)}, duration_ms=pipeline_duration_ms)
        llm_finished = True

        result = {
            "interpretations": [
                PendingInterpretationRead.model_validate(interpretation).model_dump(mode="json")
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
        commit_start = perf_counter()
        db.commit()
        track_event(db=db, trace_id=trace_id, event_name="DB_WRITE_SUCCESS", payload={"project_id": project_id, "status": NaturalInputJobStatus.DONE.value}, duration_ms=(perf_counter() - commit_start) * 1000)
        track_event(db=db, trace_id=trace_id, event_name="JOB_COMPLETED", payload={"project_id": project_id, "status": NaturalInputJobStatus.DONE.value})
        track_event(db=db, trace_id=trace_id, event_name="job.completed", payload={
            "job_id": job_id,
            "project_id": project_id,
            "interpretation_count": len(interpretations),
            "pipeline_duration_ms": round(pipeline_duration_ms, 1),
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
            failed_result = dict(job.result or {})
            failed_result.setdefault("_events", [])
            job.result = failed_result
            commit_start = perf_counter()
            db.commit()
            track_event(db=db, trace_id=trace_id, event_name="DB_WRITE_SUCCESS", payload={"project_id": project_id, "status": NaturalInputJobStatus.FAILED.value}, duration_ms=(perf_counter() - commit_start) * 1000)
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


def _failed_llm_result(request_cache) -> dict | None:
    for result in request_cache.llm_results.values():
        if isinstance(result, dict) and result.get("_llm_v2_failed"):
            return result
    return None
