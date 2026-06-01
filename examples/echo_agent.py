from agentos import AgentProcess


class EchoAgent(AgentProcess):
    name = "EchoAgent"
    capabilities = ("echo",)

    async def on_message(self, message) -> None:
        if message.type == "task_request":
            self.reply(message, {"echo": message.payload})
