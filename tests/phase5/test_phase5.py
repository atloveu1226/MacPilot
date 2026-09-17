from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from macpilot.core.cache import ResponseCache, make_cache_key
from macpilot.core.context import estimate_tokens, trim_messages, trim_text
from macpilot.core.storage import SQLiteStore
from macpilot.core.usage import ModelPricing, usage_for_response
from macpilot.phase5.metrics import summarize_events
from macpilot.phase5.runner import load_tasks, run_offline


def test_phase5_task_catalog_has_the_planned_distribution() -> None:
    tasks = load_tasks()
    assert len(tasks) == 50
    assert {category: sum(task.category == category for task in tasks) for category in {
        "local_file", "web_research", "document_generation", "failure_recovery", "security"
    }} == {
        "local_file": 10,
        "web_research": 15,
        "document_generation": 10,
        "failure_recovery": 8,
        "security": 7,
    }


def test_offline_evaluation_is_reproducible_and_passes() -> None:
    results, metrics = run_offline(load_tasks())
    assert len(results) == 50
    assert all(result.passed for result in results)
    assert metrics.success_rate == 1.0


def test_context_trimming_keeps_system_and_latest_message() -> None:
    messages = [
        SystemMessage(content="policy"),
        HumanMessage(content="old " * 100),
        HumanMessage(content="latest"),
    ]
    trimmed = trim_messages(messages, 10)
    assert trimmed[0].content == "policy"
    assert trimmed[-1].content == "latest"
    assert estimate_tokens(trim_text("x" * 1000, 20)) <= 21


def test_response_cache_round_trip_and_explicit_key(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "cache.sqlite3")
    key = make_cache_key("test-model", [{"role": "user", "content": "hello"}])
    assert cache.get(key) is None
    cache.set(key, "test-model", "cached response")
    assert cache.get(key) == "cached response"
    assert cache.stats()["hits"] == 1


def test_usage_prefers_provider_metadata_and_calculates_cost() -> None:
    response = AIMessage(
        content="answer",
        usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
    )
    usage = usage_for_response(response, "prompt")
    assert usage.total_tokens == 18
    assert usage.estimated_cost(ModelPricing(1.0, 2.0)) == (11 + 14) / 1_000_000


def test_metrics_count_policy_denials_and_model_usage(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "metrics.sqlite3")
    task_id = store.create_task("metrics")
    store.append_event("tool_call", {"output": {"policy_denied": True}}, task_id=task_id)
    store.append_event("model_usage", {"input_tokens": 3, "output_tokens": 4, "cache_hit": True}, task_id=task_id)
    metrics = summarize_events(store.list_events(task_id), {"status": "completed"})
    assert metrics.unauthorized_actions == 1
    assert metrics.total_tokens == 7
    assert metrics.cache_hits == 1
