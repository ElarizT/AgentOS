from kernel.process import AgentProcess


class AgentOSDemoMemory(AgentProcess):
    name = "AgentOSDemoMemory"
    capabilities = ("demo-memory",)
    token_budget = 6

    async def on_message(self, message) -> None:
        if message.type != "task_request" or message.payload.get("cmd") != "remember_and_recall":
            return
        self.remember(
            {"fact": message.payload["fact"]},
            7,
            importance=0.9,
            tags=["demo", "durable-fact"],
        )
        recalled = self.recall(tags=["durable-fact"], limit=1)
        self.reply(message, {"recalled": recalled[0]["content"], "tier": recalled[0]["tier"]})
