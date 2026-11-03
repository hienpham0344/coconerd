from backend.evaluation import pairwise_scores


def test_pairwise_clustering_scores_detect_mixed_topic_pair():
    scores = pairwise_scores(
        {"a": "topic-1", "b": "topic-1", "c": "topic-2"},
        {"a": "group-1", "b": "group-2", "c": "group-2"},
    )

    assert scores["true_positive_pairs"] == 0
    assert scores["false_positive_pairs"] == 1
    assert scores["false_negative_pairs"] == 1
    assert scores["pairwise_f1"] == 0
