from typing import TypedDict

from langgraph.graph import END, StateGraph

from backend.application.contracts import (
    ClassificationResult,
    ModelProvider,
    TopicCandidate,
    TopicDecision,
)
from backend.application.decision_policy import classify_locally, validate_classification
from backend.application.language_normalization import analyze_language
from backend.application.read_models import ContextMessage
from backend.application.topic_retriever import retrieval_message, retrieve_topic_candidates
from backend.domain.entities import ConversationMessage


class WorkflowState(TypedDict, total=False):
    message: ConversationMessage
    candidates: list[TopicCandidate]
    context: list[ContextMessage]
    retrieved_candidates: list[TopicCandidate]
    classification: ClassificationResult
    decision: TopicDecision
    route: str


def create_topic_workflow(provider: ModelProvider):
    def retrieve(state: WorkflowState) -> dict[str, list[TopicCandidate]]:
        return {
            "retrieved_candidates": retrieve_topic_candidates(
                retrieval_message(state["message"], state.get("context", [])), state["candidates"]
            )
        }

    async def classify(state: WorkflowState) -> dict[str, object]:
        classification = classify_locally(state["message"], state["context"])
        if classification is None:
            classification = await provider.classify(
                state["message"], state["retrieved_candidates"], state["context"]
            )
        classification = validate_classification(
            classification, state["message"], state["retrieved_candidates"], state["context"]
        )
        classification.candidate_topic_ids = [item.id for item in state["retrieved_candidates"]]
        classification.language_hints = analyze_language(state["message"].content).as_payload()
        return {"classification": classification, "decision": classification.decision}

    def outcome(state: WorkflowState) -> str:
        return state["decision"].outcome

    def mark_route(route_name: str):
        def mark(_state: WorkflowState) -> dict[str, str]:
            return {"route": route_name}

        return mark

    graph = StateGraph(WorkflowState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("classify", classify)
    for branch in ("new", "existing", "defer", "irrelevant"):
        graph.add_node(f"{branch}_topic", mark_route(branch))
        graph.add_edge(f"{branch}_topic", END)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "classify")
    graph.add_conditional_edges(
        "classify",
        outcome,
        {
            "new": "new_topic",
            "existing": "existing_topic",
            "defer": "defer_topic",
            "irrelevant": "irrelevant_topic",
        },
    )
    return graph.compile()
