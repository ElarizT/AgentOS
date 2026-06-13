"""Stable provider-neutral LLM Runtime Layer for Agent OS."""

from importlib import import_module
from typing import Any

from kernel.llm.providers import (
    DeterministicLLMProvider,
    EchoLLMProvider,
    LLMBudgetExceededError,
    LLMProvider,
    LLMProviderError,
    LLMRuntimeError,
    classify_llm_error,
)
from kernel.llm.openai_compatible import OpenAICompatibleProvider
from kernel.llm.runtime import LLMRuntime
from kernel.llm.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRetryPolicy,
    LLMTokenBudget,
    LLMUsage,
    LLMUsageLedger,
    apply_usage_to_ledger,
    check_token_budget,
    format_usage_ledger,
)


_LEGACY_EXPORTS = {
    "AsyncLLMManager",
    "LLMConfig",
    "LLMError",
    "LegacyLLMResponse",
    "extract_python_code_blocks",
    "normalize_code_block",
}


def __getattr__(name: str) -> Any:
    if name not in _LEGACY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module("kernel.llm.legacy"), name)


__all__ = [
    "AsyncLLMManager",
    "DeterministicLLMProvider",
    "EchoLLMProvider",
    "LLMConfig",
    "LLMError",
    "LLMMessage",
    "LLMBudgetExceededError",
    "LLMProvider",
    "LLMProviderError",
    "LLMRequest",
    "LLMResponse",
    "LLMRetryPolicy",
    "LLMTokenBudget",
    "LLMRuntime",
    "LLMRuntimeError",
    "LLMUsage",
    "LLMUsageLedger",
    "LegacyLLMResponse",
    "OpenAICompatibleProvider",
    "classify_llm_error",
    "apply_usage_to_ledger",
    "check_token_budget",
    "extract_python_code_blocks",
    "format_usage_ledger",
    "normalize_code_block",
]
