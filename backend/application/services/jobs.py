"""Durable processing job transitions."""

from datetime import UTC, datetime, timedelta

from backend.application.clarification import DEFER_WINDOW_SECONDS
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import ClaimedJob
from backend.application.services.results import ProcessingResult
from backend.domain.enums import JobStatus


async def complete_job(
    uow: UnitOfWork, job_id: str, result: ProcessingResult | None = None, *, owner: str
) -> None:
    waiting = False
    if (
        result is not None
        and result.outcome == "defer"
        and result.defer_reason in {"missing_context", "ambiguous"}
    ):
        waiting = await uow.jobs.wait_for_context(
            job_id, datetime.now(UTC) + timedelta(seconds=DEFER_WINDOW_SECONDS), owner=owner
        )
    if not waiting:
        await uow.jobs.complete(job_id, owner=owner)
    await uow.commit()


async def claim_job(uow: UnitOfWork, owner: str, lease_seconds: int) -> ClaimedJob | None:
    now = datetime.now(UTC)
    job = await uow.jobs.claim_available(owner, now, now + timedelta(seconds=lease_seconds))
    await uow.commit()
    return job


async def fail_job(
    uow: UnitOfWork, job_id: str, error_type: str, *, owner: str, retryable: bool = True
) -> None:
    job = await uow.jobs.get_state(job_id)
    if job is None:
        return
    delay = min(300, 2 ** min(job.attempt_count, 8))
    status = (
        JobStatus.PENDING
        if retryable and job.attempt_count < job.max_attempts and job.model_call_count < 2
        else JobStatus.DEAD
    )
    await uow.jobs.record_failure(
        job_id, status.value, datetime.now(UTC) + timedelta(seconds=delay), error_type, owner=owner
    )
    await uow.commit()
