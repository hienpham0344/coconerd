"""Versioned topic rules and reference checks; confidence alone never assigns a topic."""

import re
from collections.abc import Sequence

from backend.application.contracts import ClassificationResult, TopicCandidate, TopicDecision
from backend.application.language_normalization import analyze_language
from backend.application.read_models import ContextMessage
from backend.application.topic_memory import InvalidMemoryUpdate, validate_memory_replacements
from backend.domain.entities import ConversationMessage

POLICY_VERSION = "topic-policy-v4"
# A conservative abstention rule, not a calibrated probability of correctness.
ASSIGNMENT_CONFIDENCE_FLOOR = 0.7
POLICY_INSTRUCTIONS = (
    "Topic identity follows the same issue/project and goal, not shared keywords. "
    "Distinguish web/mobile and unrelated projects. A reply may change subject. "
    "Use defer with missing_context for an unclear acknowledgement or reference; "
    "irrelevant is only clearly non-topical content, not uncertainty. "
    "Set multiple_topics=true and defer when the target contains separate topics. "
    "Choose defer with ambiguous when your confidence in an assignment is below 0.7. "
    "For new/existing, evidence_message_ids must include the target message_id and "
    "only supplied message IDs supporting the decision. Existing topic_id must be "
    "in candidate_topics. Do not invent evidence. When deferring, set defer_reason "
    "and leave summary and extracted lists empty. Otherwise defer_reason=null. "
    "A followup_clarification can disambiguate the original message, but its new "
    "claims must not be attributed to the original message. Summary updates must "
    "contain only facts contributed by the target. Examples: 'ok' without a clear "
    "referent -> defer; 'ok' replying to 'ship beta Thursday?' -> existing beta; "
    "'ship beta Thursday, and who fixes payments?' -> defer with multiple_topics. "
    "For an explicit correction or cancellation, use memory_replacements: field, "
    "previous (one exact complete fact/overview line shown in the selected topic), "
    "replacement (new fact, or null to remove), quote (exact supporting target text). "
    "Keep unmentioned facts; never replace from context alone or edit truncated facts. "
    "Do not repeat superseded facts in summary or extracted lists. Return [] otherwise."
)
_ACKS = {"ok", "okay", "yes", "no", "agreed", "ừ", "ừm", "uh", "đồng ý", "không", "chốt nhé"}


def classify_locally(
    message: ConversationMessage, context: Sequence[ContextMessage]
) -> ClassificationResult | None:
    normalized = " ".join(re.findall(r"[^\W_]+", message.content.casefold()))
    if not message.content.strip():
        decision = TopicDecision(
            outcome="irrelevant", confidence=1, reason="message has no text content"
        )
        model_id = "local-empty"
    elif (normalized in _ACKS or analyze_language(message.content).needs_context) and not any(
        item.relation in {"reply_ancestor", "followup_clarification"} for item in context
    ):
        decision = TopicDecision(
            outcome="defer",
            confidence=0,
            reason="acknowledgement lacks an explicit referent",
            defer_reason="missing_context",
        )
        model_id = "local-defer"
    else:
        return None
    return ClassificationResult(
        decision=decision,
        model_id=model_id,
        prompt_tokens=0,
        completion_tokens=0,
        reasoning_tokens=0,
        cached_tokens=0,
        latency_ms=0,
        model_calls=0,
    )


def validate_classification(
    result: ClassificationResult,
    message: ConversationMessage,
    candidates: Sequence[TopicCandidate],
    context: Sequence[ContextMessage],
) -> ClassificationResult:
    decision = result.decision.model_copy(deep=True)
    reason = None
    known_ids = {message.message_id, *(item.message_id for item in context)}
    bare_reference = analyze_language(message.content).needs_context
    if decision.multiple_topics:
        reason = "multiple_topics"
    elif decision.outcome in {"new", "existing"}:
        if (
            message.message_id not in decision.evidence_message_ids
            or not set(decision.evidence_message_ids) <= known_ids
        ):
            reason = "invalid_evidence"
        elif decision.outcome == "existing" and decision.topic_id not in {
            item.id for item in candidates
        }:
            reason = "invalid_topic"
        elif decision.confidence < ASSIGNMENT_CONFIDENCE_FLOOR:
            reason = "ambiguous"
        elif decision.outcome == "new" and bare_reference:
            reason = "missing_context"
        elif decision.outcome == "new":
            if (
                not decision.title
                or not decision.title.strip()
                or len(decision.title) > 300
                or decision.topic_id is not None
            ):
                reason = "invalid_topic"
            elif any(
                " ".join(item.title.casefold().split())
                == " ".join(decision.title.casefold().split())
                for item in candidates
            ):
                reason = "duplicate_topic"
    if not reason and decision.outcome in {"new", "existing"}:
        selected = next((item for item in candidates if item.id == decision.topic_id), None)
        try:
            validate_memory_replacements(
                selected.summary if selected else {}, decision, message.content
            )
        except InvalidMemoryUpdate:
            reason = "invalid_evidence"
    if reason:
        decision = TopicDecision(
            outcome="defer",
            confidence=0,
            reason=f"policy check: {reason}",
            defer_reason=reason,
            multiple_topics=decision.multiple_topics,
        )
    elif decision.outcome in {"defer", "irrelevant"}:
        decision.topic_id = decision.title = None
        decision.summary = decision.description = ""
        decision.memory_replacements = []
        decision.proposals = decision.decisions = decision.open_questions = (
            decision.action_items
        ) = []
        if decision.outcome == "defer" and decision.defer_reason is None:
            decision.defer_reason = "ambiguous"
    else:
        decision.defer_reason = None
        if bare_reference:
            # A resolved reference may identify a topic without asserting new facts.
            # Keep the source message, but do not infer approvals or tasks from it.
            decision.description = decision.summary = ""
            decision.memory_replacements = []
            decision.proposals = decision.decisions = decision.open_questions = (
                decision.action_items
            ) = []
    return result.model_copy(update={"decision": decision, "policy_version": POLICY_VERSION})
