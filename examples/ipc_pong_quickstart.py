from agentos import AgentProcess


class IPCPongQuickstart(AgentProcess):
    name = "IPCPongQuickstart"

    async def on_message(self, message) -> None:
        if message.type == "task_request":
            self.reply(message, {"pong": message.payload["ping"]})
