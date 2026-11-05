import hashlib
from datetime import UTC, datetime

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.infrastructure.database.models import ApiRateLimitRecord
from backend.infrastructure.database.statements import conflict_insert


def rate_limit_dependency(
    factory: async_sessionmaker[AsyncSession],
    max_requests: int = 120,
    header_name: str = "X-API-Key",
    scope: str = "",
):
    async def enforce_rate_limit(
        x_api_key: str | None = Header(default=None, alias=header_name),
    ) -> None:
        if not x_api_key:
            return
        now = datetime.now(UTC)
        window = now.replace(second=0, microsecond=0)
        identity = f"{scope}:{x_api_key}" if scope else x_api_key
        fingerprint = hashlib.sha256(identity.encode()).hexdigest()
        async with factory() as session:
            statement = (
                conflict_insert(session, ApiRateLimitRecord)
                .values(client_fingerprint=fingerprint, window_start=window, request_count=1)
                .on_conflict_do_update(
                    index_elements=["client_fingerprint", "window_start"],
                    set_={"request_count": ApiRateLimitRecord.request_count + 1},
                )
                .returning(ApiRateLimitRecord.request_count)
            )
            count = await session.scalar(statement)
            if count is not None and count > max_requests:
                await session.rollback()
                retry_after = 60 - now.second
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Request rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )
            await session.commit()

    return enforce_rate_limit
