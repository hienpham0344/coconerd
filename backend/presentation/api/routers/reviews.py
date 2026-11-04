"""Authenticated moderator review and external-effect reconciliation."""

from fastapi import APIRouter, Depends, Query

from backend.application.ports.persistence import UnitOfWork
from backend.application.review_contracts import CorrectMessage, RecoverAction, ResumeTopicSync
from backend.application.services.message_review import correct_message, review_message
from backend.application.services.review_operations import (
    recover_action,
    resume_topic_sync,
    topic_sync_state,
)
from backend.presentation.api.dependencies import ApiDependencies


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/guilds/{guild_id}", tags=["review"], dependencies=dependencies.admin
    )

    @router.get("/messages/{message_id}/review")
    async def get_review(
        guild_id: str, message_id: str, uow: UnitOfWork = Depends(dependencies.get_uow)
    ) -> dict:
        return await review_message(uow, guild_id, message_id)

    @router.post("/messages/{message_id}/corrections")
    async def correct(
        guild_id: str,
        message_id: str,
        body: CorrectMessage,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict:
        return await correct_message(uow, guild_id, message_id, body)

    @router.get("/topics/{topic_id}/sync")
    async def get_sync(
        guild_id: str,
        topic_id: str,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict:
        return await topic_sync_state(uow, guild_id, topic_id, limit, offset)

    @router.post("/topics/{topic_id}/resume-sync")
    async def resume_sync(
        guild_id: str,
        topic_id: str,
        body: ResumeTopicSync,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict:
        return await resume_topic_sync(uow, guild_id, topic_id, body)

    @router.post("/actions/{action_id}/recover")
    async def recover(
        guild_id: str,
        action_id: str,
        body: RecoverAction,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> dict:
        return await recover_action(uow, guild_id, action_id, body)

    return router
