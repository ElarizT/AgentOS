from kernel.process import AgentProcess


class CrashingWorker(AgentProcess):
    name = "CrashingWorker"
    capabilities = ("demo-crash",)

    async def on_start(self) -> None:
        raise RuntimeError("intentional supervision demo crash")
