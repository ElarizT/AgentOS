from __future__ import annotations

import pytest

from kernel.events import RuntimeEventLog
from kernel.llm import (
    LLMBudgetExceededError,
    LLMCacheStats,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMResponseCache,
    LLMRuntime,
    LLMTokenBudget,
    LLMUsage,
    LLMUsageLedger,
    build_llm_cache_key,
)


class CacheProvider:
    def __init__(
        self,
        name: str,
        *,
        content: str = "safe response",
        usage: LLMUsage | None = None,
        fail: bool = False,
        failure_detail: str = "private failure",
    ) -> None:
        self.name = name
        self.content = content
        self.usage = usage
        self.fail = fail
        self.failure_detail = failure_detail
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail:
            raise LLMProviderError(self.failure_detail)
        return LLMResponse(
            self.content,
            request.model,
            self.name,
            usage=self.usage,
            metadata={"nested": {"value": "original"}},
        )


def test_cache_disabled_preserves_existing_behavior() -> None:
    provider = CacheProvider("primary")
    cache = LLMResponseCache()
    events = RuntimeEventLog()
    runtime = LLMRuntime(provider, events, cache=cache)

    runtime.chat([LLMMessage("user", "same")], model="model")
    runtime.chat([LLMMessage("user", "same")], model="model")

    assert len(provider.requests) == 2
    assert runtime.cache_snapshot() == LLMCacheStats()
    assert [event.event_type for event in events.events] == [
        "llm.requested",
        "llm.completed",
        "llm.requested",
        "llm.completed",
    ]


def test_cache_miss_stores_and_hit_avoids_provider_and_usage_update() -> None:
    usage = LLMUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)
    provider = CacheProvider("primary", usage=usage)
    cache = LLMResponseCache(enabled=True)
    runtime = LLMRuntime(provider, cache=cache)

    first = runtime.chat([LLMMessage("user", "same")], model="model")
    first.metadata["nested"]["value"] = "changed"
    second = runtime.chat([LLMMessage("user", "same")], model="model")

    assert len(provider.requests) == 1
    assert first.metadata.get("cached") is None
    assert second.metadata["cached"] is True
    assert len(second.metadata["cache_key"]) == 12
    assert second.metadata["nested"]["value"] == "original"
    assert runtime.usage_snapshot() == LLMUsageLedger(3, 2, 5)
    assert runtime.cache_snapshot() == LLMCacheStats(hits=1, misses=1, stores=1, size=1)


def test_cache_key_is_stable_opaque_and_changes_for_relevant_fields() -> None:
    prompt = "private prompt"
    api_key = "private api key"
    base = LLMRequest(
        (LLMMessage("user", prompt, {"unsafe": api_key}),),
        "model",
        temperature=0.0,
        metadata={"api_key": api_key, "max_tokens": 10},
    )
    same_safe_fields = LLMRequest(
        (LLMMessage("user", prompt, {"different": "ignored"}),),
        "model",
        temperature=0.0,
        metadata={"other_unsafe": "ignored", "options": {"max_tokens": 10}},
    )
    base_key = build_llm_cache_key(base, "primary")

    assert base_key == build_llm_cache_key(same_safe_fields, "primary")
    assert prompt not in repr(base_key)
    assert api_key not in repr(base_key)
    assert base_key != build_llm_cache_key(base, "other-provider")
    assert base_key != build_llm_cache_key(
        LLMRequest(base.messages, "other-model", metadata={"max_tokens": 10}),
        "primary",
    )
    assert base_key != build_llm_cache_key(
        LLMRequest(base.messages, "model", temperature=0.5, metadata={"max_tokens": 10}),
        "primary",
    )
    assert base_key != build_llm_cache_key(
        LLMRequest(base.messages, "model", metadata={"max_tokens": 11}),
        "primary",
    )
    assert base_key != build_llm_cache_key(
        LLMRequest((LLMMessage("user", "other"),), "model", metadata={"max_tokens": 10}),
        "primary",
    )


