"""Outbox claim, acknowledgement and retry policy."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import ActionResult, ActionState, ClaimedAction


async def claim_actions(
    uow: UnitOfWork, worker_id: str, limit: int, lease_seconds: int
) -> Sequence[ClaimedAction]:
    now = datetime.now(UTC)
    actions = await uow.actions.claim_available(
        worker_id, limit, now, now + timedelta(seconds=lease_seconds)
    )
    await uow.commit()
    return actions


async def _get_action(uow: UnitOfWork, action_id: str) -> ActionState:
    action = await uow.actions.get(action_id)
    if action is None:
        raise NotFound("Action not found")
    return action


def _require_lease(action: ActionState, worker_id: str, lease_token: str | None) -> None:
    if (
        action.status != "CLAIMED"
        or action.lease_owner != worker_id
        or action.lease_token != lease_token
    ):
        raise Conflict("Action is not leased by this worker")


async def complete_action(
    uow: UnitOfWork,
    action_id: str,
    worker_id: str,
    discord_thread_id: str | None,
    discord_message_id: str | None,
    *,
    lease_token: str | None = None,
) -> ActionResult:
    action = await _get_action(uow, action_id)
    if action.status == "SUCCEEDED":
        if (
            action.discord_thread_id == discord_thread_id
            and action.discord_message_id == discord_message_id
        ):
            return ActionResult(action.id, action.status)
        raise Conflict("Action was already completed with another result")
    _require_lease(action, worker_id, lease_token)
    if action.action_type == "CREATE_THREAD" and not discord_thread_id:
        raise InvalidTransition("CREATE_THREAD completion requires discord_thread_id")
    if discord_thread_id:
        topic = await uow.topics.get(action.guild_id, action.topic_id)
        if topic is None or topic.guild_id != action.guild_id:
            raise Conflict("Action topic is inconsistent")
        if (
            action.action_type == "CREATE_THREAD"
            and topic.discord_thread_id
            and topic.discord_thread_id != discord_thread_id
        ):
            raise Conflict("Topic is already mapped to another Discord thread")
    changed = await uow.actions.update_leased(
        action.id,
        worker_id,
        lease_token=lease_token,
        status="SUCCEEDED",
        completed_at=datetime.now(UTC),
        lease_owner=None,
        lease_expires_at=None,
        discord_thread_id=discord_thread_id,
        discord_message_id=discord_message_id,
    )
    if not changed:
        raise Conflict("Action lease was lost")
    if action.action_type == "CREATE_THREAD":
        await uow.topics.set_thread(action.guild_id, action.topic_id, discord_thread_id)
    await uow.commit()
    return ActionResult(action.id, "SUCCEEDED")


async def fail_action(
    uow: UnitOfWork,
    action_id: str,
    worker_id: str,
    error_type: str,
    error_message: str,
    retryable: bool,
    *,
    lease_token: str | None = None,
) -> ActionResult:
    action = await _get_action(uow, action_id)
    _require_lease(action, worker_id, lease_token)
    status = "PENDING" if retryable and action.attempt_count < action.max_attempts else "DEAD"
    changes: dict[str, object] = dict(
        error_type=error_type,
        error_message=error_message,
        lease_owner=None,
        lease_expires_at=None,
        status=status,
    )
    if status == "PENDING":
        changes["available_at"] = datetime.now(UTC) + timedelta(
            seconds=min(300, 2**action.attempt_count)
        )
    if not await uow.actions.update_leased(
        action.id, worker_id, lease_token=lease_token, **changes
    ):
        raise Conflict("Action lease was lost")
    await uow.commit()
    return ActionResult(action.id, status)
