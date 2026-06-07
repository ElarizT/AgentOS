from demos.supervisor_recovery import build_demo_snapshot
from kernel.dashboard import AgentOSDashboard
from kernel.shell_help import SUPERVISOR_RECOVERY_DEMO_PATH, is_supervisor_recovery_demo_path


class EmptyTelemetry:
    pass


def test_supervisor_recovery_demo_path_is_runnable_convention() -> None:
    assert SUPERVISOR_RECOVERY_DEMO_PATH == "demos/supervisor_recovery"
    assert is_supervisor_recovery_demo_path("demos/supervisor_recovery")
    assert is_supervisor_recovery_demo_path("demos\\supervisor_recovery\\")


def test_supervisor_recovery_snapshot_populates_dashboard_state() -> None:
    dashboard = AgentOSDashboard(
        kernel=EmptyTelemetry(),
        bus=EmptyTelemetry(),
        memory=EmptyTelemetry(),
        sandbox=EmptyTelemetry(),
    )

    dashboard.load_supervisor_recovery_snapshot(build_demo_snapshot())

    assert dashboard._demo_status == "Recovery Complete"
    assert [row["name"] for row in dashboard._demo_process_rows] == [
        "RecoverySupervisor",
        "RecoveryWorkerAgent",
    ]
    worker = dashboard._demo_process_rows[1]
    assert worker["status"] == "running"
    assert worker["restart_count"] == 1
    assert [event["event"] for event in dashboard._demo_supervision_events] == [
        "child_terminated",
        "child_restart_requested",
        "child_restarted",
    ]


def test_supervisor_recovery_tree_marks_worker_restarted() -> None:
    dashboard = AgentOSDashboard(
        kernel=EmptyTelemetry(),
        bus=EmptyTelemetry(),
        memory=EmptyTelemetry(),
        sandbox=EmptyTelemetry(),
    )
    dashboard.load_supervisor_recovery_snapshot(build_demo_snapshot())

    tree = AgentOSDashboard._format_agent_tree(dashboard._demo_hierarchy)

    assert "RecoverySupervisor" in tree
    assert "RecoveryWorkerAgent (restarted)" in tree


def test_supervisor_recovery_snapshot_contains_restart_sequence() -> None:
    state = build_demo_snapshot()

    assert [event["event"] for event in state["events"]] == [
        "child_terminated",
        "child_restart_requested",
        "child_restarted",
    ]
