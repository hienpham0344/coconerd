import hmac
import math
import time
from collections import OrderedDict, deque

from fastapi import Header, HTTPException, Request, status
from pydantic import SecretStr


class FailedAuthRateLimiter:
    """Bounded in-memory sliding-window guard for invalid API key (401) attempts."""

    def __init__(
        self,
        max_attempts: int = 20,
        window_seconds: float = 60.0,
        max_buckets: int = 1024,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()

    def reset(self) -> None:
        self._attempts.clear()

    def record_failure(self, client_key: str = "global", now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        bucket = self._attempts.get(client_key)
        if bucket is not None:
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            self._attempts.move_to_end(client_key)
        else:
            if len(self._attempts) >= self.max_buckets:
                self._evict_stale_or_oldest(cutoff)
            bucket = deque()
            self._attempts[client_key] = bucket
        bucket.append(current)
        if len(bucket) > self.max_attempts:
            retry_after = max(1, math.ceil(self.window_seconds - (current - bucket[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed authentication attempts",
                headers={"Retry-After": str(retry_after)},
            )

    def _evict_stale_or_oldest(self, cutoff: float) -> None:
        stale_keys = [
            key
            for key, timestamps in self._attempts.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for key in stale_keys:
            self._attempts.pop(key, None)
        while len(self._attempts) >= self.max_buckets:
            self._attempts.popitem(last=False)


failed_auth_limiter = FailedAuthRateLimiter()


def _is_configured(expected: SecretStr | None) -> bool:
    return expected is not None and bool(expected.get_secret_value().strip())


def verify_key(
    expected: SecretStr | None,
    supplied: str | None,
    label: str,
    *,
    client_key: str = "global",
) -> None:
    if expected is None or not expected.get_secret_value().strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} credential is not configured",
        )
    if supplied is None or not hmac.compare_digest(
        expected.get_secret_value().encode("utf-8"), supplied.encode("utf-8")
    ):
        failed_auth_limiter.record_failure(client_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def bot_key_dependency(expected: SecretStr | None):
    async def require_bot_key(
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> None:
        client_host = request.client.host if request.client else "global"
        verify_key(expected, x_api_key, "Bot API", client_key=client_host)

    return require_bot_key


def admin_key_dependency(expected: SecretStr | None):
    async def require_admin_key(
        request: Request,
        x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    ) -> None:
        client_host = request.client.host if request.client else "global"
        verify_key(expected, x_admin_api_key, "Admin API", client_key=client_host)

    return require_admin_key


def bot_or_admin_key_dependency(
    bot_expected: SecretStr | None,
    admin_expected: SecretStr | None,
):
    async def require_bot_or_admin_key(
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    ) -> None:
        client_host = request.client.host if request.client else "global"
        if x_api_key is not None and (x_admin_api_key is None or _is_configured(bot_expected)):
            if (
                bot_expected is not None
                and _is_configured(bot_expected)
                and hmac.compare_digest(
                    bot_expected.get_secret_value().encode("utf-8"),
                    x_api_key.encode("utf-8"),
                )
            ):
                return
            if x_admin_api_key is not None and _is_configured(admin_expected):
                verify_key(admin_expected, x_admin_api_key, "Admin API", client_key=client_host)
                return
            verify_key(bot_expected, x_api_key, "Bot API", client_key=client_host)
            return
        if x_admin_api_key is not None:
            verify_key(admin_expected, x_admin_api_key, "Admin API", client_key=client_host)
            return
        if _is_configured(bot_expected):
            verify_key(bot_expected, None, "Bot API", client_key=client_host)
        elif _is_configured(admin_expected):
            verify_key(admin_expected, None, "Admin API", client_key=client_host)
        else:
            verify_key(bot_expected, None, "Bot API", client_key=client_host)

    return require_bot_or_admin_key
