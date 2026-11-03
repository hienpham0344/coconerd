import hmac

from fastapi import Header, HTTPException, status
from pydantic import SecretStr


def verify_key(expected: SecretStr | None, supplied: str | None, label: str) -> None:
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} credential is not configured",
        )
    if supplied is None or not hmac.compare_digest(expected.get_secret_value(), supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def bot_key_dependency(expected: SecretStr | None):
    async def require_bot_key(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> None:
        verify_key(expected, x_api_key, "Bot API")

    return require_bot_key


def admin_key_dependency(expected: SecretStr | None):
    async def require_admin_key(
        x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    ) -> None:
        verify_key(expected, x_admin_api_key, "Admin API")

    return require_admin_key
