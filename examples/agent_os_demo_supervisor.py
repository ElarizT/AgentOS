from kernel.process import AgentProcess


class AgentOSDemoSupervisor(AgentProcess):
    name = "AgentOSDemoSupervisor"
    capabilities = ("demo-supervision",)
    supervisor_strategy = "one_for_one"
    max_restarts = 3
    restart_window_seconds = 30.0
    restart_backoff_seconds = 0.2

    async def on_start(self) -> None:
        memory_pid = await self.spawn_child("examples/agent_os_demo_memory.py")
        worker_pid = await self.spawn_child("examples/agent_os_demo_worker.py", execution_mode="isolated")
        crash_pid = await self.spawn_child("examples/agent_os_demo_crash_probe.py", execution_mode="isolated")
        coordinator_pid = await self.spawn_child("examples/agent_os_demo_coordinator.py")
        self.coordinator_pid = coordinator_pid
        self.send(
            coordinator_pid,
            {
                "cmd": "start_demo",
                "memory_pid": memory_pid,
                "worker_pid": worker_pid,
                "crash_pid": crash_pid,
            },
            message_type="control",
        )
        self.remember({"event": "demo_started", "children": self.list_children()}, 2, tags=["demo"])

    async def on_message(self, message) -> None:
        if message.type != "event":
            return
        self.remember({"supervision_event": message.payload}, 2, tags=["demo", "supervision"])
        if message.payload.get("event") == "child_restarted":
            details = message.payload.get("details", {})
            if details.get("child_name") == "AgentOSDemoCrashProbe":
                self.send(
                    self.coordinator_pid,
                    {"cmd": "crash_probe_restarted", "crash_pid": details["new_pid"]},
                    message_type="control",
                )
