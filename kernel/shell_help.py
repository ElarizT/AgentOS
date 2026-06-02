from __future__ import annotations

from pathlib import Path


def format_shell_help(process_root: Path) -> str:
    return (
        "commands:\n"
        "  run <path>   start an AgentProcess script under "
        f"{process_root}\n"
        "  ps           list process registry status\n"
        "  kill <PID>   gracefully stop and unregister a process\n"
        "  help         show this quick reference\n"
        "\n"
        "examples:\n"
        "  run examples/hello_agent.py\n"
        "  run examples/memory_agent.py\n"
        "  run examples/supervisor_quickstart.py\n"
        "  run examples/research_team\n"
        "\n"
        "execution mode:\n"
        "  AGENT_OS_PROCESS_ISOLATION=in-process  trusted local mode (default)\n"
        "  AGENT_OS_PROCESS_ISOLATION=process     spawned child process isolation\n"
        "\n"
        "SDK guide: docs/sdk_quickstart.md"
    )
