"""Internal dashboard API. Never expose the administrator key to a browser."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["session", "oauth"]
Key = Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")]


class CredentialBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: str = Field(min_length=1, max_length=16384)
    expires_at: datetime
    expected_payload: str | None = Field(default=None, min_length=1, max_length=16384)


def create_router(repository, dependencies):
    router = APIRouter(
        prefix="/api/v1/admin/web",
        tags=["dashboard"],
        dependencies=dependencies,
    )

    async def require_guild(repo, guild_id):
        guild = await repo.settings(guild_id)
        if guild is None:
            raise HTTPException(404, "Server chưa được cấu hình.")
        return guild

    @router.get("/guilds")
    async def guilds(
        limit: int = Query(200, ge=1, le=200),
        offset: int = Query(0, ge=0),
        repo=Depends(repository),
    ):
        return {"items": await repo.guilds(limit, offset)}

    @router.get("/guilds/{guild_id}/settings")
    async def settings_read(guild_id: str, repo=Depends(repository)):
        return await require_guild(repo, guild_id)

    @router.get("/guilds/{guild_id}/overview")
    async def overview(guild_id: str, repo=Depends(repository)):
        return await repo.overview(guild_id, await require_guild(repo, guild_id))

    @router.get("/guilds/{guild_id}/topics")
    async def topics(
        guild_id: str,
        q: str = Query("", max_length=200),
        status: Literal["ACTIVE", "RESUMED", "DORMANT", "CLOSED"] | None = None,
        limit: int = Query(12, ge=1, le=100),
        offset: int = Query(0, ge=0),
        repo=Depends(repository),
    ):
        await require_guild(repo, guild_id)
        return await repo.topics(guild_id, q, status, limit, offset)

    @router.put("/credentials/{kind}/{key}")
    async def save_credential(kind: Kind, key: Key, body: CredentialBody, repo=Depends(repository)):
        now = datetime.now(UTC)
        ttl = timedelta(hours=12) if kind == "session" else timedelta(minutes=5)
        if body.expires_at.tzinfo is None or not now < body.expires_at <= now + ttl:
            raise HTTPException(422, "Invalid credential expiry")
        if not await repo.save_credential(
            kind, key, body.payload, body.expires_at, body.expected_payload
        ):
            raise HTTPException(409, "Credential changed or revoked")
        return {"status": "saved"}

    @router.get("/credentials/{kind}/{key}")
    async def credential(kind: Kind, key: Key, repo=Depends(repository)):
        result = await repo.credential(kind, key)
        if result is None:
            raise HTTPException(404, "Credential not found")
        return result

    @router.post("/credentials/oauth/{key}/consume")
    async def consume(key: Key, repo=Depends(repository)):
        result = await repo.credential("oauth", key, consume=True)
        if result is None:
            raise HTTPException(404, "Credential not found")
        return result

    @router.delete("/credentials/{kind}/{key}", status_code=204)
    async def remove(kind: Kind, key: Key, repo=Depends(repository)):
        await repo.delete_credential(kind, key)
        return Response(status_code=204)

    return router
