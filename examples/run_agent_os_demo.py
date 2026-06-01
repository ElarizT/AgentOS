from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from kernel.memory_store import PersistentMemoryManager
from kernel.process import AgentMessage, ProcessRegistry


class DemoKernel:
    def register_agent_capability(self, _agent_name: str, _capability: str) -> None:
        pass

    def unregister_agent(self, _agent_name: str) -> None:
        pass


class DemoBus:
    def __init__(self) -> None:
        self.mailboxes: dict[str, asyncio.Queue[AgentMessage]] = {}
        self.sizes: dict[str, int] = {}

    def register_mailbox(self, agent_name: str, buffer_size: int) -> None:
        self.mailboxes[agent_name] = asyncio.Queue(maxsize=buffer_size)
        self.sizes[agent_name] = buffer_size

    def unregister_mailbox(self, agent_name: str) -> bool:
        self.sizes.pop(agent_name, None)
        return self.mailboxes.pop(agent_name, None) is not None

    def send_message(self, message: AgentMessage) -> None:
        self.mailboxes[message.receiver].put_nowait(message)

    async def recv_message(self, agent_name: str) -> AgentMessage:
        return await self.mailboxes[agent_name].get()

    def get_mailbox_metrics(self) -> list[tuple[str, int, int, str]]:
        return [
            (name, mailbox.qsize(), self.sizes[name], "Direct")
            for name, mailbox in self.mailboxes.items()
        ]


async def run_demo() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-os-demo-") as memory_dir:
        memory = PersistentMemoryManager(Path(memory_dir))
        registry = ProcessRegistry(kernel=DemoKernel(), bus=DemoBus(), memory=memory)
        supervisor = await registry.run_path("examples/agent_os_demo_supervisor.py")

        deadline = asyncio.get_running_loop().time() + 8.0
        while asyncio.get_running_loop().time() < deadline:
            records = memory.recall("AgentOSDemoCoordinator", tags=["self-healing"])
            if records:
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("demo timed out before the restarted crash probe replied")

        rows = await registry.list_processes()
        durable = memory.recall("AgentOSDemoMemory", tags=["durable-fact"])
        summary = {
            "supervisor_pid": supervisor.pid,
            "self_healing": records[0]["content"],
            "persistent_memory": durable[0]["content"],
            "processes": [
                {
                    "pid": row["pid"],
                    "name": row["name"],
                    "status": row["status"],
                    "mode": row["execution_mode"],
                    "parent_pid": row["parent_pid"],
                    "restarts": row["restart_count"],
                    "ipc": [
                        row["messages_sent"],
                        row["messages_received"],
                        row["message_errors"],
                    ],
                    "paged_memory": row["memory_paged_count"],
                }
                for row in rows
            ],
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        await registry.kill(supervisor.pid)


if __name__ == "__main__":
    asyncio.run(run_demo())
