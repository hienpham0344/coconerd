"""Strict snapshot evaluation; synthetic labels are not real Discord accuracy."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.application.agent_workflow import create_topic_workflow
from backend.application.contracts import ClassificationResult, ModelProvider, TopicCandidate
from backend.application.read_models import ContextMessage
from backend.application.services.message_context import bound_context
from backend.application.topic_retriever import retrieval_message, retrieve_topic_candidates
from backend.domain.entities import ConversationMessage


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1)
    split: Literal["dev", "holdout"]
    synthetic: Literal[True]
    tags: list[str]
    message: ConversationMessage
    candidates: list[TopicCandidate] = Field(default_factory=list)
    context: list[ContextMessage] = Field(default_factory=list)
    expected_outcome: Literal["new", "existing", "defer", "irrelevant"]
    expected_topic_id: str | None = None

    @model_validator(mode="after")
    def validate_gold(self):
        if not self.message.message_id:
            raise ValueError("message_id must not be empty")
        if (self.expected_outcome == "existing") != bool(self.expected_topic_id):
            raise ValueError("only existing labels require expected_topic_id")
        ids = [item.id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate ID")
        return self


class EvaluationPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1)
    mode: Literal["mock", "live"]
    status: Literal["ok", "error", "skipped"]
    candidate_topic_ids: list[str] = Field(default_factory=list, max_length=5)
    result: ClassificationResult | None = None
    error_type: str | None = None
    reserved_model_calls: int = Field(default=0, ge=0, le=1)
    elapsed_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_result(self):
        if (self.status == "ok") != (self.result is not None):
            raise ValueError("only ok predictions must contain a result")
        if self.result and self.result.candidate_topic_ids != self.candidate_topic_ids:
            raise ValueError("candidate IDs must match the actual classification shortlist")
        if self.status == "skipped" and self.reserved_model_calls:
            raise ValueError("skipped cases cannot reserve calls")
        if self.mode == "mock" and self.reserved_model_calls:
            raise ValueError("mock cases cannot reserve paid calls")
        return self


def _unique(rows, key):
    result = {}
    for row in rows:
        value = key(row)
        if value in result:
            raise ValueError(f"duplicate message_id: {value}")
        result[value] = row
    return result


def _read(path: Path, model):
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(model.model_validate_json(line))
        except ValueError as exc:
            # Do not echo raw file contents or response details into logs.
            raise ValueError(f"Invalid evaluation row at {path}:{number}") from exc
    if not rows:
        raise ValueError("evaluation input is empty")
    return rows


def read_cases(path: Path) -> list[EvaluationCase]:
    rows = _read(path, EvaluationCase)
    _unique(rows, lambda row: row.message.message_id)
    return rows


def read_predictions(path: Path) -> list[EvaluationPrediction]:
    rows = _read(path, EvaluationPrediction)
    _unique(rows, lambda row: row.message_id)
    return rows


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate(cases: list[EvaluationCase], predictions: list[EvaluationPrediction]) -> dict:
    gold = _unique(cases, lambda row: row.message.message_id)
    predicted = _unique(predictions, lambda row: row.message_id)
    if not gold or set(gold) != set(predicted):
        raise ValueError("prediction IDs must exactly match nonempty gold IDs")
    modes = {row.mode for row in predictions}
    if len(modes) != 1:
        raise ValueError("do not mix mock and live predictions")
    outcome_hits = decision_hits = assignments = correct_assignments = 0
    merges = duplicates = existing_predictions = deferred = correct_deferred = 0
    recall_hits = existing_labels = 0
    for id, case in gold.items():
        row = predicted[id]
        if case.expected_outcome == "existing":
            existing_labels += 1
            recall_hits += case.expected_topic_id in row.candidate_topic_ids[:5]
        if row.result is None:
            continue
        decision = row.result.decision
        outcome_match = decision.outcome == case.expected_outcome
        identity_match = outcome_match and (
            decision.outcome != "existing" or decision.topic_id == case.expected_topic_id
        )
        outcome_hits += outcome_match
        decision_hits += identity_match
        assigned = decision.outcome in {"new", "existing"}
        assignments += assigned
        correct_assignments += assigned and identity_match
        if decision.outcome == "existing":
            existing_predictions += 1
            merges += not identity_match
        duplicates += decision.outcome == "new" and case.expected_outcome == "existing"
        if decision.outcome == "defer":
            deferred += 1
            correct_deferred += case.expected_outcome == "defer"
    usage = {}
    for field in ("prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens"):
        values = [getattr(row.result, field) if row.result else None for row in predictions]
        known = [value for value in values if value is not None]
        usage[field] = {
            "known_sum": sum(known),
            "known_cases": len(known),
            "total": sum(known) if len(known) == len(cases) else None,
        }
    prompt = usage["prompt_tokens"]["total"]
    completion = usage["completion_tokens"]["total"]
    usage["total_tokens"] = (
        prompt + completion if prompt is not None and completion is not None else None
    )
    latencies = [row.elapsed_ms for row in predictions if row.elapsed_ms is not None]
    model_latencies = [
        row.elapsed_ms
        for row in predictions
        if row.reserved_model_calls and row.elapsed_ms is not None
    ]
    count = len(cases)
    return {
        "mode": next(iter(modes)),
        "synthetic": True,
        "model_accuracy_claim": False,
        "cases": count,
        "completed": sum(row.status == "ok" for row in predictions),
        "errors": sum(row.status == "error" for row in predictions),
        "skipped": sum(row.status == "skipped" for row in predictions),
        "prediction_coverage": sum(row.status == "ok" for row in predictions) / count,
        "outcome_accuracy": outcome_hits / count,
        "decision_accuracy": decision_hits / count,
        "candidate_recall_at_5": _ratio(recall_hits, existing_labels),
        "existing_labels": existing_labels,
        "retrieved_gold_topics": recall_hits,
        "wrong_merges": merges,
        "wrong_merge_rate": _ratio(merges, existing_predictions),
        "duplicate_new": duplicates,
        "defer_precision": _ratio(correct_deferred, deferred),
        "assignment_coverage": assignments / count,
        "assignment_precision": _ratio(correct_assignments, assignments),
        "reserved_model_calls": sum(row.reserved_model_calls for row in predictions),
        "usage": usage,
        "latency_ms": {
            "known_cases": len(latencies),
            "all_cases_mean": _ratio(sum(latencies), len(latencies)),
            "model_attempts_known": len(model_latencies),
            "model_attempts_mean": _ratio(sum(model_latencies), len(model_latencies)),
        },
    }


class _CallLimitReached(Exception):
    pass


class _CappedProvider:
    def __init__(self, provider: ModelProvider, limit: int, live: bool):
        self.provider, self.limit, self.live = provider, limit, live
        self.model_id = provider.model_id
        self.calls = 0

    async def classify(self, message, candidates, context=()):
        if self.live:
            if self.calls >= self.limit:
                raise _CallLimitReached
            self.calls += 1
        return await self.provider.classify(message, candidates, context)


async def run_cases(
    cases: list[EvaluationCase],
    provider: ModelProvider,
    *,
    mode: Literal["mock", "live"],
    max_calls: int = 0,
) -> AsyncIterator[EvaluationPrediction]:
    """Stream snapshots without DB writes or retries; cap includes failed attempts."""
    if mode not in {"mock", "live"} or not 0 <= max_calls <= 100:
        raise ValueError("mode must be mock/live and max_calls must be between 0 and 100")
    _unique(cases, lambda row: row.message.message_id)
    capped = _CappedProvider(provider, max_calls, mode == "live")
    workflow = create_topic_workflow(capped)
    for case in cases:
        started, before = perf_counter(), capped.calls
        context = bound_context(case.context)
        candidates = retrieve_topic_candidates(
            retrieval_message(case.message, context), case.candidates
        )
        fields = dict(
            message_id=case.message.message_id,
            mode=mode,
            candidate_topic_ids=[item.id for item in candidates],
        )
        try:
            state = await workflow.ainvoke(
                {"message": case.message, "candidates": candidates, "context": context}
            )
            result = state["classification"]
            fields.update(
                status="ok", result=result, candidate_topic_ids=result.candidate_topic_ids
            )
        except _CallLimitReached:
            fields.update(status="skipped", error_type="call_cap")
        except Exception as exc:
            fields.update(status="error", error_type=type(exc).__name__)
        yield EvaluationPrediction(
            **fields,
            reserved_model_calls=capped.calls - before,
            elapsed_ms=round((perf_counter() - started) * 1000),
        )


def report_json(cases, predictions) -> str:
    return json.dumps(evaluate(cases, predictions), ensure_ascii=False, indent=2, allow_nan=False)
