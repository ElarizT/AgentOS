from __future__ import annotations

from typing import Any

import pytest

from kernel.events import RuntimeEventLog
from kernel.llm import (
    LLMBudgetExceededError,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMRetryPolicy,
    LLMRuntime,
    LLMTokenBudget,
    LLMUsage,
    LLMUsageLedger,
    apply_usage_to_ledger,
    check_token_budget,
    format_usage_ledger,
)


class BudgetProvider:
    def __init__(
        self,
        name: str,
        outcomes: list[LLMResponse | LLMUsage | Exception | None],
    ) -> None:
        self.name = name
        self.outcomes = list(outcomes)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, LLMResponse):
            return outcome
        return LLMResponse("safe response", request.model, self.name, usage=outcome)


def test_no_budget_preserves_events_and_tracks_known_usage() -> None:
    usage = LLMUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)
    provider = BudgetProvider("primary", [usage])
    events = RuntimeEventLog()
    runtime = LLMRuntime(provider, events)

    runtime.chat([LLMMessage("user", "private prompt")], model="model")

    assert runtime.token_budget is None
    assert runtime.usage_snapshot() == LLMUsageLedger(3, 2, 5)
    assert [event.event_type for event in events.events] == [
        "llm.requested",
        "llm.completed",
    ]


def test_usage_ledger_updates_cumulatively_from_successful_responses() -> None:
    provider = BudgetProvider(
        "primary",
        [
            LLMUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            LLMUsage(prompt_tokens=4, completion_tokens=1, total_tokens=5),
        ],
    )
    runtime = LLMRuntime(provider)

    runtime.chat([LLMMessage("user", "one")], model="model")
    snapshot = runtime.usage_snapshot()
    runtime.chat([LLMMessage("user", "two")], model="model")

    assert snapshot == LLMUsageLedger(3, 2, 5)
    assert runtime.usage_snapshot() == LLMUsageLedger(7, 3, 10)


@pytest.mark.parametrize(
    ("budget", "usage", "category"),
    [
        (LLMTokenBudget(max_prompt_tokens=4), LLMUsage(prompt_tokens=5), "prompt"),
        (
            LLMTokenBudget(max_completion_tokens=4),
            LLMUsage(completion_tokens=5),
            "completion",
        ),
        (LLMTokenBudget(max_total_tokens=4), LLMUsage(total_tokens=5), "total"),
    ],
)
def test_cumulative_budget_limits_raise_after_usage_is_recorded(
    budget: LLMTokenBudget,
    usage: LLMUsage,
    category: str,
) -> None:
    provider = BudgetProvider("primary", [usage])
    runtime = LLMRuntime(provider, token_budget=budget)

    with pytest.raises(LLMBudgetExceededError, match=category):
        runtime.chat([LLMMessage("user", "private")], model="model")

    assert runtime.usage_snapshot() == apply_usage_to_ledger(LLMUsageLedger(), usage)


def test_budget_exceeded_is_sanitized_and_emits_safe_events() -> None:
    prompt = "private prompt"
    api_key = "private api key"
    events = RuntimeEventLog()
    provider = BudgetProvider(
        "primary",
        [LLMUsage(prompt_tokens=6, completion_tokens=4, total_tokens=10)],
    )
    runtime = LLMRuntime(
        provider,
        events,
        token_budget=LLMTokenBudget(name="demo-budget", max_total_tokens=9),
    )

    with pytest.raises(LLMBudgetExceededError, match="demo-budget") as error:
        runtime.chat(
            [LLMMessage("user", prompt)],
            model="model",
            metadata={"private": api_key},
        )

    budget_events = [
        event for event in events.events if event.event_type.startswith("llm.budget_")
    ]
    assert [event.event_type for event in budget_events] == [
        "llm.budget_checked",
        "llm.budget_updated",
        "llm.budget_exceeded",
    ]
    assert budget_events[-1].metadata == {
        "budget": "demo-budget",
        "prompt_tokens_used": 6,
        "completion_tokens_used": 4,
        "total_tokens_used": 10,
        "exceeded": "total",
        "max_total_tokens": 9,
    }
    assert prompt not in repr((error.value, events.events))
    assert api_key not in repr((error.value, events.events))


def test_budget_exceeded_does_not_trigger_retry() -> None:
    provider = BudgetProvider(
        "primary",
        [LLMUsage(total_tokens=6), LLMUsage(total_tokens=1)],
    )
    runtime = LLMRuntime(
        provider,
        retry_policy=LLMRetryPolicy(max_attempts=2, retry_on=("unknown",)),
        token_budget=LLMTokenBudget(max_total_tokens=5),
    )

    with pytest.raises(LLMBudgetExceededError):
        runtime.chat([LLMMessage("user", "private")], model="model")

    assert len(provider.requests) == 1


