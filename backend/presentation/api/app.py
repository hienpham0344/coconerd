import html
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.application.services import ChannelNotAllowedError, ingest_message
from backend.config import Settings, get_settings
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import TopicStatus
from backend.domain.exceptions import InvalidTopicTransition
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    Base,
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
    MessageBatchIngestRequest,
    MessageBatchIngestResponse,
    MessageIngestRequest,
    MessageIngestResponse,
    ModelConfigRequest,
    ModelConfigResponse,
    TopicThreadMappingRequest,
    TopicThreadMappingResponse,
)
from backend.presentation.api.security import admin_key_dependency, bot_key_dependency, verify_key

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    factory = session_factory or create_session_factory(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with factory.kw["bind"].begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
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

    class RequestLimitMiddleware:
        def __init__(self, inner_app: ASGIApp, max_request_bytes: int):
            self.inner_app = inner_app
            self.max_request_bytes = max_request_bytes

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.inner_app(scope, receive, send)
                return

            request_id = None
            content_length_str = None
            for key, value in scope.get("headers", []):
                key_lower = key.lower()
                if key_lower == b"x-request-id":
                    request_id = value.decode("latin1", errors="replace")
                elif key_lower == b"content-length":
                    content_length_str = value.decode("latin1", errors="replace")

            if not request_id:
                request_id = str(uuid4())

            scope.setdefault("state", {})["request_id"] = request_id

            if content_length_str:
                try:
                    too_large = int(content_length_str) > self.max_request_bytes
                except ValueError:
                    response = Response(
                        status_code=400,
                        content="Invalid Content-Length",
                        headers={"X-Request-ID": request_id, "X-Content-Type-Options": "nosniff"},
                    )
                    await response(scope, receive, send)
                    return
                if too_large:
                    response = Response(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        headers={"X-Request-ID": request_id, "X-Content-Type-Options": "nosniff"},
                    )
                    await response(scope, receive, send)
                    return

            messages: list[Message] = []
            total_bytes = 0
            more_body = True
            while more_body:
                message = await receive()
                messages.append(message)
                if message["type"] == "http.request":
                    chunk = message.get("body", b"")
                    total_bytes += len(chunk)
                    if total_bytes > self.max_request_bytes:
                        response = Response(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            headers={"X-Request-ID": request_id, "X-Content-Type-Options": "nosniff"},
                        )
                        await response(scope, receive, send)
                        return
                    more_body = message.get("more_body", False)
                elif message["type"] == "http.disconnect":
                    return

            message_queue = list(messages)

            async def replay_receive() -> Message:
                if message_queue:
                    return message_queue.pop(0)
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send_wrapper(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers["X-Content-Type-Options"] = "nosniff"
                    headers["X-Request-ID"] = request_id
                await send(message)

            await self.inner_app(scope, replay_receive, send_wrapper)

    app.add_middleware(RequestLimitMiddleware, max_request_bytes=app_settings.max_request_bytes)

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

    @app.post(
        "/api/v1/messages/batch",
        response_model=MessageBatchIngestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["messages"],
        dependencies=bot_dependencies,
    )
    async def ingest_batch(
        body: MessageBatchIngestRequest,
        session: AsyncSession = Depends(get_session),
    ) -> MessageBatchIngestResponse:
        accepted_ids = []
        for msg_in in body.messages:
            if len(msg_in.content) > app_settings.max_message_length:
                continue
            message = ConversationMessage(
                guild_id=msg_in.guild_id,
                channel_id=msg_in.channel_id,
                message_id=msg_in.message_id,
                author_id=msg_in.author_id,
                author_name=msg_in.author_name,
                content=msg_in.content,
                created_at=msg_in.created_at,
                reply_to_message_id=msg_in.reply_to_message_id,
            )
            try:
                record, _ = await ingest_message(
                    session, message, max_attempts=app_settings.worker_max_attempts
                )
                accepted_ids.append(record.discord_message_id)
            except ChannelNotAllowedError:
                continue
        return MessageBatchIngestResponse(accepted=len(accepted_ids), message_ids=accepted_ids)

    @app.get(
        "/api/v1/guilds/{guild_id}/settings",
        tags=["guilds"],
        dependencies=bot_dependencies,
    )
    async def get_guild_settings_for_bot(
        guild_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        record = await session.get(GuildSettingsRecord, guild_id)
        if record is None:
            return {
                "guild_id": guild_id,
                "enabled": False,
                "allowed_channel_ids": [],
                "output_channel_id": None,
                "retention_days": 365,
            }
        return {
            "guild_id": record.guild_id,
            "enabled": record.enabled,
            "allowed_channel_ids": record.allowed_channel_ids or [],
            "output_channel_id": record.output_channel_id,
            "retention_days": record.retention_days,
        }

    @app.put(
        "/api/v1/guilds/{guild_id}/settings",
        tags=["guilds"],
        dependencies=bot_dependencies,
    )
    async def update_guild_settings_for_bot(
        guild_id: str,
        body: GuildSettingsRequest,
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        logger.info("Updating guild settings via bot API: guild_id=%s, enabled=%s", guild_id, body.enabled)
        record = await session.get(GuildSettingsRecord, guild_id)
        if record is None:
            record = GuildSettingsRecord(guild_id=guild_id, enabled=body.enabled)
            session.add(record)
        record.enabled = body.enabled
        record.allowed_channel_ids = body.allowed_channel_ids
        record.output_channel_id = body.output_channel_id
        record.retention_days = body.retention_days
        record.updated_at = datetime.now(UTC)
        await session.commit()
        return {
            "guild_id": record.guild_id,
            "enabled": record.enabled,
            "allowed_channel_ids": record.allowed_channel_ids,
            "output_channel_id": record.output_channel_id,
            "retention_days": record.retention_days,
        }

    @app.get(
        "/api/v1/admin/guilds/{guild_id}/settings",
        tags=["admin"],
        dependencies=admin_dependencies,
    )
    async def get_admin_guild_settings(
        guild_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        record = await session.get(GuildSettingsRecord, guild_id)
        if record is None:
            return {
                "guild_id": guild_id,
                "enabled": False,
                "allowed_channel_ids": [],
                "output_channel_id": None,
                "retention_days": 365,
            }
        return {
            "guild_id": record.guild_id,
            "enabled": record.enabled,
            "allowed_channel_ids": record.allowed_channel_ids or [],
            "output_channel_id": record.output_channel_id,
            "retention_days": record.retention_days,
        }

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
        logger.info("Updating guild settings via admin API: guild_id=%s, enabled=%s", guild_id, body.enabled)
        record = await session.get(GuildSettingsRecord, guild_id)
        if record is None:
            record = GuildSettingsRecord(guild_id=guild_id, enabled=body.enabled)
            session.add(record)
        record.enabled = body.enabled
        record.allowed_channel_ids = body.allowed_channel_ids
        record.output_channel_id = body.output_channel_id
        record.retention_days = body.retention_days
        record.updated_at = datetime.now(UTC)
        await session.commit()
        return {
            "guild_id": record.guild_id,
            "enabled": record.enabled,
            "allowed_channel_ids": record.allowed_channel_ids,
            "output_channel_id": record.output_channel_id,
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
                provider="groq" if app_settings.ai_provider == "groq" else "meta",
                model_id=app_settings.groq_model if app_settings.ai_provider == "groq" else app_settings.meta_model_name,
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
        response_items: list[ActionResponse] = []
        for action in actions:
            thread_id = action.discord_thread_id
            if not thread_id and action.topic_id:
                topic = await session.get(TopicRecord, action.topic_id)
                if topic:
                    thread_id = topic.discord_thread_id
            response_items.append(
                ActionResponse(
                    action_id=action.id,
                    type=action.action_type,
                    topic_id=action.topic_id,
                    guild_id=action.guild_id,
                    channel_id=action.channel_id,
                    payload=action.payload,
                    status=action.status,
                    discord_thread_id=thread_id,
                )
            )
        return response_items

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
                if topic.discord_thread_id and topic.discord_thread_id != body.discord_thread_id:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Topic already has a different discord_thread_id: {topic.discord_thread_id}",
                    )
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
            action.available_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**action.attempt_count)
            )
        await session.commit()
        return {"action_id": action.id, "status": action.status}

    @app.get(
        "/api/v1/topics",
        tags=["topics"],
        dependencies=bot_dependencies,
    )
    async def list_topics(
        guild_id: str = Query(min_length=1, max_length=100),
        channel_id: str | None = Query(default=None, max_length=100),
        include_closed: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=100),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        stmt = select(TopicRecord).where(TopicRecord.guild_id == guild_id)
        if channel_id:
            stmt = stmt.where(TopicRecord.channel_id == channel_id)
        if not include_closed:
            stmt = stmt.where(
                TopicRecord.status.in_(
                    [TopicStatus.ACTIVE, TopicStatus.DORMANT, TopicStatus.RESUMED]
                )
            )
        stmt = stmt.order_by(TopicRecord.last_activity_at.desc()).limit(limit)
        records = (await session.scalars(stmt)).all()

        topic_ids = [t.id for t in records]
        counts: dict[str, int] = {}
        if topic_ids:
            count_stmt = (
                select(
                    MessageTopicAssociationRecord.topic_id,
                    func.count(MessageTopicAssociationRecord.id),
                )
                .where(
                    MessageTopicAssociationRecord.guild_id == guild_id,
                    MessageTopicAssociationRecord.topic_id.in_(topic_ids),
                )
                .group_by(MessageTopicAssociationRecord.topic_id)
            )
            count_rows = (await session.execute(count_stmt)).all()
            counts = {row[0]: row[1] for row in count_rows}

        return {
            "items": [
                {
                    "topic_id": t.id,
                    "channel_id": t.channel_id,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "discord_thread_id": t.discord_thread_id,
                    "last_activity": t.last_activity_at.isoformat() if t.last_activity_at else None,
                    "message_count": counts.get(t.id, 0),
                }
                for t in records
            ]
        }

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
            "channel_id": topic.channel_id,
            "title": topic.title,
            "description": topic.description,
            "status": topic.status,
            "discord_thread_id": topic.discord_thread_id,
            "last_activity": topic.last_activity_at.isoformat() if topic.last_activity_at else None,
        }

    @app.put(
        "/api/v1/topics/{topic_id}/thread",
        response_model=TopicThreadMappingResponse,
        tags=["topics"],
        dependencies=bot_dependencies,
    )
    async def set_topic_thread(
        topic_id: str,
        body: TopicThreadMappingRequest,
        session: AsyncSession = Depends(get_session),
    ) -> TopicThreadMappingResponse:
        topic = await session.scalar(
            select(TopicRecord).where(
                TopicRecord.id == topic_id, TopicRecord.guild_id == body.guild_id
            )
        )
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        if topic.channel_id != body.channel_id:
            raise HTTPException(
                status_code=409,
                detail=f"Channel mismatch: topic belongs to {topic.channel_id}, got {body.channel_id}",
            )
        if topic.discord_thread_id and topic.discord_thread_id != body.discord_thread_id:
            raise HTTPException(
                status_code=409,
                detail=f"Topic already mapped to different thread {topic.discord_thread_id}",
            )
        topic.discord_thread_id = body.discord_thread_id
        await session.commit()
        return TopicThreadMappingResponse(
            status="ok",
            topic_id=topic.id,
            guild_id=topic.guild_id,
            channel_id=topic.channel_id,
            discord_thread_id=topic.discord_thread_id,
        )

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
                    "created_at": message.created_at.isoformat() if message.created_at else None,
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
        channel_id: str | None = Query(default=None, max_length=100),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        topic = await session.scalar(
            select(TopicRecord).where(
                TopicRecord.id == topic_id, TopicRecord.guild_id == guild_id
            )
        )
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        if channel_id and topic.channel_id and topic.channel_id != channel_id:
            raise HTTPException(status_code=404, detail="Topic not found in this channel")

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
            "topic_id": topic.id,
            "title": topic.title,
            "status": topic.status,
            "channel_id": topic.channel_id,
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
        lifecycle = ConversationTopic.create(topic.guild_id, topic.title, channel_id=topic.channel_id)
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

    # =========================================================================
    # Dashboard Setup UI (/setup/{guild_id})
    # =========================================================================
    @app.get("/setup/{guild_id}", response_class=HTMLResponse, tags=["dashboard"])
    @app.get("/dashboard/setup/{guild_id}", response_class=HTMLResponse, tags=["dashboard"])
    async def setup_dashboard_view(
        guild_id: str,
        admin_key: str | None = Query(default=None),
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        record = await session.get(GuildSettingsRecord, guild_id)
        enabled = record.enabled if record else True
        allowed_channels = ",".join(record.allowed_channel_ids) if record and record.allowed_channel_ids else ""
        output_channel = record.output_channel_id or "" if record else ""
        retention = record.retention_days if record else 365
        default_admin_key = ""

        page_html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🥥 Coconerd Setup Dashboard</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --border: #334155;
            --accent: #38bdf8;
            --accent-hover: #0284c7;
            --text: #f8fafc;
            --text-dim: #94a3b8;
            --success: #22c55e;
            --danger: #ef4444;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            max-width: 620px;
            width: 100%;
            padding: 32px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4);
        }}
        .header {{
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 24px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
        }}
        .logo {{ font-size: 44px; }}
        h1 {{ font-size: 22px; font-weight: 700; color: #fff; }}
        p.subtitle {{ font-size: 14px; color: var(--text-dim); margin-top: 4px; }}
        .badge {{
            display: inline-block;
            background: #0284c722;
            color: var(--accent);
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            margin-top: 6px;
            font-family: monospace;
        }}
        .form-group {{ margin-bottom: 20px; }}
        label {{
            display: block;
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-dim);
            margin-bottom: 8px;
        }}
        .hint {{
            font-size: 12px;
            color: #64748b;
            margin-top: 5px;
        }}
        input[type="text"], input[type="password"], input[type="number"], textarea {{
            width: 100%;
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text);
            font-size: 14px;
            outline: none;
            transition: border-color 0.15s;
        }}
        input:focus, textarea:focus {{
            border-color: var(--accent);
        }}
        .checkbox-row {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 20px;
            cursor: pointer;
        }}
        .checkbox-row input {{
            width: 18px;
            height: 18px;
            accent-color: var(--accent);
            cursor: pointer;
        }}
        .btn {{
            width: 100%;
            background: var(--accent);
            color: #0f172a;
            font-weight: 700;
            font-size: 15px;
            border: none;
            border-radius: 8px;
            padding: 12px;
            cursor: pointer;
            transition: background 0.15s;
            margin-top: 10px;
        }}
        .btn:hover {{ background: var(--accent-hover); }}
        .btn:disabled {{ opacity: 0.6; cursor: not-allowed; }}
        #banner {{
            display: none;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 14px;
            margin-bottom: 20px;
            font-weight: 500;
        }}
        #banner.success {{ display: block; background: #052e16; color: #4ade80; border: 1px solid #166534; }}
        #banner.error {{ display: block; background: #450a0a; color: #f87171; border: 1px solid #991b1b; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <div class="logo">🥥</div>
            <div>
                <h1>Coconerd Guild Setup</h1>
                <p class="subtitle">Cấu hình kênh theo dõi và kênh tổng hợp cho máy chủ Discord</p>
                <div class="badge">GUILD ID: {html.escape(guild_id)}</div>
            </div>
        </div>

        <div id="banner"></div>

        <form id="setupForm" method="POST" action="/setup/{html.escape(guild_id)}">
            <div class="form-group">
                <label for="adminKey">Admin API Key</label>
                <input type="password" id="adminKey" name="admin_key" value="{html.escape(default_admin_key)}" placeholder="Nhập COCONERD_ADMIN_API_KEY..." required>
                <div class="hint">Khóa quản trị Backend (COCONERD_ADMIN_API_KEY).</div>
            </div>

            <div class="checkbox-row">
                <input type="checkbox" id="enabled" name="enabled" value="true" {"checked" if enabled else ""}>
                <label for="enabled" style="margin:0; text-transform:none; font-size:14px; color:var(--text); cursor:pointer;">
                    Kích hoạt Coconerd cho máy chủ này (Enabled)
                </label>
            </div>

            <div class="form-group">
                <label for="allowedChannels">Input Channels (Kênh theo dõi)</label>
                <input type="text" id="allowedChannels" name="allowed_channels" value="{html.escape(allowed_channels)}" placeholder="1234567890, 9876543210">
                <div class="hint">Danh sách Channel ID mà Bot được phép đọc tin nhắn, cách nhau bởi dấu phẩy.</div>
            </div>

            <div class="form-group">
                <label for="outputChannel">Output Channel (Kênh xuất thông báo / Topic)</label>
                <input type="text" id="outputChannel" name="output_channel" value="{html.escape(output_channel)}" placeholder="1234567890">
                <div class="hint">Channel ID nơi Bot sẽ tự động tạo Thread và gửi thông báo tổng hợp Topic mới.</div>
            </div>

            <div class="form-group">
                <label for="retentionDays">Data Retention (Số ngày lưu trữ)</label>
                <input type="number" id="retentionDays" name="retention_days" value="{retention}" min="1" max="3650">
            </div>

            <button type="submit" class="btn" id="saveBtn">Lưu Cấu Hình</button>
        </form>
    </div>

    <script>
        const form = document.getElementById("setupForm");
        const banner = document.getElementById("banner");
        const saveBtn = document.getElementById("saveBtn");

        function showMessage(type, text) {{
            banner.className = type;
            banner.innerText = text;
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
        }}

        form.addEventListener("submit", async (e) => {{
            e.preventDefault();
            saveBtn.disabled = true;
            saveBtn.innerText = "Đang lưu cấu hình...";

            const adminKey = document.getElementById("adminKey").value.trim();
            const enabled = document.getElementById("enabled").checked;
            const rawChannels = document.getElementById("allowedChannels").value.trim();
            const outputChannel = document.getElementById("outputChannel").value.trim();
            const retentionDays = parseInt(document.getElementById("retentionDays").value, 10) || 365;

            const allowedChannelIds = rawChannels
                ? rawChannels.split(",").map(s => s.trim()).filter(Boolean)
                : [];

            const payload = {{
                enabled: enabled,
                allowed_channel_ids: allowedChannelIds,
                output_channel_id: outputChannel || null,
                retention_days: retentionDays
            }};

            try {{
                const res = await fetch("/api/v1/admin/guilds/{html.escape(guild_id)}/settings", {{
                    method: "PUT",
                    headers: {{
                        "Content-Type": "application/json",
                        "X-Admin-API-Key": adminKey
                    }},
                    body: JSON.stringify(payload)
                }});

                if (res.ok) {{
                    const data = await res.json();
                    showMessage("success", "✅ Đã lưu cấu hình Guild thành công! Bot đã sẵn sàng lắng nghe các kênh đã chọn.");
                }} else {{
                    const err = await res.json().catch(() => ({{ detail: res.statusText }}));
                    showMessage("error", "❌ Lỗi (" + res.status + "): " + (err.detail || "Không thể lưu cấu hình."));
                }}
            }} catch (exc) {{
                showMessage("error", "❌ Lỗi mạng hoặc không thể kết nối tới Backend: " + exc.message);
            }} finally {{
                saveBtn.disabled = false;
                saveBtn.innerText = "Lưu Cấu Hình";
            }}
        }});
    </script>
