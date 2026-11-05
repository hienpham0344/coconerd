from fastapi import APIRouter, Depends, HTTPException, status

from backend.application.errors import ChannelNotAllowedError
from backend.application.ports.persistence import UnitOfWork
from backend.application.services.messages import ingest_message
from backend.domain.entities import ConversationMessage
from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.schemas import (
    MessageIngestRequest,
    MessageIngestResponse,
)


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/messages",
        response_model=MessageIngestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["messages"],
        dependencies=dependencies.bot,
    )
    async def ingest(
        body: MessageIngestRequest,
        uow: UnitOfWork = Depends(dependencies.get_uow),
    ) -> MessageIngestResponse:
        if len(body.content) > dependencies.settings.max_message_length:
            raise HTTPException(status_code=422, detail="Message content exceeds configured limit")
        if len(body.content.encode("utf-8")) > dependencies.settings.max_request_bytes:
            raise HTTPException(status_code=413, detail="Message payload exceeds request limit")
        message = ConversationMessage(
            guild_id=body.guild_id,
            channel_id=body.channel_id,
            message_id=body.message_id,
            author_id=body.author_id,
            author_name=body.author_name,
            content=body.content,
            created_at=body.created_at,
            reply_to_message_id=body.reply_to_message_id,
            attachments=[item.model_dump(mode="json") for item in body.attachments],
        )
        try:
            await ingest_message(
                uow,
                message,
                max_attempts=dependencies.settings.worker_max_attempts,
            )
        except ChannelNotAllowedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return MessageIngestResponse(message_id=body.message_id)

    return router