def test_existing_strict_overrun_blocks_later_provider_calls() -> None:
    provider = BudgetProvider(
        "primary",
        [LLMUsage(total_tokens=6), LLMUsage(total_tokens=1)],
    )
    runtime = LLMRuntime(
        provider,
        token_budget=LLMTokenBudget(max_total_tokens=5),
    )

    with pytest.raises(LLMBudgetExceededError):
        runtime.chat([LLMMessage("user", "first")], model="model")
    with pytest.raises(LLMBudgetExceededError):
        runtime.chat([LLMMessage("user", "second")], model="model")

    assert len(provider.requests) == 1
    assert runtime.usage_snapshot().total_tokens == 6


def test_budget_exceeded_does_not_trigger_fallback() -> None:
    primary = BudgetProvider("primary-provider", [LLMUsage(total_tokens=6)])
    fallback = BudgetProvider("fallback-provider", [LLMUsage(total_tokens=1)])
    runtime = LLMRuntime(
        providers={"primary": primary, "fallback": fallback},
        default_provider="primary",
        fallback_providers=["fallback"],
        token_budget=LLMTokenBudget(max_total_tokens=5),
    )

    with pytest.raises(LLMBudgetExceededError):
        runtime.chat([LLMMessage("user", "private")], model="model")

    assert len(primary.requests) == 1
    assert fallback.requests == []


def test_failed_attempt_does_not_update_ledger_and_fallback_updates_once() -> None:
    primary = BudgetProvider("primary-provider", [LLMProviderError("safe failure")])
    usage = LLMUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6)
    fallback = BudgetProvider("fallback-provider", [usage])
    runtime = LLMRuntime(
        providers={"primary": primary, "fallback": fallback},
        default_provider="primary",
        fallback_providers=["fallback"],
        token_budget=LLMTokenBudget(max_total_tokens=10),
    )

    response = runtime.chat([LLMMessage("user", "private")], model="model")

    assert response.provider == "fallback-provider"
    assert runtime.usage_snapshot() == LLMUsageLedger(4, 2, 6)


def test_request_max_tokens_is_enforced_before_provider_call() -> None:
    provider = BudgetProvider("primary", [LLMUsage(completion_tokens=1)])
    events = RuntimeEventLog()
    runtime = LLMRuntime(
        provider,
        events,
        token_budget=LLMTokenBudget(max_completion_tokens=5),
    )

    with pytest.raises(LLMBudgetExceededError, match="completion"):
        runtime.chat(
            [LLMMessage("user", "private")],
            model="model",
            metadata={"options": {"max_tokens": 6}},
        )

    assert provider.requests == []
    assert runtime.usage_snapshot() == LLMUsageLedger()
    assert [event.event_type for event in events.events] == [
        "llm.budget_checked",
        "llm.budget_exceeded",
    ]


def test_unknown_usage_does_not_invent_counts() -> None:
    provider = BudgetProvider(
        "primary",
        [None, LLMUsage(prompt_tokens=2, completion_tokens=None, total_tokens=None)],
    )
    runtime = LLMRuntime(provider)

    runtime.chat([LLMMessage("user", "one")], model="model")
    runtime.chat([LLMMessage("user", "two")], model="model")

    assert runtime.usage_snapshot() == LLMUsageLedger(prompt_tokens=2)


def test_non_strict_budget_reports_overrun_without_blocking_response() -> None:
    events = RuntimeEventLog()
    provider = BudgetProvider("primary", [LLMUsage(total_tokens=6)])
    runtime = LLMRuntime(
        provider,
        events,
        token_budget=LLMTokenBudget(max_total_tokens=5, strict=False),
    )

    response = runtime.chat([LLMMessage("user", "private")], model="model")

    assert response.content == "safe response"
    assert runtime.usage_snapshot().total_tokens == 6
    assert events.by_type("llm.budget_exceeded")


def test_budget_helpers_are_deterministic() -> None:
    ledger = apply_usage_to_ledger(
        LLMUsageLedger(prompt_tokens=1),
        LLMUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
    )

    assert ledger == LLMUsageLedger(3, 3, 5)
    assert check_token_budget(
        LLMTokenBudget(max_prompt_tokens=2, max_completion_tokens=3, max_total_tokens=4),
        ledger,
    ) == ("prompt", "total")
    assert format_usage_ledger(ledger) == "prompt=3, completion=3, total=5"


def test_invalid_budget_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="max_prompt_tokens"):
        LLMTokenBudget(max_prompt_tokens=-1)
    with pytest.raises(ValueError, match="name"):
        LLMTokenBudget(name=" ")
    with pytest.raises(ValueError, match="strict"):
        LLMTokenBudget(strict=1)  # type: ignore[arg-type]
    with pytest.raises(Exception, match="token_budget must be"):
        LLMRuntime(BudgetProvider("primary", [None]), token_budget=object())  # type: ignore[arg-type]
