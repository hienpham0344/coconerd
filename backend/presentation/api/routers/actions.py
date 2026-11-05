from dataclasses import asdict

from fastapi import APIRouter, Depends

from backend.application.ports.persistence import UnitOfWork
from backend.application.services import actions
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.schemas import (
    ActionClaimRequest,
    ActionCompletionRequest,
    ActionFailureRequest,
    ActionResponse,
)


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/actions/claim",
        response_model=list[ActionResponse],
        tags=["actions"],
        dependencies=dependencies.bot,
    )
    async def claim_actions(
        body: ActionClaimRequest, uow: UnitOfWork = Depends(dependencies.get_uow)
    ) -> list[ActionResponse]:
        claimed = await actions.claim_actions(
            uow,
            body.worker_id,
            body.limit,
            dependencies.settings.action_lease_seconds,
        )
        return [
            ActionResponse(
                action_id=action.id,
                type=action.action_type,
                topic_id=action.topic_id,
                guild_id=action.guild_id,
                channel_id=action.channel_id,
                payload=action.payload,
                status=action.status,
                lease_token=action.lease_token,
            )
            for action in claimed
        ]

    @router.post(
        "/api/v1/actions/{action_id}/complete",
        tags=["actions"],
        dependencies=dependencies.bot,
    )
    async def complete_action(
        action_id: str,
        body: ActionCompletionRequest,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, str]:
        result = await actions.complete_action(
            uow,
            action_id,
            body.worker_id,
            body.discord_thread_id,
            body.discord_message_id,
            lease_token=body.lease_token,
            previous_discord_thread_id=body.previous_discord_thread_id,
            discord_channel_id=body.discord_channel_id,
        )
        return asdict(result)

    @router.post(
        "/api/v1/actions/{action_id}/fail",
        tags=["actions"],
        dependencies=dependencies.bot,
    )
    async def fail_action(
        action_id: str,
        body: ActionFailureRequest,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict[str, str]:
        result = await actions.fail_action(
            uow,
            action_id,
            body.worker_id,
            body.error_type,
            body.error_message,
            body.retryable,
            lease_token=body.lease_token,
        )
        return asdict(result)

    return router
