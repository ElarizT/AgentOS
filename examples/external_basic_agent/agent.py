from agentos import AgentProcess


class ExternalBasicAgent(AgentProcess):
    name = "external_basic_agent"

    async def on_start(self) -> None:
        print("[ExternalBasicAgent] Started")
