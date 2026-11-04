from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class GuildSettingsRecord(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_channel_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_message_id", name="uq_message_guild_discord_id"),
        Index("ix_messages_guild_channel_created", "guild_id", "channel_id", "created_at"),
        Index("ix_messages_guild_author_created", "guild_id", "author_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(100), nullable=False)
    discord_message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    author_id: Mapped[str] = mapped_column(String(100), nullable=False)
    author_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(100))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TopicRecord(Base):
    __tablename__ = "topics"
    __table_args__ = (
        Index("ix_topics_guild_status_activity", "guild_id", "status", "last_activity_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    discord_thread_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TopicSearchTermRecord(Base):
    __tablename__ = "topic_search_terms"
    __table_args__ = (Index("ix_topic_terms_guild_term", "guild_id", "term"),)

    topic_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    term: Mapped[str] = mapped_column(String(300), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)


class EpisodeRecord(Base):
    __tablename__ = "conversation_episodes"
    __table_args__ = (
        Index("ix_episodes_guild_topic_started", "guild_id", "topic_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageTopicAssociationRecord(Base):
    __tablename__ = "message_topic_associations"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "message_record_id", name="uq_message_association_guild_message"
        ),
        Index("ix_associations_guild_topic", "guild_id", "topic_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message_record_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)


class TopicSummaryRecord(Base):
    __tablename__ = "topic_summaries"
    __table_args__ = (
        UniqueConstraint("guild_id", "topic_id", "version", name="uq_summary_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AIDecisionRecord(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message_record_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    decision_type: Mapped[str] = mapped_column(String(40), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class DiscordActionRecord(Base):
    __tablename__ = "discord_actions"
    __table_args__ = (
        Index("ix_actions_status_created", "status", "created_at"),
        Index("ix_actions_lease", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(100), nullable=False)
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    dependency_id: Mapped[str | None] = mapped_column(
        ForeignKey("discord_actions.id", ondelete="CASCADE")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    discord_thread_id: Mapped[str | None] = mapped_column(String(100))
    discord_message_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessingJobRecord(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_jobs_status_available", "status", "available_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message_record_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    model_call_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    reassessment_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    followup_message_id: Mapped[str | None] = mapped_column(String(36))
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ModelConfigRecord(Base):
    __tablename__ = "model_configs"
    __table_args__ = (
        Index(
            "uq_model_configs_global", "scope", unique=True, sqlite_where=text("guild_id IS NULL")
        ),
        Index(
            "uq_model_configs_guild",
            "scope",
            "guild_id",
            unique=True,
            sqlite_where=text("guild_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    guild_id: Mapped[str | None] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class WorkerHeartbeatRecord(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ApiRateLimitRecord(Base):
    __tablename__ = "api_rate_limits"

    client_fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
