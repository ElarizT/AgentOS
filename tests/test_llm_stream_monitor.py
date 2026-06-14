from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from textual.widgets import Static

from kernel.dashboard import AgentOSDashboard
from kernel.events import RuntimeEvent
from kernel.llm_stream_monitor import (
    LLMStreamMetric,
    LLMStreamSnapshot,
    build_llm_stream_snapshot,
    format_llm_stream_metric,
    render_llm_stream_snapshot,
)
from kernel.llm.types import LLMUsage


BASE_TIME = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)


def stream_event(
    action: str,
    seconds: int,
    *,
    provider: str = "openai",
    model: str = "gpt-test",
    metadata: dict | None = None,
    message: str = "safe event",
) -> RuntimeEvent:
    values = {"provider": provider, "model": model}
    values.update(metadata or {})
    return RuntimeEvent(
        BASE_TIME + timedelta(seconds=seconds),
        "ERROR" if action == "failed" else "INFO",
        "LLMRuntime",
        f"llm.stream_{action}",
        message,
        values,
    )


def make_dashboard() -> AgentOSDashboard:
    return AgentOSDashboard(kernel=object(), bus=object(), memory=object(), sandbox=object())


def test_empty_stream_snapshot_and_rendering() -> None:
    snapshot = build_llm_stream_snapshot([])

    assert snapshot == LLMStreamSnapshot()
    assert render_llm_stream_snapshot(snapshot) == ["No LLM streaming activity yet."]


def test_stream_lifecycle_accumulates_chunks_chars_usage_and_timestamps() -> None:
    snapshot = build_llm_stream_snapshot(
        [
            stream_event(
                "completed",
                4,
                metadata={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            ),
            stream_event("chunk", 2, metadata={"chunk_index": 0, "delta_chars": 5}),
            stream_event("requested", 0),
            stream_event("chunk", 3, metadata={"chunk_index": 1, "delta_chars": 7}),
            stream_event("started", 1),
        ]
    )

    assert snapshot.metrics == (
        LLMStreamMetric(
            provider="openai",
            model="gpt-test",
            status="completed",
            chunks=2,
            delta_chars=12,
            started_at=BASE_TIME + timedelta(seconds=1),
            completed_at=BASE_TIME + timedelta(seconds=4),
            usage=LLMUsage(10, 4, 14),
        ),
    )


def test_failed_stream_lifecycle_uses_sanitized_error_fields() -> None:
    metric = build_llm_stream_snapshot(
        [
            stream_event("requested", 0),
            stream_event("started", 1),
            stream_event("chunk", 2, metadata={"delta_chars": 8}),
            stream_event(
                "failed",
                3,
                metadata={"error_category": "timeout", "error_type": "TimeoutError"},
            ),
        ]
    ).metrics[0]

    assert metric.status == "failed"
    assert metric.chunks == 1
    assert metric.delta_chars == 8
    assert metric.failed_at == BASE_TIME + timedelta(seconds=3)
    assert metric.error_category == "timeout"
    assert metric.error_type == "TimeoutError"


def test_snapshot_ordering_is_deterministic_and_new_request_resets_route() -> None:
    snapshot = build_llm_stream_snapshot(
        [
            stream_event("chunk", 1, provider="zeta", model="model-b", metadata={"delta_chars": 9}),
            stream_event("requested", 2, provider="zeta", model="model-b"),
            stream_event("requested", 0, provider="alpha", model="model-a"),
        ]
    )

    assert [(metric.provider, metric.model) for metric in snapshot.metrics] == [
        ("alpha", "model-a"),
        ("zeta", "model-b"),
    ]
    assert snapshot.metrics[1].status == "requested"
    assert snapshot.metrics[1].chunks == 0
    assert snapshot.metrics[1].delta_chars == 0


def test_monitor_ignores_prompt_streamed_text_messages_and_unsafe_metadata() -> None:
    prompt = "private prompt"
    delta = "private streamed delta"
    event = stream_event(
        "chunk",
        1,
        metadata={
            "delta_chars": len(delta),
            "prompt": prompt,
            "delta": delta,
            "headers": {"authorization": "private key"},
        },
        message=f"{prompt}: {delta}",
    )

    rendered = repr(render_llm_stream_snapshot(build_llm_stream_snapshot([event])))

    assert "chars=" in rendered
    assert prompt not in rendered
    assert delta not in rendered
    assert "authorization" not in rendered


def test_format_and_render_stream_metric_are_compact() -> None:
    metric = LLMStreamMetric(
        "groq",
        "llama-test",
        "completed",
        chunks=9,
        delta_chars=421,
        usage=LLMUsage(total_tokens=134),
    )

    row = format_llm_stream_metric(metric)

    assert "groq/llama-test" in row
    assert "completed" in row
    assert "chunks=9" in row
    assert "chars=421" in row
    assert "total_tokens=134" in row
    assert render_llm_stream_snapshot([metric]) == [row]


@pytest.mark.asyncio
async def test_dashboard_renders_stream_monitor_with_existing_observability_panels() -> None:
    dashboard = make_dashboard()
    dashboard.refresh_metrics = lambda: None  # type: ignore[method-assign]
    dashboard._runtime_events = [
        stream_event("requested", 0),
        stream_event("started", 1),
        stream_event("chunk", 2, metadata={"chunk_index": 0, "delta_chars": 5}),
    ]

    async with dashboard.run_test(size=(120, 42)) as pilot:
        dashboard._render_llm_stream_monitor()
        dashboard._render_timeline()
        dashboard._render_replay()
        dashboard._render_agent_metrics()
        dashboard._render_ipc_inspector([])
        dashboard._render_dependency_graph()
        await pilot.pause(0)

        title = str(dashboard.query_one("#llm-stream-title", Static).render())
        monitor = str(dashboard.query_one("#llm-stream-monitor", Static).render())

        assert "LLM Stream Monitor" in title
        assert "openai/gpt-test" in monitor
        assert "streaming" in monitor
        assert "chunks=1" in monitor
        assert dashboard.query_one("#runtime-timeline", Static)
        assert dashboard.query_one("#execution-replay", Static)
        assert dashboard.query_one("#agent-metrics", Static)
        assert dashboard.query_one("#ipc-inspector", Static)
        assert dashboard.query_one("#dependency-graph", Static)


@pytest.mark.asyncio
async def test_dashboard_stream_monitor_avoids_unchanged_updates_and_preserves_scroll() -> None:
    dashboard = make_dashboard()
    dashboard.refresh_metrics = lambda: None  # type: ignore[method-assign]
    dashboard._runtime_events = [
        stream_event("requested", index, provider=f"provider-{index}", model="model")
        for index in range(30)
    ]

    async with dashboard.run_test(size=(100, 30)) as pilot:
        dashboard._render_llm_stream_monitor()
        await pilot.pause(0)
        monitor = dashboard.query_one("#llm-stream-monitor", Static)
        monitor.scroll_to(y=4, animate=False, force=True)
        await pilot.pause(0)
        before = monitor.scroll_y
        content_before = dashboard._scrollable_content["#llm-stream-monitor"]

        dashboard._render_llm_stream_monitor()
        dashboard._runtime_events.append(
            stream_event("requested", 31, provider="provider-30", model="model")
        )
        dashboard._render_llm_stream_monitor()
        await pilot.pause(0)

        assert dashboard._scrollable_content["#llm-stream-monitor"] != content_before
        assert monitor.scroll_y == before
