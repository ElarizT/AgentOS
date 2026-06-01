from agentos import AgentProcess


class MyAgent(AgentProcess):
    name = "MyAgent"

    async def on_start(self) -> None:
        self.remember({"status": "ready"}, tags=["startup"])

    async def on_message(self, message) -> None:
        if message.type == "task_request":
            self.reply(message, {"ok": True, "received": message.payload})
