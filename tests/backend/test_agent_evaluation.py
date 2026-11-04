import json
from datetime import UTC, datetime

import pytest

from backend.agent_evaluation import (
    EvaluationCase,
    EvaluationPrediction,
    evaluate,
    read_cases,
    read_predictions,
    run_cases,
)
from backend.application.contracts import ClassificationResult, TopicDecision
from backend.domain.entities import ConversationMessage


def case(id="m", outcome="existing", topic="mobile", content="Mobile login crashes"):
    return EvaluationCase(
        conversation_id=f"dev-{id}",
        split="dev",
        synthetic=True,
        tags=["similar_topics"],
        message=ConversationMessage("g", "c", id, "a", "A", content, datetime.now(UTC)),
        expected_outcome=outcome,
        expected_topic_id=topic,
    )


def prediction(id="m", outcome="existing", topic="mobile", **usage):
    return EvaluationPrediction(
        message_id=id,
        mode="live",
        status="ok",
        candidate_topic_ids=["mobile"],
        reserved_model_calls=1,
        elapsed_ms=10,
        result=ClassificationResult(
            decision=TopicDecision(outcome=outcome, topic_id=topic, confidence=0.8, reason="test"),
            model_id="test",
            latency_ms=8,
            candidate_topic_ids=["mobile"],
            **usage,
        ),
    )


def test_metrics_count_wrong_identity_errors_and_skips_in_denominators():
    cases = [case("a"), case("b"), case("c", "defer", None), case("d", "new", None)]
    rows = [
        prediction("a", topic="web"),
        prediction("b", "new", None),
        EvaluationPrediction(
            message_id="c",
            mode="live",
            status="error",
            error_type="Timeout",
            reserved_model_calls=1,
            elapsed_ms=30,
        ),
        EvaluationPrediction(message_id="d", mode="live", status="skipped"),
    ]
    report = evaluate(cases, rows)
    assert report["cases"] == 4
    assert report["outcome_accuracy"] == 0.25
    assert report["decision_accuracy"] == 0
    assert report["prediction_coverage"] == report["assignment_coverage"] == 0.5
    assert report["wrong_merges"] == report["duplicate_new"] == 1
    assert report["errors"] == report["skipped"] == 1
    assert report["candidate_recall_at_5"] == 1
    assert report["defer_precision"] is None


def test_usage_remains_unknown_and_does_not_double_count_cached_or_reasoning():
    full = prediction(
        prompt_tokens=100, completion_tokens=30, cached_tokens=60, reasoning_tokens=20
    )
    report = evaluate([case()], [full])
    assert report["usage"]["total_tokens"] == 130
    assert report["usage"]["cached_tokens"]["known_sum"] == 60
    unknown = prediction("other")
    report = evaluate([case(), case("other")], [full, unknown])
    assert report["usage"]["total_tokens"] is None
    assert report["usage"]["prompt_tokens"] == {"known_sum": 100, "known_cases": 1, "total": None}


@pytest.mark.parametrize("rows", [[], [prediction(), prediction()], [prediction("extra")]])
def test_evaluation_rejects_missing_duplicate_and_extra_predictions(rows):
    with pytest.raises(ValueError):
        evaluate([case()], rows)


@pytest.mark.parametrize("reader,record", [(read_cases, case()), (read_predictions, prediction())])
def test_jsonl_readers_reject_duplicate_ids(tmp_path, reader, record):
    path = tmp_path / "duplicate.jsonl"
    path.write_text((record.model_dump_json() + "\n") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        reader(path)


async def test_runner_enforces_call_cap_after_failure_but_keeps_local_cases():
    class FailingProvider:
        model_id = "fake"
        calls = 0

        async def classify(self, *_args):
            self.calls += 1
            raise TimeoutError("private response must not be emitted")

    provider = FailingProvider()
    cases = [case("a"), case("b"), case("c", "defer", None, "ok")]
    rows = [row async for row in run_cases(cases, provider, mode="live", max_calls=1)]
    assert provider.calls == 1
    assert [row.status for row in rows] == ["error", "skipped", "ok"]
    assert rows[0].error_type == "TimeoutError"
    assert "private" not in rows[0].model_dump_json()
    assert rows[2].result.decision.outcome == "defer"
    report = evaluate(cases, rows)
    assert report["reserved_model_calls"] == 1
    assert report["outcome_accuracy"] == pytest.approx(1 / 3)


def test_synthetic_splits_are_disjoint_and_cover_failure_modes():
    from pathlib import Path

    root = Path("tests/fixtures/evaluation")
    dev, holdout = [read_cases(root / f"agent_{split}.jsonl") for split in ("dev", "holdout")]
    assert not {r.conversation_id for r in dev} & {r.conversation_id for r in holdout}
    assert all(r.split == "dev" and r.synthetic for r in dev)
    assert all(r.split == "holdout" and r.synthetic for r in holdout)
    for split in (dev, holdout):
        tags = {tag for row in split for tag in row.tags}
        assert {
            "missing_context",
            "interleaving",
            "similar_topics",
            "aliases",
            "old_topic",
            "changed_subject",
            "multiple_topics",
            "clarification",
        } <= tags


def test_mock_report_is_explicitly_not_model_accuracy():
    row = prediction().model_copy(update={"mode": "mock", "reserved_model_calls": 0})
    report = evaluate([case()], [row])
    assert report["mode"] == "mock"
    assert report["model_accuracy_claim"] is False
    assert json.dumps(report)


def test_latency_separates_model_attempts_from_skipped_and_local_cases():
    rows = [
        prediction("a"),
        EvaluationPrediction(
            message_id="b",
            mode="live",
            status="skipped",
            elapsed_ms=0,
        ),
    ]
    report = evaluate([case("a"), case("b")], rows)
    assert report["latency_ms"]["all_cases_mean"] == 5
    assert report["latency_ms"]["model_attempts_mean"] == 10
    assert report["latency_ms"]["model_attempts_known"] == 1


async def test_cli_refuses_overwrite_before_provider_creation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from backend import agent_evaluation_cli as evaluate_agent

    path = tmp_path / "results.jsonl"
    path.write_text("preserve", encoding="utf-8")
    gold = tmp_path / "cases.jsonl"
    gold.write_text(case().model_dump_json(), encoding="utf-8")

    def forbidden(*_args):
        pytest.fail("provider must not be constructed before output-path validation")

    monkeypatch.setattr(evaluate_agent, "MetaModelProvider", forbidden)
    with pytest.raises(FileExistsError):
        await evaluate_agent.run(
            SimpleNamespace(
                cases=gold,
                predictions=None,
                output=path,
                live=True,
                max_calls=1,
            )
        )
    assert path.read_text() == "preserve"


def test_cli_requires_explicit_live_cap(monkeypatch):
    from backend.agent_evaluation_cli import main

    monkeypatch.setattr("sys.argv", ["evaluate_agent", "cases.jsonl", "--live", "--output", "out"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
