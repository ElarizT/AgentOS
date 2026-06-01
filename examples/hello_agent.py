from agentos import AgentProcess


class HelloAgent(AgentProcess):
    name = "HelloAgent"

    async def on_start(self) -> None:
        self.remember({"message": "Hello from Agent OS"}, tags=["hello"])
