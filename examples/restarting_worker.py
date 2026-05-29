from kernel.process import AgentProcess


class RestartingWorker(AgentProcess):
    name = "RestartingWorker"
    capabilities = ("restartable",)

    async def on_start(self) -> None:
        self.remember({"event": "worker_ready", "pid": self.pid}, 1)

    async def on_message(self, message) -> None:
        if message.type == "control" and message.payload.get("cmd") == "crash":
            raise RuntimeError("intentional worker crash")
        self.remember({"event": "worker_message", "payload": message.payload}, 1)
