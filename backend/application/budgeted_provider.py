"""Lazy provider guarded by a durable reservation supplied by the worker."""

from collections.abc import Awaitable, Callable, Sequence

from backend.application.contracts import ClassificationResult, ModelProvider, TopicCandidate
from backend.application.read_models import ContextMessage
from backend.domain.entities import ConversationMessage


class ModelCallBudgetExceeded(Exception):
    pass


class BudgetedProvider:
    model_id = "budgeted"

    def __init__(
        self,
        factory: Callable[[], Awaitable[ModelProvider]],
        reserve: Callable[[], Awaitable[bool]],
    ):
        self.factory = factory
        self.reserve = reserve
        self.provider: ModelProvider | None = None

    async def classify(
        self,
        message: ConversationMessage,
        candidates: list[TopicCandidate],
        context: Sequence[ContextMessage] = (),
    ) -> ClassificationResult:
        if not await self.reserve():
            raise ModelCallBudgetExceeded("Message exhausted its two-call budget or lost its lease")
        if self.provider is None:
            self.provider = await self.factory()
        return await self.provider.classify(message, candidates, context)

    async def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if close is not None:
            await close()
