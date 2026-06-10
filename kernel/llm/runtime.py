"""Provider-neutral LLM runtime facade with structured observability."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from kernel.events import RuntimeEvent
from kernel.llm.providers import LLMProvider, LLMProviderError
from kernel.llm.types import LLMMessage, LLMRequest, LLMResponse, LLMUsage


EventSink = Callable[[RuntimeEvent], None] | Any
MessageInput = LLMMessage | Mapping[str, Any]


class LLMRuntime:
    """Stable Agent OS interface for synchronous LLM provider calls."""

    def __init__(self, provider: LLMProvider, event_sink: EventSink | None = None) -> None:
        self.provider = provider
        self.event_sink = event_sink

    def chat(
        self,
        messages: Sequence[MessageInput],
        model: str,
        temperature: float = 0.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        request = LLMRequest(
            messages=tuple(_coerce_message(message) for message in messages),
            model=model,
            temperature=temperature,
            metadata=dict(metadata or {}),
        )
        provider_name = _provider_name(self.provider)
        event_metadata = {"provider": provider_name, "model": request.model}
        self._emit(
            RuntimeEvent.info(
                "LLMRuntime",
                "llm.requested",
                f"LLM request sent to {provider_name}",
                event_metadata,
            )
        )

        try:
            response = self.provider.complete(request)
            if not isinstance(response, LLMResponse):
                raise TypeError("provider returned an invalid LLM response")
        except Exception as exc:
            self._emit(
                RuntimeEvent.error(
                    "LLMRuntime",
                    "llm.failed",
                    f"LLM request failed for {provider_name}",
                    {
                        **event_metadata,
                        "error": True,
                        "error_type": exc.__class__.__name__,
                    },
                )
            )
            if isinstance(exc, LLMProviderError):
                raise
            raise LLMProviderError(f"LLM provider '{provider_name}' failed") from exc

        completed_metadata = {
            "provider": response.provider,
            "model": response.model,
            **_usage_metadata(response.usage),
        }
        self._emit(
            RuntimeEvent.info(
                "LLMRuntime",
                "llm.completed",
                f"LLM request completed with {response.provider}",
                completed_metadata,
            )
        )
        return response

    def _emit(self, event: RuntimeEvent) -> None:
        if self.event_sink is None:
            return
        try:
            append = getattr(self.event_sink, "append", None)
            if callable(append):
                append(event)
            elif callable(self.event_sink):
                self.event_sink(event)
        except Exception:
            # Observability must not change LLM call behavior.
            return


def _coerce_message(message: MessageInput) -> LLMMessage:
    if isinstance(message, LLMMessage):
        return message
    if isinstance(message, Mapping):
        return LLMMessage(
            role=str(message.get("role", "")),
            content=str(message.get("content", "")),
            metadata=dict(message.get("metadata", {})),
        )
    raise TypeError("messages must be LLMMessage objects or mappings")


def _provider_name(provider: LLMProvider) -> str:
    name = str(getattr(provider, "name", "")).strip()
    return name or provider.__class__.__name__


def _usage_metadata(usage: LLMUsage | None) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        name: value
        for name in ("prompt_tokens", "completion_tokens", "total_tokens")
        if (value := getattr(usage, name)) is not None
    }
