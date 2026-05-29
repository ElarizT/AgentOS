from kernel.process import AgentProcess


class SupervisorAgent(AgentProcess):
    name = "SupervisorAgent"
    capabilities = ("supervision",)
    supervisor_strategy = "one_for_one"
    max_restarts = 3
    restart_window_seconds = 15.0
    restart_backoff_seconds = 0.1

    async def on_start(self) -> None:
        await self.spawn_child("examples/crashing_worker.py", restart_policy="permanent")
        await self.spawn_child("examples/restarting_worker.py", restart_policy="permanent")
        self.remember({"event": "supervisor_started", "children": self.list_children()}, 2)

    async def on_message(self, message) -> None:
        if message.type == "event":
            self.remember({"supervision_event": message.payload}, 2)
