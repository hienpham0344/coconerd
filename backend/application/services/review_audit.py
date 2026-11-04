"""Idempotency and audit shared by moderator operations."""

import hashlib
import json

from backend.application.errors import Conflict
from backend.application.ports.persistence import UnitOfWork
from backend.application.review_contracts import ReviewCommand


async def replay(
    uow: UnitOfWork, guild_id: str, operation: str, resource_id: str, command: ReviewCommand
) -> tuple[str, dict | None]:
    fingerprint = hashlib.sha256(
        json.dumps(
            [operation, resource_id, command.model_dump(mode="json")],
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    prior = await uow.reviews.event(guild_id, command.request_id)
    if prior and prior["fingerprint"] != fingerprint:
        raise Conflict("request_id was already used with another operation or body")
    return fingerprint, prior["result"] if prior else None


async def record(
    uow: UnitOfWork,
    guild_id: str,
    operation: str,
    resource_id: str,
    command: ReviewCommand,
    fingerprint: str,
    result: dict,
    *,
    message_record_id: str | None = None,
    topic_id: str | None = None,
) -> dict:
    await uow.reviews.add_event(
        guild_id,
        command.request_id,
        fingerprint,
        operation,
        resource_id,
        command.actor,
        command.reason,
        result,
        message_record_id=message_record_id,
        topic_id=topic_id,
    )
    await uow.commit()
    return result
