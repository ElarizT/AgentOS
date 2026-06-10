"""Provider-neutral data structures for LLM requests and responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("LLM message role must not be empty")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[LLMMessage, ...]
    model: str
    temperature: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not self.messages:
            raise ValueError("LLM request must contain at least one message")
        if not self.model.strip():
            raise ValueError("LLM request model must not be empty")


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: LLMUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not self.model.strip():
            raise ValueError("LLM response model must not be empty")
        if not self.provider.strip():
            raise ValueError("LLM response provider must not be empty")
