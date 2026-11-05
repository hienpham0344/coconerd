import asyncio
import json
from dataclasses import FrozenInstanceError

import pytest


def router(**kwargs):
    from coconerd_ai.task_routing import TaskRouter

    return TaskRouter(model="muse-spark-1.3", **kwargs)


def test_task_profiles_apply_only_the_selected_override():
    routes = router(
        profiles_json='{"chat":{"max_tokens":1024,"timeout_seconds":8},'
        '"topic_memory":{"max_tokens":4096,"reasoning_effort":"minimal"}}'
    )

    assert routes.resolve("chat").max_tokens == 1024
    assert routes.resolve("chat").timeout_seconds == 8
    assert routes.resolve("topic_classification").max_tokens == 2048
    assert routes.resolve("topic_memory").max_tokens == 4096
    assert routes.resolve("topic_memory").reasoning_effort == "minimal"
    with pytest.raises(FrozenInstanceError):
        routes.resolve("chat").model = "changed"


def test_task_model_override_is_explicit_and_does_not_change_other_tasks():
    routes = router(profiles_json='{"topic_memory":{"model":"meta-operator-model"}}')

    assert routes.resolve("topic_memory").model == "meta-operator-model"
    assert routes.resolve("chat").model == "muse-spark-1.3"


def test_single_mode_uses_base_parameters_for_all_tasks():
    routes = router(
        mode="single",
        temperature=0.2,
        max_tokens=3072,
        reasoning_effort="minimal",
        profiles_json='{"chat":{"model":"ignored-meta-model","max_tokens":512}}',
    )

    for task in ("chat", "topic_classification", "topic_memory"):
        profile = routes.resolve(task)
        assert (profile.model, profile.temperature, profile.max_tokens) == (
            "muse-spark-1.3",
            0.2,
            3072,
        )
        assert profile.reasoning_effort == "minimal"


@pytest.mark.parametrize(
    "profiles",
    [
        "not-json",
        "[]",
        "null",
        '{"unknown":{}}',
        '{"chat":[]}',
        '{"chat":{"provider":"other"}}',
        '{"chat":{"max_tokens":true}}',
        '{"chat":{"max_tokens":"1024"}}',
        '{"chat":{"max_tokens":0}}',
        '{"chat":{"max_tokens":32769}}',
        json.dumps({"chat": {"max_tokens": 10**500}}),
        '{"chat":{"temperature":1e309}}',
        '{"chat":{"timeout_seconds":0}}',
        '{"chat":{"timeout_seconds":46}}',
        '{"chat":{"timeout_seconds":true}}',
        '{"chat":{"temperature":NaN}}',
        '{"chat":{"temperature":Infinity}}',
        '{"chat":{"temperature":-0.1}}',
        '{"chat":{"reasoning_effort":"invalid"}}',
        '{"chat":{"max_input_chars":131073}}',
        '{"chat":{"max_input_chars":0}}',
        '{"chat":{"model":""}}',
        '{"chat":{"model":"model with spaces"}}',
        '{"chat":{},"chat":{}}',
        '{"chat":{"max_tokens":512,"max_tokens":1024}}',
    ],
)
def test_invalid_profiles_are_rejected_even_in_single_mode(profiles):
    with pytest.raises(ValueError):
        router(mode="single", profiles_json=profiles)


def test_unknown_mode_and_unknown_runtime_task_are_rejected():
    with pytest.raises(ValueError):
        router(mode="automatic-anything")
    with pytest.raises(ValueError):
        router().resolve("run_shell")


@pytest.mark.parametrize(
    ("summaries", "expected"),
    [
        ([], "topic_classification"),
        ([{"topic_id": "t", "title": "Stored title"}], "topic_classification"),
        ([{"overview": "  ", "decisions": []}], "topic_classification"),
        ([{"overview": "Lan owns QA"}], "topic_memory"),
        ([{"decisions": ["Ship Friday"]}], "topic_memory"),
        ([{"overview": 1, "decisions": [None, ""]}], "topic_classification"),
    ],
)
def test_memory_route_requires_actual_stored_facts(summaries, expected):
    assert router().topic_task(summaries) == expected


async def test_invocation_runs_once_and_returns_validated_result():
    from coconerd_ai.task_routing import TaskInvocation

    invocation = TaskInvocation(router().resolve("chat"))
    calls = []

    async def operation():
        calls.append("called")
        return '{"answer":"hello"}'

    result = await invocation.run(operation, input_chars=10, validate=json.loads)
    assert result == {"answer": "hello"}
    with pytest.raises(RuntimeError):
        await invocation.run(operation, input_chars=10, validate=json.loads)
    assert calls == ["called"]


async def test_input_limit_rejects_before_dispatch():
    from coconerd_ai.task_routing import TaskInvocation

    invocation = TaskInvocation(router().resolve("chat"))
    calls = []

    async def operation():
        calls.append("called")
        return "hello"

    with pytest.raises(ValueError):
        await invocation.run(operation, input_chars=24001, validate=str)
    assert calls == []


async def test_invalid_output_consumes_invocation_and_logs_no_body(caplog):
    from coconerd_ai.task_routing import TaskInvocation

    invocation = TaskInvocation(router().resolve("chat"))
    calls = []

    async def operation():
        calls.append("called")
        return "private-output-body"

    with pytest.raises(ValueError):
        await invocation.run(operation, input_chars=1, validate=json.loads)
    with pytest.raises(RuntimeError):
        await invocation.run(operation, input_chars=1, validate=json.loads)
    assert calls == ["called"]
    assert "private-output-body" not in caplog.text


async def test_provider_error_never_retries_or_logs_exception_detail(caplog):
    from coconerd_ai.task_routing import TaskInvocation

    invocation = TaskInvocation(router().resolve("chat"))
    calls = []

    async def operation():
        calls.append("called")
        raise RuntimeError("private-key-and-provider-error")

    with pytest.raises(RuntimeError):
        await invocation.run(operation, input_chars=1, validate=str)
    with pytest.raises(RuntimeError):
        await invocation.run(operation, input_chars=1, validate=str)
    assert calls == ["called"]
    assert "private-key-and-provider-error" not in caplog.text


async def test_timeout_cancels_operation_and_consumes_invocation():
    from coconerd_ai.task_routing import TaskInvocation

    invocation = TaskInvocation(router().resolve("chat"))
    cleaned = []

    async def operation():
        try:
            await asyncio.sleep(1)
        finally:
            cleaned.append(True)

    with pytest.raises(TimeoutError):
        await invocation.run(operation, input_chars=1, validate=str, timeout_seconds=0.001)
    assert cleaned == [True]
    with pytest.raises(RuntimeError):
        await invocation.run(operation, input_chars=1, validate=str)


async def test_caller_cannot_increase_profile_deadline():
    from coconerd_ai.task_routing import TaskInvocation

    invocation = TaskInvocation(
        router(profiles_json='{"chat":{"timeout_seconds":0.001}}').resolve("chat")
    )

    async def operation():
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await invocation.run(operation, input_chars=1, validate=str, timeout_seconds=15)


async def test_external_cancellation_does_not_allow_reexecution():
    from coconerd_ai.task_routing import TaskInvocation

    invocation = TaskInvocation(router().resolve("chat"))
    started = asyncio.Event()
    calls = []

    async def operation():
        calls.append("called")
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(invocation.run(operation, input_chars=1, validate=str))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(RuntimeError):
        await invocation.run(operation, input_chars=1, validate=str)
    assert calls == ["called"]
