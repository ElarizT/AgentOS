from agentos import AgentProcess


class SupervisorQuickstart(AgentProcess):
    name = "SupervisorQuickstart"
    supervisor_strategy = "one_for_one"

    async def on_start(self) -> None:
        self.worker_pid = await self.spawn_child("examples/supervisor_quickstart_worker.py")
        self.send(self.worker_pid, {"cmd": "crash_once"}, message_type="control")

    async def on_message(self, message) -> None:
        if message.type == "event" and message.payload.get("event") == "child_restarted":
            self.remember({"restart": message.payload["details"]}, tags=["supervision"])
