from agentos import AgentProcess


class SupervisorQuickstartWorker(AgentProcess):
    name = "SupervisorQuickstartWorker"

    async def on_message(self, message) -> None:
        if message.type == "control" and message.payload.get("cmd") == "crash_once":
            raise RuntimeError("intentional quickstart restart")
