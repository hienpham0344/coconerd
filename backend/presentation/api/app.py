import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.services import ChannelNotAllowedError, ingest_message
from backend.config import Settings, get_settings
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import TopicStatus
from backend.domain.exceptions import InvalidTopicTransition
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    DiscordActionRecord,
    EpisodeRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ModelConfigRecord,
    ProcessingJobRecord,
    TopicRecord,
    TopicSummaryRecord,
    WorkerHeartbeatRecord,
)
from backend.infrastructure.database.repositories import ActionRepository, MessageRepository
from backend.presentation.api.rate_limit import rate_limit_dependency
from backend.presentation.api.schemas import (
    ActionClaimRequest,
    ActionCompletionRequest,
    ActionFailureRequest,
    ActionResponse,
    GuildSettingsRequest,
    HealthResponse,
    MessageIngestRequest,
    MessageIngestResponse,
    ModelConfigRequest,
    ModelConfigResponse,
)
from backend.presentation.api.security import admin_key_dependency, bot_key_dependency

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    factory = session_factory or create_session_factory(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await factory.kw["bind"].dispose()

    app = FastAPI(
        title="Discord Autonomous Conversation Organizer API",
        version="1.0.0",
        description="Durable API contract between the Discord bot and the conversation backend.",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.session_factory = factory
    app.state.worker_status = "not_started_in_api_process"
    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["X-API-Key", "X-Admin-API-Key", "Content-Type"],
        )

    @app.middleware("http")
    async def enforce_request_limit(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > app_settings.max_request_bytes
            except ValueError:
                return Response(
                    status_code=400,
                    content="Invalid Content-Length",
                    headers={"X-Request-ID": request_id},
                )
            if too_large:
                return Response(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    headers={"X-Request-ID": request_id},
                )
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > app_settings.max_request_bytes:
                return Response(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    headers={"X-Request-ID": request_id},
                )
            chunks.append(chunk)
        body = b"".join(chunks)
        body_sent = False

        async def replay_body():
            nonlocal body_sent
            if body_sent:
                return {"type": "http.disconnect"}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive=replay_body)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Request-ID"] = request_id
        return response

    async def get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    bot_auth = bot_key_dependency(app_settings.bot_api_key)
    admin_auth = admin_key_dependency(app_settings.admin_api_key)
    bot_dependencies = [Depends(bot_auth), Depends(rate_limit_dependency(factory, 120))]
    admin_dependencies = [
        Depends(admin_auth),
        Depends(rate_limit_dependency(factory, 60, "X-Admin-API-Key")),
    ]

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        try:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.exception(
                "Database health check failed", extra={"error_type": type(exc).__name__}
            )
            return HealthResponse(status="degraded", database="unavailable", worker="unknown")
        cutoff = datetime.now(UTC) - timedelta(
            seconds=max(10, app_settings.worker_poll_seconds * 5)
        )
        async with factory() as session:
            heartbeat = await session.scalar(
                select(WorkerHeartbeatRecord)
                .where(
                    WorkerHeartbeatRecord.status.in_(["running", "idle"]),
                    WorkerHeartbeatRecord.last_seen_at >= cutoff,
                )
                .order_by(WorkerHeartbeatRecord.last_seen_at.desc())
                .limit(1)
            )
        worker_status = "ok" if heartbeat else "unavailable"
        status_text = "ok" if heartbeat else "degraded"
        return HealthResponse(status=status_text, database="ok", worker=worker_status)

    @app.post(
        "/api/v1/messages",
        response_model=MessageIngestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["messages"],
        dependencies=bot_dependencies,
    )
    async def ingest(
        body: MessageIngestRequest,
        session: AsyncSession = Depends(get_session),
    ) -> MessageIngestResponse:
        if len(body.content) > app_settings.max_message_length:
            raise HTTPException(status_code=422, detail="Message content exceeds configured limit")
        if len(body.content.encode("utf-8")) > app_settings.max_request_bytes:
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
        )
        try:
            record, _inserted = await ingest_message(
                session, message, max_attempts=app_settings.worker_max_attempts
            )
        except ChannelNotAllowedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return MessageIngestResponse(message_id=record.discord_message_id)

    @app.put(
        "/api/v1/admin/guilds/{guild_id}/settings",
        tags=["admin"],
        dependencies=admin_dependencies,
    )
    async def set_guild_settings(
        guild_id: str,
        body: GuildSettingsRequest,
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        record = await session.get(GuildSettingsRecord, guild_id)
        if record is None:
            record = GuildSettingsRecord(guild_id=guild_id, enabled=body.enabled)
            session.add(record)
        record.enabled = body.enabled
        record.allowed_channel_ids = body.allowed_channel_ids
        record.retention_days = body.retention_days
        await session.commit()
        return {
            "guild_id": record.guild_id,
            "enabled": record.enabled,
            "allowed_channel_ids": record.allowed_channel_ids,
            "retention_days": record.retention_days,
        }

    @app.put(
        "/api/v1/admin/model-config",
        response_model=ModelConfigResponse,
        tags=["admin"],
        dependencies=admin_dependencies,
    )
    async def set_model_config(
        body: ModelConfigRequest,
        guild_id: str | None = Query(default=None, max_length=100),
        session: AsyncSession = Depends(get_session),
    ) -> ModelConfigResponse:
        scope = "guild" if guild_id else "global"
        record = await session.scalar(
            select(ModelConfigRecord).where(
                ModelConfigRecord.scope == scope,
                ModelConfigRecord.guild_id == guild_id,
            )
        )
        if record is None:
            from uuid import uuid4

            record = ModelConfigRecord(
                id=str(uuid4()),
                scope=scope,
                guild_id=guild_id,
                provider=body.provider,
                model_id=body.model_id,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            )
            session.add(record)
        else:
            record.provider = body.provider
            record.model_id = body.model_id
            record.temperature = body.temperature
            record.max_tokens = body.max_tokens
        await session.commit()
        return ModelConfigResponse(
            scope=record.scope,
            guild_id=record.guild_id,
            provider=record.provider,
            model_id=record.model_id,
            temperature=record.temperature,
            max_tokens=record.max_tokens,
        )

    @app.get(
        "/api/v1/admin/model-config",
        response_model=ModelConfigResponse,
        tags=["admin"],
        dependencies=admin_dependencies,
    )
    async def get_model_config(
        guild_id: str | None = Query(default=None, max_length=100),
        session: AsyncSession = Depends(get_session),
    ) -> ModelConfigResponse:
        record = None
        if guild_id:
            record = await session.scalar(
                select(ModelConfigRecord).where(
                    ModelConfigRecord.scope == "guild", ModelConfigRecord.guild_id == guild_id
                )
            )
        if record is None:
            record = await session.scalar(
                select(ModelConfigRecord).where(
                    ModelConfigRecord.scope == "global", ModelConfigRecord.guild_id.is_(None)
                )
            )
        if record is None:
            record = ModelConfigRecord(
                id="default",
                scope="global",
                guild_id=None,
                provider="meta",
                model_id=app_settings.meta_model_name,
                temperature=app_settings.llm_temperature,
                max_tokens=app_settings.llm_max_tokens,
            )
        return ModelConfigResponse(
            scope=record.scope,
            guild_id=record.guild_id,
            provider=record.provider,
            model_id=record.model_id,
            temperature=record.temperature,
            max_tokens=record.max_tokens,
        )

    @app.post(
        "/api/v1/actions/claim",
        response_model=list[ActionResponse],
        tags=["actions"],
        dependencies=bot_dependencies,
    )
    async def claim_actions(
        body: ActionClaimRequest, session: AsyncSession = Depends(get_session)
    ) -> list[ActionResponse]:
        actions = await ActionRepository(session).claim(
            body.worker_id, body.limit, app_settings.action_lease_seconds
        )
        await session.commit()
        return [
            ActionResponse(
                action_id=action.id,
                type=action.action_type,
                topic_id=action.topic_id,
                guild_id=action.guild_id,
                channel_id=action.channel_id,
                payload=action.payload,
                status=action.status,
            )
            for action in actions
        ]

    @app.post(
        "/api/v1/actions/{action_id}/complete",
        tags=["actions"],
        dependencies=bot_dependencies,
    )
    async def complete_action(
        action_id: str,
        body: ActionCompletionRequest,
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, str]:
        action = await session.get(DiscordActionRecord, action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action.status == "SUCCEEDED":
            if (
                action.discord_thread_id == body.discord_thread_id
                and action.discord_message_id == body.discord_message_id
            ):
                return {"action_id": action.id, "status": action.status}
            raise HTTPException(
                status_code=409, detail="Action was already completed with another result"
            )
        if action.status != "CLAIMED" or action.lease_owner != body.worker_id:
            raise HTTPException(status_code=409, detail="Action is not leased by this worker")
        if action.action_type == "CREATE_THREAD" and not body.discord_thread_id:
            raise HTTPException(
                status_code=422, detail="CREATE_THREAD completion requires discord_thread_id"
            )
        action.status = "SUCCEEDED"
        action.completed_at = datetime.now(UTC)
        action.lease_owner = None
        action.lease_expires_at = None
        action.discord_thread_id = body.discord_thread_id
        action.discord_message_id = body.discord_message_id
        if body.discord_thread_id:
            topic = await session.get(TopicRecord, action.topic_id)
            if topic is None or topic.guild_id != action.guild_id:
                raise HTTPException(status_code=409, detail="Action topic is inconsistent")
            if action.action_type == "CREATE_THREAD":
                topic.discord_thread_id = body.discord_thread_id
        await session.commit()
        return {"action_id": action.id, "status": action.status}

    @app.post(
        "/api/v1/actions/{action_id}/fail",
        tags=["actions"],
        dependencies=bot_dependencies,
    )
    async def fail_action(
        action_id: str,
        body: ActionFailureRequest,
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, str]:
        action = await session.get(DiscordActionRecord, action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action.status != "CLAIMED" or action.lease_owner != body.worker_id:
            raise HTTPException(status_code=409, detail="Action is not leased by this worker")
        action.error_type = body.error_type
        action.error_message = body.error_message
        action.lease_owner = None
        action.lease_expires_at = None
        action.status = (
            "PENDING" if body.retryable and action.attempt_count < action.max_attempts else "DEAD"
        )
        if action.status == "PENDING":
            from datetime import timedelta

            action.available_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**action.attempt_count)
            )
        await session.commit()
        return {"action_id": action.id, "status": action.status}

    @app.get(
        "/api/v1/topics/{topic_id}",
        tags=["topics"],
        dependencies=bot_dependencies,
    )
    async def get_topic(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        topic = await session.scalar(
            select(TopicRecord).where(TopicRecord.id == topic_id, TopicRecord.guild_id == guild_id)
        )
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        return {
            "topic_id": topic.id,
            "guild_id": topic.guild_id,
            "title": topic.title,
            "description": topic.description,
            "status": topic.status,
            "discord_thread_id": topic.discord_thread_id,
            "last_activity": topic.last_activity_at,
        }

    @app.get(
        "/api/v1/topics/{topic_id}/messages",
        tags=["topics"],
        dependencies=bot_dependencies,
    )
    async def get_topic_messages(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        limit: int = Query(default=50, ge=1, le=100),
        before: str | None = Query(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        topic = await session.scalar(
            select(TopicRecord.id).where(
                TopicRecord.id == topic_id, TopicRecord.guild_id == guild_id
            )
        )
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        try:
            before_at = datetime.fromisoformat(before) if before else None
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="before must be an ISO-8601 timestamp"
            ) from exc
        messages = await MessageRepository(session).list_for_topic(
            guild_id, topic_id, limit, before_at
        )
        return {
            "items": [
                {
                    "message_id": message.discord_message_id,
                    "channel_id": message.channel_id,
                    "author_id": message.author_id,
                    "author_name": message.author_name,
                    "content": message.content,
                    "created_at": message.created_at,
                    "reply_to_message_id": message.reply_to_message_id,
                }
                for message in messages
            ],
            "limit": limit,
        }

    @app.get(
        "/api/v1/topics/{topic_id}/summary",
        tags=["topics"],
        dependencies=[Depends(bot_auth)],
    )
    async def get_topic_summary(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        summary = await session.scalar(
            select(TopicSummaryRecord)
            .where(TopicSummaryRecord.guild_id == guild_id, TopicSummaryRecord.topic_id == topic_id)
            .order_by(TopicSummaryRecord.version.desc())
            .limit(1)
        )
        if summary is None:
            raise HTTPException(status_code=404, detail="Topic summary not found")
        return {
            **summary.data,
            "version": summary.version,
            "source_message_ids": summary.source_message_ids,
        }

    @app.delete(
        "/api/v1/admin/guilds/{guild_id}/data",
        tags=["admin"],
        dependencies=admin_dependencies,
    )
    async def delete_guild_data(
        guild_id: str, session: AsyncSession = Depends(get_session)
    ) -> dict[str, str]:
        topic_ids = select(TopicRecord.id).where(TopicRecord.guild_id == guild_id)
        message_ids = select(MessageRecord.id).where(MessageRecord.guild_id == guild_id)
        await session.execute(
            delete(ProcessingJobRecord).where(ProcessingJobRecord.guild_id == guild_id)
        )
        await session.execute(
            delete(DiscordActionRecord).where(DiscordActionRecord.guild_id == guild_id)
        )
        await session.execute(
            delete(TopicSummaryRecord).where(TopicSummaryRecord.guild_id == guild_id)
        )
        await session.execute(delete(EpisodeRecord).where(EpisodeRecord.guild_id == guild_id))
        await session.execute(
            delete(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.guild_id == guild_id
            )
        )
        await session.execute(delete(AIDecisionRecord).where(AIDecisionRecord.guild_id == guild_id))
        await session.execute(delete(TopicRecord).where(TopicRecord.id.in_(topic_ids)))
        await session.execute(delete(MessageRecord).where(MessageRecord.id.in_(message_ids)))
        await session.execute(
            delete(GuildSettingsRecord).where(GuildSettingsRecord.guild_id == guild_id)
        )
        await session.execute(
            delete(ModelConfigRecord).where(ModelConfigRecord.guild_id == guild_id)
        )
        await session.commit()
        return {"guild_id": guild_id, "status": "deleted"}

    @app.post(
        "/api/v1/admin/topics/{topic_id}/close",
        tags=["admin"],
        dependencies=admin_dependencies,
    )
    async def close_topic(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, str]:
        topic = await session.scalar(
            select(TopicRecord).where(TopicRecord.id == topic_id, TopicRecord.guild_id == guild_id)
        )
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        lifecycle = ConversationTopic.create(topic.guild_id, topic.title)
        lifecycle.status = TopicStatus(topic.status)
        try:
            lifecycle.close()
        except InvalidTopicTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        topic.status = lifecycle.status.value
        await session.commit()
        return {"topic_id": topic_id, "status": "CLOSED"}

    @app.delete(
        "/api/v1/admin/topics/{topic_id}",
        tags=["admin"],
        dependencies=[Depends(admin_auth)],
    )
    async def delete_topic(
        topic_id: str,
        guild_id: str = Query(min_length=1, max_length=100),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, str]:
        topic = await session.scalar(
            select(TopicRecord).where(TopicRecord.id == topic_id, TopicRecord.guild_id == guild_id)
        )
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        message_record_ids = select(MessageTopicAssociationRecord.message_record_id).where(
            MessageTopicAssociationRecord.guild_id == guild_id,
            MessageTopicAssociationRecord.topic_id == topic_id,
        )
        await session.execute(
            delete(DiscordActionRecord).where(
                DiscordActionRecord.guild_id == guild_id, DiscordActionRecord.topic_id == topic_id
            )
        )
        await session.execute(
            delete(ProcessingJobRecord).where(
                ProcessingJobRecord.message_record_id.in_(message_record_ids)
            )
        )
        await session.execute(
            delete(AIDecisionRecord).where(
                AIDecisionRecord.message_record_id.in_(message_record_ids)
            )
        )
        await session.execute(delete(MessageRecord).where(MessageRecord.id.in_(message_record_ids)))
        await session.execute(
            delete(TopicSummaryRecord).where(
                TopicSummaryRecord.guild_id == guild_id, TopicSummaryRecord.topic_id == topic_id
            )
        )
        await session.execute(
            delete(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.guild_id == guild_id,
                MessageTopicAssociationRecord.topic_id == topic_id,
            )
        )
        await session.execute(
            delete(EpisodeRecord).where(
                EpisodeRecord.guild_id == guild_id, EpisodeRecord.topic_id == topic_id
            )
        )
        await session.delete(topic)
        await session.commit()
        return {"topic_id": topic_id, "status": "deleted"}

    return app


app = create_app()
