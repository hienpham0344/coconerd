"""Deterministic task profiles and a single-use, bounded execution guard."""

import asyncio
import json
import logging
import math
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from time import perf_counter
from types import MappingProxyType
from typing import TypeVar

logger = logging.getLogger(__name__)
META_API_BASE = "https://api.meta.ai/v1"
ROUTING_VERSION = "task-routing-v1"
_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
_FIELDS = {
    "model",
    "temperature",
    "max_tokens",
    "reasoning_effort",
    "timeout_seconds",
    "max_input_chars",
}
_MEMORY_FIELDS = ("overview", "proposals", "decisions", "open_questions", "action_items")
T = TypeVar("T")
R = TypeVar("R")


class TaskConfigurationError(ValueError):
    """Operator configuration is invalid; never include its raw value in errors."""


class TaskInputError(ValueError):
    """Input exceeds the selected task's contract."""


class TaskOutputError(ValueError):
    """Output failed the task's response contract."""


class TaskAlreadyRunError(RuntimeError):
    """An invocation cannot retry, including after a failure or cancellation."""


class TaskKind(StrEnum):
    CHAT = "chat"
    TOPIC_CLASSIFICATION = "topic_classification"
    TOPIC_MEMORY = "topic_memory"


def _number(value: object, low: float, high: float, *, integer: bool = False) -> bool:
    expected = (int,) if integer else (int, float)
    return (
        not isinstance(value, bool)
        and isinstance(value, expected)
        and low <= value <= high
        and math.isfinite(value)
    )


def validate_meta_endpoint(value: str) -> str:
    if value.rstrip("/") != META_API_BASE:
        raise TaskConfigurationError("Only the canonical Meta API endpoint is allowed")
    return META_API_BASE


@dataclass(frozen=True, slots=True)
class TaskProfile:
    task: TaskKind
    model: str
    temperature: float
    max_tokens: int
    reasoning_effort: str
    timeout_seconds: float
    max_input_chars: int
    mode: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model, str)
            or not self.model
            or len(self.model) > 200
            or any(char.isspace() for char in self.model)
            or not _number(self.temperature, 0, 2)
            or not _number(self.max_tokens, 1, 32768, integer=True)
            or not isinstance(self.reasoning_effort, str)
            or self.reasoning_effort not in _EFFORTS
            or not _number(self.timeout_seconds, 0, 45)
            or self.timeout_seconds == 0
            or not _number(self.max_input_chars, 1, 131072, integer=True)
        ):
            raise TaskConfigurationError("Invalid Meta task profile")

    def trace(self) -> dict[str, object]:
        return {
            "version": ROUTING_VERSION,
            "mode": self.mode,
            "task": self.task.value,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "timeout_seconds": self.timeout_seconds,
            "max_input_chars": self.max_input_chars,
        }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TaskConfigurationError("Duplicate task configuration field")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise TaskConfigurationError("Task configuration numbers must be finite")


class TaskRouter:
    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        reasoning_effort: str = "low",
        mode: str = "task",
        profiles_json: str = "{}",
    ) -> None:
        if mode not in {"task", "single"}:
            raise TaskConfigurationError("Agent mode must be task or single")
        try:
            overrides = json.loads(
                profiles_json, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
            )
        except (ValueError, TypeError, RecursionError) as exc:
            raise TaskConfigurationError("Invalid task configuration JSON") from exc
        if not isinstance(overrides, dict) or overrides.keys() - set(TaskKind):
            raise TaskConfigurationError("Unknown task profile")
        profiles = {}
        for task in TaskKind:
            chat = task == TaskKind.CHAT
            base = TaskProfile(
                task=task,
                model=model,
                temperature=0.85 if chat and mode == "task" else temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                timeout_seconds=15.0 if chat else 30.0,
                max_input_chars=24000 if chat else 64000,
                mode=mode,
            )
            values = overrides.get(task, {})
            if not isinstance(values, dict) or values.keys() - _FIELDS:
                raise TaskConfigurationError("Unknown task profile field")
            configured = replace(base, **values)
            profiles[task] = configured if mode == "task" else base
        self._profiles = MappingProxyType(profiles)

    def resolve(self, task: TaskKind | str) -> TaskProfile:
        try:
            return self._profiles[TaskKind(task)]
        except (ValueError, KeyError, TypeError) as exc:
            raise TaskConfigurationError("Unknown task") from exc

    @staticmethod
    def topic_task(summaries: Iterable[Mapping[str, object]]) -> TaskKind:
        for summary in summaries:
            for field in _MEMORY_FIELDS:
                value = summary.get(field)
                if isinstance(value, str) and value.strip():
                    return TaskKind.TOPIC_MEMORY
                if isinstance(value, list) and any(
                    isinstance(item, str) and item.strip() for item in value
                ):
                    return TaskKind.TOPIC_MEMORY
        return TaskKind.TOPIC_CLASSIFICATION


class TaskInvocation:
    def __init__(self, profile: TaskProfile) -> None:
        self.profile = profile
        self._started = False
        self._timeout = profile.timeout_seconds

    @property
    def trace(self) -> dict[str, object]:
        return {**self.profile.trace(), "timeout_seconds": self._timeout}

    async def run(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        input_chars: int,
        validate: Callable[[T], R],
        timeout_seconds: float | None = None,
    ) -> R:
        if self._started:
            raise TaskAlreadyRunError("Task invocation was already consumed")
        self._started = True
        started = perf_counter()
        status, error_type = "error", None
        try:
            if not _number(input_chars, 0, self.profile.max_input_chars, integer=True):
                raise TaskInputError("Task input exceeds the character limit")
            if timeout_seconds is not None:
                if not _number(timeout_seconds, 0, float("inf")) or timeout_seconds == 0:
                    raise TaskInputError("Task deadline must be positive and finite")
                self._timeout = min(self.profile.timeout_seconds, timeout_seconds)
            async with asyncio.timeout(self._timeout):
                result = validate(await operation())
            status = "ok"
            return result
        except BaseException as exc:
            error_type = type(exc).__name__
            if isinstance(exc, asyncio.CancelledError):
                status = "cancelled"
            raise
        finally:
            logger.info(
                "Meta task invocation finished",
                extra={
                    "agent_name": self.profile.task.value,
                    "model_id": self.profile.model,
                    "task_route": self.trace,
                    "status": status,
                    "error_type": error_type,
                    "latency_ms": round((perf_counter() - started) * 1000),
                },
            )
