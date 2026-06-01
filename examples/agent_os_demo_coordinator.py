from kernel.process import AgentProcess


class AgentOSDemoCoordinator(AgentProcess):
    name = "AgentOSDemoCoordinator"
    capabilities = ("demo-coordination", "ipc")

    async def on_message(self, message) -> None:
        if message.type != "control":
            return
        if message.payload.get("cmd") == "start_demo":
            await self._run_initial_flow(message.payload)
        elif message.payload.get("cmd") == "crash_probe_restarted":
            await self._verify_restarted_probe(message.payload["crash_pid"])

    async def _run_initial_flow(self, config) -> None:
        worker = await self.request(config["worker_pid"], {"cmd": "work", "value": 21}, timeout=2.0)
        memory = await self.request(
            config["memory_pid"],
            {"cmd": "remember_and_recall", "fact": "worker doubled 21 to 42"},
            timeout=2.0,
        )
        self.remember(
            {"event": "ipc_complete", "worker": worker.payload, "memory": memory.payload},
            3,
            tags=["demo", "ipc"],
        )
        self.send(config["crash_pid"], {"cmd": "crash"}, message_type="control")

    async def _verify_restarted_probe(self, crash_pid) -> None:
        response = await self.request(crash_pid, {"cmd": "health"}, timeout=2.0)
        self.remember(
            {"event": "self_healing_verified", "replacement_pid": crash_pid, "reply": response.payload},
            3,
            importance=0.9,
            tags=["demo", "self-healing"],
        )
