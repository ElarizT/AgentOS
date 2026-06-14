"""Safe, event-derived LLM streaming observability helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from kernel.events import RuntimeEvent
from kernel.llm.types import LLMUsage


_STREAM_EVENTS = {
    "llm.stream_requested",
    "llm.stream_started",
    "llm.stream_chunk",
    "llm.stream_completed",
    "llm.stream_failed",
}


@dataclass(frozen=True)
class LLMStreamMetric:
    """Latest safe streaming state for one provider and model pair."""

    provider: str
    model: str
    status: str
    chunks: int = 0
    delta_chars: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    usage: LLMUsage | None = None
    error_category: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class LLMStreamSnapshot:
    """Deterministically ordered LLM streaming monitor snapshot."""

    metrics: tuple[LLMStreamMetric, ...] = ()


def build_llm_stream_snapshot(events: Iterable[Any] = ()) -> LLMStreamSnapshot:
    """Build latest stream state using only safe structured event metadata."""
    structured = [
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, RuntimeEvent) and event.event_type in _STREAM_EVENTS
    ]
    structured.sort(key=lambda item: (item[1].timestamp, item[0]))

    metrics: dict[tuple[str, str], LLMStreamMetric] = {}
    for _, event in structured:
        provider = _safe_text(event.metadata, "provider")
        model = _safe_text(event.metadata, "model")
        if provider is None or model is None:
            continue
        key = (provider, model)
        current = metrics.get(key, LLMStreamMetric(provider, model, "requested"))

        if event.event_type == "llm.stream_requested":
            metrics[key] = LLMStreamMetric(provider, model, "requested")
        elif event.event_type == "llm.stream_started":
            metrics[key] = replace(
                current,
                status="streaming",
                started_at=current.started_at or event.timestamp,
            )
        elif event.event_type == "llm.stream_chunk":
            metrics[key] = replace(
                current,
                status="streaming",
                started_at=current.started_at or event.timestamp,
                chunks=current.chunks + 1,
                delta_chars=current.delta_chars
                + (_safe_nonnegative_int(event.metadata, "delta_chars") or 0),
                usage=_safe_usage(event.metadata) or current.usage,
            )
        elif event.event_type == "llm.stream_completed":
            metrics[key] = replace(
                current,
                status="completed",
                completed_at=event.timestamp,
                usage=_safe_usage(event.metadata) or current.usage,
                error_category=None,
                error_type=None,
            )
        elif event.event_type == "llm.stream_failed":
            metrics[key] = replace(
                current,
                status="failed",
                failed_at=event.timestamp,
                error_category=_safe_text(event.metadata, "error_category"),
                error_type=_safe_text(event.metadata, "error_type"),
            )

    return LLMStreamSnapshot(
        tuple(
            metrics[key]
            for key in sorted(metrics, key=lambda item: (item[0], item[1]))
        )
    )


def format_llm_stream_metric(metric: LLMStreamMetric) -> str:
    """Format one compact LLM stream monitor row."""
    route = f"{metric.provider}/{metric.model}"
    parts = [
        f"{route:<28}",
        f"{metric.status:<10}",
        f"chunks={metric.chunks}",
        f"chars={metric.delta_chars}",
    ]
    if metric.usage is not None:
        parts.extend(
            f"{name}={value}"
            for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            if (value := getattr(metric.usage, name)) is not None
        )
    else:
        parts.append("usage=pending")
    error = metric.error_category or metric.error_type
    if error is not None:
        parts.append(f"error={error}")
    if metric.error_category is not None and metric.error_type is not None:
        parts.append(f"type={metric.error_type}")
    return "  ".join(parts)


def render_llm_stream_snapshot(
    snapshot: LLMStreamSnapshot | Iterable[LLMStreamMetric],
) -> list[str]:
    """Render stable monitor rows with a deterministic empty state."""
    metrics = snapshot.metrics if isinstance(snapshot, LLMStreamSnapshot) else tuple(snapshot)
    if not metrics:
        return ["No LLM streaming activity yet."]
    return [format_llm_stream_metric(metric) for metric in metrics]


def _safe_usage(metadata: Mapping[str, Any]) -> LLMUsage | None:
    values = {
        name: _safe_nonnegative_int(metadata, name)
        for name in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    if all(value is None for value in values.values()):
        return None
    return LLMUsage(**values)


def _safe_nonnegative_int(metadata: Mapping[str, Any], name: str) -> int | None:
    value = metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _safe_text(metadata: Mapping[str, Any], name: str) -> str | None:
    value = metadata.get(name)
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text:
        return None
    return text[:120]
