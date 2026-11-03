from typing import TypedDict

from langgraph.graph import END, StateGraph

from backend.application.contracts import ModelProvider, TopicCandidate, TopicDecision
from backend.domain.entities import ConversationMessage


class WorkflowState(TypedDict, total=False):
    message: ConversationMessage
    candidates: list[TopicCandidate]
    decision: TopicDecision
    route: str


def create_topic_workflow(provider: ModelProvider):
    async def classify(state: WorkflowState) -> dict[str, TopicDecision]:
        decision = await provider.classify(state["message"], state["candidates"])
        return {"decision": decision}

    def outcome(state: WorkflowState) -> str:
        return state["decision"].outcome

    def mark_route(route_name: str):
        def mark(_state: WorkflowState) -> dict[str, str]:
            return {"route": route_name}

        return mark

    graph = StateGraph(WorkflowState)
    graph.add_node("classify", classify)
    for branch in ("new", "existing", "defer", "irrelevant"):
        graph.add_node(f"{branch}_topic", mark_route(branch))
        graph.add_edge(f"{branch}_topic", END)
    graph.set_entry_point("classify")
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
