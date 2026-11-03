import json

import pytest

from backend.evaluation import candidate_recall_at_k, pairwise_scores


def test_pairwise_clustering_scores_detect_mixed_topic_pair():
    scores = pairwise_scores(
        {"a": "topic-1", "b": "topic-1", "c": "topic-2"},
        {"a": "group-1", "b": "group-2", "c": "group-2"},
    )

    assert scores["true_positive_pairs"] == 0
    assert scores["false_positive_pairs"] == 1
    assert scores["false_negative_pairs"] == 1
    assert scores["pairwise_f1"] == 0


def test_candidate_recall_at_5_counts_retrieved_gold_topics():
    scores = candidate_recall_at_k(
        {"a": "topic-1", "b": "topic-2", "c": None},
        {"a": ["topic-4", "topic-1"], "b": [f"candidate-{i}" for i in range(5)]},
    )

    assert scores == {
        "messages_with_gold_topic": 2,
        "retrieved_gold_topics": 1,
        "candidate_recall_at_k": 0.5,
    }


def test_candidate_recall_at_5_handles_messages_without_gold_topics():
    scores = candidate_recall_at_k({"a": None}, {"a": ["topic-1"]})

    assert scores["messages_with_gold_topic"] == 0
    assert scores["candidate_recall_at_k"] == 0.0


@pytest.mark.parametrize("candidate_ids", ["topic-1", ["topic-1", None], [2]])
def test_prediction_candidate_ids_must_be_list_of_strings(tmp_path, candidate_ids):
    from backend.evaluation import read_candidate_ids_jsonl

    prediction_file = tmp_path / "predictions.jsonl"
    prediction_file.write_text(
        json.dumps({"message_id": "m", "candidate_topic_ids": candidate_ids}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="candidate_topic_ids"):
        read_candidate_ids_jsonl(prediction_file)