def test_successful_fallback_is_cached_under_route_that_succeeded() -> None:
    primary = CacheProvider("primary-provider", fail=True)
    fallback = CacheProvider("fallback-provider", content="fallback")
    runtime = LLMRuntime(
        providers={"primary": primary, "fallback": fallback},
        default_provider="primary",
        fallback_providers=["fallback"],
        cache=LLMResponseCache(enabled=True),
    )

    first = runtime.chat([LLMMessage("user", "same")], model="model")
    second = runtime.chat([LLMMessage("user", "same")], model="model")

    assert first.content == second.content == "fallback"
    assert second.metadata["cached"] is True
    assert len(primary.requests) == 2
    assert len(fallback.requests) == 1
    assert runtime.cache_snapshot() == LLMCacheStats(hits=1, misses=3, stores=1, size=1)


def test_provider_failure_and_budget_exceeded_responses_are_not_cached() -> None:
    failing = CacheProvider("failing", fail=True)
    failing_runtime = LLMRuntime(failing, cache=LLMResponseCache(enabled=True))

    with pytest.raises(LLMProviderError):
        failing_runtime.chat([LLMMessage("user", "private")], model="model")

    assert failing_runtime.cache_snapshot() == LLMCacheStats(misses=1)

    over_budget = CacheProvider("primary", usage=LLMUsage(total_tokens=6))
    budget_runtime = LLMRuntime(
        over_budget,
        token_budget=LLMTokenBudget(max_total_tokens=5),
        cache=LLMResponseCache(enabled=True),
    )

    with pytest.raises(LLMBudgetExceededError):
        budget_runtime.chat([LLMMessage("user", "private")], model="model")

    assert budget_runtime.cache_snapshot() == LLMCacheStats(misses=1)


def test_budget_preflight_still_applies_before_cache_hit() -> None:
    provider = CacheProvider("primary", usage=LLMUsage(completion_tokens=1, total_tokens=1))
    runtime = LLMRuntime(
        provider,
        token_budget=LLMTokenBudget(max_completion_tokens=2),
        cache=LLMResponseCache(enabled=True),
    )
    messages = [LLMMessage("user", "same")]

    runtime.chat(messages, model="model", metadata={"max_tokens": 1})
    cached = runtime.chat(messages, model="model", metadata={"max_tokens": 1})

    assert cached.metadata["cached"] is True
    assert runtime.usage_snapshot() == LLMUsageLedger(completion_tokens=1, total_tokens=1)


def test_cache_events_are_safe_and_cache_hit_skips_requested_event() -> None:
    prompt = "private prompt"
    api_key = "private api key"
    provider = CacheProvider("primary")
    events = RuntimeEventLog()
    runtime = LLMRuntime(provider, events, cache=LLMResponseCache(enabled=True))

    runtime.chat(
        [LLMMessage("user", prompt)],
        model="model",
        metadata={"api_key": api_key},
    )
    before_hit = len(events.events)
    runtime.chat(
        [LLMMessage("user", prompt)],
        model="model",
        metadata={"api_key": api_key},
    )

    cache_events = [
        event for event in events.events if event.event_type.startswith("llm.cache_")
    ]
    assert [event.event_type for event in cache_events] == [
        "llm.cache_checked",
        "llm.cache_miss",
        "llm.cache_stored",
        "llm.cache_checked",
        "llm.cache_hit",
    ]
    safe_fields = {"provider", "model", "cache_key", "hit", "size"}
    assert all(set(event.metadata) <= safe_fields for event in cache_events)
    assert "llm.requested" not in [
        event.event_type for event in events.events[before_hit:]
    ]
    assert prompt not in repr(events.events)
    assert api_key not in repr(events.events)


def test_cache_stats_clear_and_request_level_opt_out() -> None:
    provider = CacheProvider("primary")
    cache = LLMResponseCache(enabled=True)
    events = RuntimeEventLog()
    runtime = LLMRuntime(provider, events, cache=cache)
    messages = [LLMMessage("user", "same")]

    runtime.chat(messages, model="model", metadata={"options": {"cache": False}})
    runtime.chat(messages, model="model")
    runtime.chat(messages, model="model")

    assert len(provider.requests) == 2
    assert runtime.cache_snapshot() == LLMCacheStats(hits=1, misses=1, stores=1, size=1)

    runtime.clear_cache()

    assert runtime.cache_snapshot() == LLMCacheStats(hits=1, misses=1, stores=1, size=0)
    assert events.events[-1].event_type == "llm.cache_cleared"
    assert events.events[-1].metadata == {"size": 0}
