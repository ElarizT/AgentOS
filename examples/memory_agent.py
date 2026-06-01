from agentos import AgentProcess


class MemoryAgent(AgentProcess):
    name = "MemoryAgent"

    async def on_start(self) -> None:
        self.remember({"fact": "Agent OS memory is process-local"}, tags=["quickstart"])
        recalled = self.recall(tags=["quickstart"])
        self.remember({"recalled_count": len(recalled)}, tags=["quickstart-result"])
