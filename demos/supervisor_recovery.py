from __future__ import annotations

from typing import Any


def build_demo_snapshot() -> dict[str, Any]:
    supervisor_pid = 200
    worker_pid = 202
    return {
        "status": "Recovery Complete",
        "process_rows": [
            {
                "pid": supervisor_pid,
                "name": "RecoverySupervisor",
                "status": "running",
                "execution_mode": "demo",
                "child_count": 1,
                "restart_count": 0,
                "messages_sent": 3,
                "messages_received": 3,
                "message_errors": 0,
            },
            {
                "pid": worker_pid,
                "name": "RecoveryWorkerAgent",
                "status": "running",
                "execution_mode": "demo",
                "supervisor_pid": supervisor_pid,
                "child_count": 0,
                "restart_count": 1,
                "messages_sent": 0,
                "messages_received": 0,
                "message_errors": 0,
            },
        ],
        "hierarchy": {
            "supervisor": "RecoverySupervisor",
            "children": ["RecoveryWorkerAgent (restarted)"],
        },
        "events": [
            {
                "event": "child_terminated",
                "message": "Detected child termination:\nRecoveryWorkerAgent",
            },
            {
                "event": "child_restart_requested",
                "message": "Restarting child:\nRecoveryWorkerAgent",
            },
            {
                "event": "child_restarted",
                "message": "Child restarted:\nRecoveryWorkerAgent",
            },
        ],
    }
