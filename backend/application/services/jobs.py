"""Durable processing job transitions."""

from datetime import UTC, datetime, timedelta

from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import ClaimedJob
from backend.domain.enums import JobStatus


async def complete_job(uow: UnitOfWork, job_id: str) -> None:
    await uow.jobs.complete(job_id)
    await uow.commit()


async def claim_job(uow: UnitOfWork, owner: str, lease_seconds: int) -> ClaimedJob | None:
    now = datetime.now(UTC)
    job = await uow.jobs.claim_available(owner, now, now + timedelta(seconds=lease_seconds))
    await uow.commit()
    return job


async def fail_job(uow: UnitOfWork, job_id: str, error_type: str) -> None:
    job = await uow.jobs.get_state(job_id)
    if job is None:
        return
    delay = min(300, 2 ** min(job.attempt_count, 8))
    status = JobStatus.PENDING if job.attempt_count < job.max_attempts else JobStatus.DEAD
    await uow.jobs.record_failure(
        job_id, status.value, datetime.now(UTC) + timedelta(seconds=delay), error_type
    )
    await uow.commit()
