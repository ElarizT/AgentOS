from types import SimpleNamespace

import pytest
from textual.widgets import DataTable, RichLog, Static

from kernel.dashboard import AgentOSDashboard, MailboxMetric
from main import format_external_agent_run


class EmptyTelemetry:
    pass


def make_dashboard() -> AgentOSDashboard:
    return AgentOSDashboard(
        kernel=EmptyTelemetry(),
        bus=EmptyTelemetry(),
        memory=EmptyTelemetry(),
        sandbox=EmptyTelemetry(),
    )


def process_rows(count: int, *, suffix: str = "") -> list[dict[str, object]]:
    return [
        {
            "pid": 100 + index,
            "name": f"LongExternalProcessName{index}{suffix}",
            "status": "running",
            "execution_mode": "in-process",
            "supervisor_strategy": "one_for_one",
            "messages_sent": index,
            "messages_received": index,
            "message_errors": 0,
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_execution_panel_renders_external_lifecycle_and_has_useful_height() -> None:
    dashboard = make_dashboard()
    dashboard.refresh_metrics = lambda: None  # type: ignore[method-assign]
    result = SimpleNamespace(
        manifest_name="external_basic_agent",
        succeeded=True,
        output="[ExternalBasicAgent] Started",
        error=None,
    )

    async with dashboard.run_test(size=(120, 36)) as pilot:
        dashboard._write_execution_log(format_external_agent_run(result))
        await pilot.pause(0)

        log = dashboard.query_one("#wasm-log", RichLog)
        output = "\n".join(line.text for line in log.lines)
        title = str(dashboard.query_one("#wasm-pane .pane-title", Static).render())

        assert log.region.height >= 7
        assert "Execution / WASM Isolation Monitor" in title
        assert "Manifest validated" in output
        assert "Agent loaded" in output
        assert "Lifecycle executed" in output
        assert "Completed" in output


@pytest.mark.asyncio
async def test_process_registry_preserves_scroll_and_content_across_refresh() -> None:
    dashboard = make_dashboard()
    dashboard.refresh_metrics = lambda: None  # type: ignore[method-assign]

    async with dashboard.run_test(size=(90, 30)) as pilot:
        table = dashboard.query_one("#process-table", DataTable)
        dashboard._render_processes(process_rows(30))
        await pilot.pause(0)
        table.scroll_to(x=8, y=8, animate=False, force=True)
        await pilot.pause(0)
        before = (table.scroll_x, table.scroll_y)

        dashboard._render_processes(process_rows(30))
        dashboard._render_processes(process_rows(30, suffix="-updated"))
        await pilot.pause(0)

        assert table.row_count == 30
        assert (table.scroll_x, table.scroll_y) == before


@pytest.mark.asyncio
async def test_ipc_and_agent_tree_still_render_after_layout_change() -> None:
    dashboard = make_dashboard()
    dashboard.refresh_metrics = lambda: None  # type: ignore[method-assign]
    dashboard._demo_hierarchy = {
        "supervisor": "Supervisor",
        "children": [f"Agent{index}" for index in range(12)],
    }

    async with dashboard.run_test(size=(100, 32)) as pilot:
        dashboard._render_mailboxes(
            [MailboxMetric(f"Agent{index}", index, 20, "Direct") for index in range(12)]
        )
        dashboard._render_agent_tree()
        await pilot.pause(0)

        ipc = dashboard.query_one("#ipc-table", DataTable)
        tree = str(dashboard.query_one("#agent-tree", Static).render())
        assert ipc.row_count == 12
        assert "Supervisor" in tree
        assert "Agent11" in tree


@pytest.mark.asyncio
async def test_execution_log_does_not_jump_when_user_scrolled_up() -> None:
    dashboard = make_dashboard()
    dashboard.refresh_metrics = lambda: None  # type: ignore[method-assign]

    async with dashboard.run_test(size=(100, 30)) as pilot:
        log = dashboard.query_one("#wasm-log", RichLog)
        for index in range(30):
            dashboard._write_execution_log(f"line {index}", scroll_end=False)
        await pilot.pause(0)
        log.scroll_to(y=3, animate=False, force=True)
        await pilot.pause(0)
        before = log.scroll_y

        dashboard._write_execution_log("new telemetry", scroll_end=False)
        await pilot.pause(0)

        assert log.scroll_y == before
