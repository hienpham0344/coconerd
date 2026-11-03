"""Compute pairwise clustering metrics from labeled and predicted JSONL files."""

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any


def read_jsonl(path: Path, key: str) -> dict[str, str | None]:
    rows: dict[str, str | None] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record: dict[str, Any] = json.loads(line)
            message_id = record["message_id"]
            value = record[key]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(
                f"Invalid {path}:{line_number}; expected message_id and {key}"
            ) from exc
        if not isinstance(message_id, str) or not isinstance(value, (str, type(None))):
            raise ValueError(f"Invalid {path}:{line_number}; IDs must be strings or null")
        rows[message_id] = value
    return rows


def pairwise_scores(
    gold: dict[str, str | None], predictions: dict[str, str | None]
) -> dict[str, float | int]:
    common = sorted(set(gold) & set(predictions))
    tp = fp = fn = 0
    for left, right in combinations(common, 2):
        gold_same = gold[left] is not None and gold[left] == gold[right]
        predicted_same = predictions[left] is not None and predictions[left] == predictions[right]
        tp += int(gold_same and predicted_same)
        fp += int(not gold_same and predicted_same)
        fn += int(gold_same and not predicted_same)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "messages_compared": len(common),
        "true_positive_pairs": tp,
        "false_positive_pairs": fp,
        "false_negative_pairs": fn,
        "pairwise_precision": precision,
        "pairwise_recall": recall,
        "pairwise_f1": f1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold", type=Path, help="JSONL with message_id and expected_topic_id")
    parser.add_argument(
        "predictions", type=Path, help="JSONL with message_id and predicted_topic_id"
    )
    args = parser.parse_args()
    gold = read_jsonl(args.gold, "expected_topic_id")
    predictions = read_jsonl(args.predictions, "predicted_topic_id")
    print(json.dumps(pairwise_scores(gold, predictions), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
