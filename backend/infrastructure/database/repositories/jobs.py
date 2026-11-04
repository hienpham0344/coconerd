from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.errors import Conflict
from backend.application.read_models import ClaimedJob, JobState
from backend.domain.enums import JobStatus
from backend.infrastructure.database.models import ProcessingJobRecord
from backend.infrastructure.database.repositories.deferred_jobs import DeferredJobs


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve_model_call(self, job_id: str, owner: str) -> bool:
        changed = await self.session.execute(
            update(ProcessingJobRecord)
            .execution_options(synchronize_session=False)
            .where(
                ProcessingJobRecord.id == job_id,
                ProcessingJobRecord.status == "CLAIMED",
                ProcessingJobRecord.lease_owner == owner,
                ProcessingJobRecord.lease_expires_at > datetime.now(UTC),
                ProcessingJobRecord.model_call_count < 2,
            )
            .values(model_call_count=ProcessingJobRecord.model_call_count + 1)
        )
        return changed.rowcount == 1

    async def wait_for_context(self, job_id: str, until: datetime, *, owner: str) -> bool:
        return await DeferredJobs(self.session).wait(job_id, until, owner=owner)

    async def wake_deferred(self, followup_message_id: str) -> None:
        await DeferredJobs(self.session).wake(followup_message_id)

    async def complete(self, job_id: str, *, owner: str) -> None:
        result = await self.session.execute(
            update(ProcessingJobRecord)
            .execution_options(synchronize_session=False)
            .where(
                ProcessingJobRecord.id == job_id,
                ProcessingJobRecord.status == JobStatus.CLAIMED,
                ProcessingJobRecord.lease_owner == owner,
                ProcessingJobRecord.lease_expires_at > datetime.now(UTC),
            )
            .values(
                status=JobStatus.SUCCEEDED, lease_owner=None, lease_expires_at=None, error_type=None
            )
        )
        if result.rowcount != 1:
            raise Conflict("Processing job lease was lost")

    async def get_state(self, job_id: str) -> JobState | None:
        record = await self.session.scalar(
            select(ProcessingJobRecord)
            .where(ProcessingJobRecord.id == job_id)
            .execution_options(populate_existing=True)
        )
        return (
            JobState(record.id, record.attempt_count, record.max_attempts, record.model_call_count)
            if record
            else None
        )

    async def record_failure(
        self, job_id: str, status: str, available_at: datetime, error_type: str, *, owner: str
    ) -> None:
        await self.session.execute(
            update(ProcessingJobRecord)
            .execution_options(synchronize_session=False)
            .where(
                ProcessingJobRecord.id == job_id,
                ProcessingJobRecord.status == JobStatus.CLAIMED,
                ProcessingJobRecord.lease_owner == owner,
                ProcessingJobRecord.lease_expires_at > datetime.now(UTC),
            )
            .values(
                status=status,
                available_at=available_at,
                error_type=error_type,
                lease_owner=None,
                lease_expires_at=None,
            )
        )

    async def claim_available(
        self, owner: str, now: datetime, lease_expires_at: datetime
    ) -> ClaimedJob | None:
        record = await self._claim(owner, now, lease_expires_at)
        if record is None:
            return None
        return ClaimedJob(
            record.id, record.guild_id, record.message_record_id, record.followup_message_id
        )

    async def claim_one_read_model(self, owner: str, lease_seconds: int) -> ClaimedJob | None:
        record = await self.claim_one(owner, lease_seconds)
        if record is None:
            return None
        return ClaimedJob(
            id=record.id,
            guild_id=record.guild_id,
            message_record_id=record.message_record_id,
            followup_message_id=record.followup_message_id,
        )

    async def claim_one(self, owner: str, lease_seconds: int) -> ProcessingJobRecord | None:
        now = datetime.now(UTC)
        return await self._claim(owner, now, now + timedelta(seconds=lease_seconds))

    async def _claim(
        self, owner: str, now: datetime, lease_expires_at: datetime
    ) -> ProcessingJobRecord | None:
        await self.session.execute(
            update(ProcessingJobRecord)
            .execution_options(synchronize_session=False)
            .where(
                ProcessingJobRecord.status == "WAITING",
                ProcessingJobRecord.deferred_until <= now,
            )
            .values(status="SUCCEEDED")
        )
        available = or_(
            ProcessingJobRecord.status == JobStatus.PENDING,
            and_(
                ProcessingJobRecord.status == JobStatus.CLAIMED,
                ProcessingJobRecord.lease_expires_at <= now,
            ),
        )
        job_id = await self.session.scalar(
            select(ProcessingJobRecord.id)
            .where(
                available,
                ProcessingJobRecord.available_at <= now,
                ProcessingJobRecord.attempt_count < ProcessingJobRecord.max_attempts,
            )
            .order_by(ProcessingJobRecord.created_at)
            .limit(1)
        )
        if job_id is None:
            await self.session.execute(
                update(ProcessingJobRecord)
                .execution_options(synchronize_session=False)
                .where(
                    available,
                    ProcessingJobRecord.attempt_count >= ProcessingJobRecord.max_attempts,
                )
                .values(
                    status=JobStatus.DEAD,
                    lease_owner=None,
                    lease_expires_at=None,
                    error_type="LeaseAttemptsExhausted",
                )
            )
            return None
        claim_result = await self.session.execute(
            update(ProcessingJobRecord)
            .execution_options(synchronize_session=False)
            .where(ProcessingJobRecord.id == job_id, available)
            .values(
                status=JobStatus.CLAIMED,
                lease_owner=owner,
                lease_expires_at=lease_expires_at,
                attempt_count=ProcessingJobRecord.attempt_count + 1,
            )
        )
        if claim_result.rowcount != 1:
            return None
        return await self.session.get(ProcessingJobRecord, job_id)
