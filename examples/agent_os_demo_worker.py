from kernel.process import AgentProcess


class AgentOSDemoWorker(AgentProcess):
    name = "AgentOSDemoWorker"
    capabilities = ("demo-worker",)

    async def on_message(self, message) -> None:
        if message.type == "task_request" and message.payload.get("cmd") == "work":
            self.remember({"event": "isolated_work", "value": message.payload["value"]}, 1)
            self.reply(message, {"ok": True, "result": message.payload["value"] * 2})