</body>
</html>
"""
        return HTMLResponse(content=page_html)

    @app.post("/setup/{guild_id}", response_class=HTMLResponse, tags=["dashboard"])
    async def setup_dashboard_submit(
        guild_id: str,
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        # Fallback server-side form submission handler without python-multipart dependency
        body_bytes = await request.body()
        form_data = parse_qs(body_bytes.decode("utf-8", errors="replace"))
        admin_key = form_data.get("admin_key", [""])[0]
        verify_key(app_settings.admin_api_key, admin_key, "Admin API")
        enabled = form_data.get("enabled", ["false"])[0].lower() in ("true", "1", "on")
        allowed_channels = form_data.get("allowed_channels", [""])[0]
        output_channel = form_data.get("output_channel", [""])[0]
        try:
            retention_days = int(form_data.get("retention_days", ["365"])[0])
        except ValueError:
            retention_days = 365
        record = await session.get(GuildSettingsRecord, guild_id)
        if record is None:
            record = GuildSettingsRecord(guild_id=guild_id, enabled=enabled)
            session.add(record)
        record.enabled = enabled
        record.allowed_channel_ids = [c.strip() for c in allowed_channels.split(",") if c.strip()]
        record.output_channel_id = output_channel.strip() or None
        record.retention_days = retention_days
        await session.commit()
        return HTMLResponse(
            f"<html><body style='background:#0f172a;color:#fff;font-family:sans-serif;padding:40px;text-align:center;'>"
            f"<h2>🥥 Cấu hình máy chủ {html.escape(guild_id)} đã lưu thành công!</h2>"
            f"<p><a href='/setup/{html.escape(guild_id)}' style='color:#38bdf8;'>Quay lại trang Setup</a></p>"
            f"</body></html>"
        )

    return app


app = create_app()
