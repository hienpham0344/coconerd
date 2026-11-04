"""Persistence operations for auditable moderator review; no ORM escapes this port."""

from typing import Protocol

from backend.application.review_contracts import RecoverAction


class ReviewsRepository(Protocol):
    async def event(self, guild_id: str, request_id: str) -> dict | None: ...
    async def add_event(
        self,
        guild_id: str,
        request_id: str,
        fingerprint: str,
        operation: str,
        resource_id: str,
        actor: str,
        reason: str,
        result: dict,
        message_record_id: str | None = None,
        topic_id: str | None = None,
    ) -> None: ...
    async def message_state(self, guild_id: str, message_record_id: str) -> dict: ...
    async def finish_job(self, guild_id: str, message_record_id: str) -> None: ...
    async def reassign(
        self,
        guild_id: str,
        message_record_id: str,
        expected_revision: int,
        topic_id: str | None,
        reason: str,
    ) -> None: ...
    async def fence_topic(
        self, guild_id: str, topic_id: str, version: int, paused: bool, thread_id: str | None = None
    ) -> None: ...
    async def cancel_actions(self, guild_id: str, topic_ids: list[str]) -> list[str]: ...
    async def valid_sources(self, guild_id: str, topic_id: str, source_ids: list[str]) -> bool: ...
    async def sync_state(self, guild_id: str, topic_id: str, limit: int, offset: int) -> dict: ...
    async def recover_action(
        self, guild_id: str, action_id: str, command: RecoverAction
    ) -> dict: ...
