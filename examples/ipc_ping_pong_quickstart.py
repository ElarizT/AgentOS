from agentos import AgentProcess


class IPCPingPongQuickstart(AgentProcess):
    name = "IPCPingPongQuickstart"

    async def on_start(self) -> None:
        pong_pid = await self.spawn_child("examples/ipc_pong_quickstart.py")
        response = await self.request(pong_pid, {"ping": "hello"}, timeout=2.0)
        self.remember({"response": response.payload}, tags=["ipc"])
