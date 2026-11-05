"""Versioned topic rules and reference checks; confidence alone never assigns a topic."""

import re
from collections.abc import Sequence

from backend.application.contracts import ClassificationResult, TopicCandidate, TopicDecision
from backend.application.language_normalization import analyze_language
from backend.application.read_models import ContextMessage
from backend.application.topic_memory import InvalidMemoryUpdate, validate_memory_replacements
from backend.domain.entities import ConversationMessage

POLICY_VERSION = "topic-policy-v6"
# A conservative abstention rule, not a calibrated probability of correctness.
ASSIGNMENT_CONFIDENCE_FLOOR = 0.7
POLICY_INSTRUCTIONS = (
    "First decide whether the target contributes information worth retaining in a conversation "
    "note, independently of whether its subject matches a topic. Set is_noteworthy=false and "
    "outcome=irrelevant for greetings, jokes, memes, teasing, idle chatter, rhetorical questions "
    "and standalone trivia such as 'Is water wet?' or 'Tại sao cơm ăn lại no?'. Shared keywords "
    "or replying to an important discussion do not make chatter noteworthy. Set "
    "is_noteworthy=true for substantive discussions, useful questions, meeting or study "
    "schedules, meal planning, concrete proposals, decisions, corrections, cancellations and "
    "follow-up tasks. 'Trưa nay ăn gì?', 'Mai đi học môn gì?' and 'Mai có ai đi học trên trường?' "
    "are useful coordination questions even before anyone answers; no final decision or "
    "minimum message count is required. A short reply approving, rejecting or changing a "
    "specific plan can be noteworthy when its referent is clear. Use context to distinguish "
    "practical coordination from banter; do not classify using topic keywords alone. "
    "When a message mixes useful information and chatter, retain only the useful facts; "
    "an incidental joke is not a separate topic. "
    "Topic identity follows the same issue/project and goal, not shared keywords. "
    "Keep aspects of the same event or project in one topic: planning its meeting, "
    "assigning roles, discussing responsibilities and confirming its schedule are one "
    "conversation, even when their titles or vocabulary differ. For example, 'mai họp làm "
    "hackathon team1', 'về phần này mình 3 role', 'backend, frontend và pm', 'mình sẽ là pm', "
    "'ai là frontend?', 'tui là frontend', assigning Phương to backend, and 'chốt mai 9h họp' "
    "belong to the same hackathon team1 topic. Do not create a separate role-assignment topic. "
    "conversation_predecessor is a nearby earlier turn already assigned to the candidate "
    "marked conversation_predecessor_target. Use its subject to resolve continuations, "
    "including short fragments with no explicit reply. Prefer that existing topic when the "
    "target continues its project or goal; adjacency alone is not proof. Create a new topic "
    "only for an independent issue/project/goal, such as unrelated lunch plans or another "
    "team's hackathon. Never transfer predecessor facts into the target's memory. "
    "Distinguish web/mobile and unrelated projects. A reply may change subject. "
    "Use defer with missing_context for an unclear acknowledgement or reference; "
    "Use irrelevant for clearly non-noteworthy content, not uncertainty about a useful message. "
    "Set multiple_topics=true and defer for independent topics, not multiple aspects of "
    "one project or event. "
    "Choose defer with ambiguous when your confidence in an assignment is below 0.7. "
    "For new/existing, evidence_message_ids must include the target message_id and "
    "only supplied message IDs supporting the decision. Existing topic_id must be "
    "in candidate_topics. Do not invent evidence. When deferring, set defer_reason "
    "and leave summary and extracted lists empty. Otherwise defer_reason=null. "
    "For irrelevant, also leave summary, description and extracted lists empty. "
    "A followup_clarification can disambiguate the original message, but its new "
    "claims must not be attributed to the original message. A conversation_followup is a "
    "later nearby turn with an assigned topic, not an explicit reply or proof of a match. "
    "A candidate marked conversation_followup_target belongs to that later turn only. "
    "Use its meaning to reassess the original target, including short cross-language turns; "
    "defer if the connection remains unclear. A state such as 'hungry' followed by meal "
    "coordination can belong to that meal conversation without asserting a meal decision. "
    "Never transfer the follow-up's claims into the target's memory. Summary updates must "
    "contain only useful facts contributed by the target, written as concise self-contained "
    "notes in the conversation's language. Resolve pronouns and short references using "
    "supported context so readers understand the subject without scrolling back. Include "
    "who, what, when and where only when supplied; never invent missing details. Keep "
    "proposals, confirmed decisions, unanswered questions and tasks distinct. Do not copy "
    "the transcript, narrate chatter or describe a mere question as an agreement. "
    "Examples: 'ok' without a clear "
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
    message: ConversationMessage,
    context: Sequence[ContextMessage],
    candidates: Sequence[TopicCandidate] = (),
) -> ClassificationResult | None:
    normalized = " ".join(re.findall(r"[^\W_]+", message.content.casefold()))
    if not message.content.strip() and message.attachments:
        anchors = [
            item
            for item in candidates
            if message.reply_to_message_id
            and item.evidence == "direct_reply_target"
            and item.status in {"ACTIVE", "DORMANT", "RESUMED"}
        ]
        anchor = anchors[0] if len(anchors) == 1 else None
        title = None
        if anchor is None:
            base_title = f"Tệp đính kèm từ {message.author_name[:100]}"
            title = base_title
            existing_titles = {item.title.casefold() for item in candidates}
            suffix = 2
            while title.casefold() in existing_titles:
                title = f"{base_title} ({suffix})"
                suffix += 1
        decision = TopicDecision(
            outcome="existing" if anchor else "new",
            topic_id=anchor.id if anchor else None,
            title=title,
            confidence=1,
            reason="copy attachments without interpreting their contents",
            evidence_message_ids=[message.message_id],
        )
        model_id = "local-attachments"
    elif not message.content.strip():
        decision = TopicDecision(
            outcome="irrelevant", confidence=1, reason="message has no text content"
        )
        model_id = "local-empty"
    elif (normalized in _ACKS or analyze_language(message.content).needs_context) and not any(
        item.relation in {"reply_ancestor", "followup_clarification", "conversation_followup"}
        for item in context
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
    if not decision.is_noteworthy:
        decision.outcome = "irrelevant"
        decision.multiple_topics = False
    elif decision.multiple_topics:
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
        elif decision.outcome == "irrelevant":
            decision.is_noteworthy = False
            decision.defer_reason = None
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
