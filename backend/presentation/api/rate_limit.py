import hashlib
from datetime import UTC, datetime

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.infrastructure.database.models import ApiRateLimitRecord
from backend.infrastructure.database.statements import conflict_insert
from backend.presentation.api.security import FailedAuthRateLimiter, failed_auth_limiter

__all__ = ["FailedAuthRateLimiter", "failed_auth_limiter", "rate_limit_dependency"]


async def _consume_rate_limit(
    factory: async_sessionmaker[AsyncSession],
    api_key: str,
    max_requests: int,
    scope: str = "",
) -> None:
    now = datetime.now(UTC)
    window = now.replace(second=0, microsecond=0)
    identity = f"{scope}:{api_key}" if scope else api_key
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


def rate_limit_dependency(
    factory: async_sessionmaker[AsyncSession],
    max_requests: int = 120,
    header_name: str = "X-API-Key",
    scope: str = "",
    fallback_max_requests: int = 60,
):
    if scope.startswith("X-"):
        fallback_header_name = scope

        async def enforce_dual_rate_limit(
            x_api_key: str | None = Header(default=None, alias=header_name),
            x_admin_api_key: str | None = Header(default=None, alias=fallback_header_name),
        ) -> None:
            if x_api_key:
                await _consume_rate_limit(factory, x_api_key, max_requests)
            elif x_admin_api_key:
                await _consume_rate_limit(factory, x_admin_api_key, fallback_max_requests)

        return enforce_dual_rate_limit

    async def enforce_rate_limit(
        x_api_key: str | None = Header(default=None, alias=header_name),
    ) -> None:
        if not x_api_key:
            return
        await _consume_rate_limit(factory, x_api_key, max_requests, scope=scope)

    return enforce_rate_limit
