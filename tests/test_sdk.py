from pathlib import Path

import pytest

from agentos import AgentProcess
from kernel.process import AgentProcess as KernelAgentProcess
from kernel.process import ProcessRegistry
from kernel.shell_help import (
    DEMO_COMMANDS,
    INSPECT_COMMAND,
    SUPERVISOR_RECOVERY_DEMO_PATH,
    format_demo_browser,
    format_shell_help,
    parse_inspect_path,
)
from test_process_registry import FakeBus, FakeKernel, FakeMemory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_FILES = [
    "examples/hello_agent.py",
    "examples/echo_agent.py",
    "examples/memory_agent.py",
    "examples/supervisor_quickstart.py",
    "examples/supervisor_quickstart_worker.py",
    "examples/ipc_ping_pong_quickstart.py",
    "examples/ipc_pong_quickstart.py",
    "templates/basic_agent.py",
]


def make_registry(tmp_path) -> ProcessRegistry:
    return ProcessRegistry(
        kernel=FakeKernel(),
        bus=FakeBus(),
        memory=FakeMemory(),
        allowed_roots=[tmp_path],
    )


def write_script(tmp_path, source: str) -> Path:
    path = tmp_path / "beginner_agent.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_public_sdk_exports_agent_process() -> None:
    assert AgentProcess is KernelAgentProcess


def test_quickstart_examples_compile_and_pass_agent_preflight(tmp_path) -> None:
    registry = make_registry(tmp_path)
    for relative_path in QUICKSTART_FILES:
        path = PROJECT_ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        registry._preflight_source(path)


def test_shell_help_includes_quickstart_commands(tmp_path) -> None:
    help_text = format_shell_help(tmp_path)

    assert "run <path>" in help_text
    assert "inspect <path>" in help_text
    assert "ps" in help_text
    assert "kill <PID>" in help_text
    assert "demos" in help_text
    assert "help" in help_text
    assert "AGENT_OS_PROCESS_ISOLATION=in-process" in help_text
    assert "AGENT_OS_PROCESS_ISOLATION=process" in help_text
    assert "run examples/hello_agent.py" in help_text
    assert "inspect examples/external_basic_agent" in help_text
    assert "run examples/research_team" in help_text
    assert "docs/sdk_quickstart.md" in help_text


def test_demo_browser_lists_research_team_run_command() -> None:
    output = format_demo_browser()

    assert "Available Demos" in output
    assert "research_team" in output
    assert "run examples/research_team" in output
    assert "supervisor_recovery" in output
    assert f"run {SUPERVISOR_RECOVERY_DEMO_PATH}" in output
    assert "automatic restart" in output


def test_demo_browser_command_and_alias_are_recognized() -> None:
    assert {"demo", "demos"} <= DEMO_COMMANDS


def test_inspect_external_agent_command_is_recognized() -> None:
    assert INSPECT_COMMAND == "inspect"
    assert parse_inspect_path("inspect ./examples/external_basic_agent") == (
        "./examples/external_basic_agent"
    )
    assert parse_inspect_path(r"inspect .\examples\external_basic_agent") == (
        r".\examples\external_basic_agent"
    )


def test_inspect_command_requires_one_path() -> None:
    with pytest.raises(ValueError, match="usage: inspect <path>"):
        parse_inspect_path("inspect")


@pytest.mark.asyncio
async def test_missing_agent_process_subclass_has_beginner_friendly_error(tmp_path) -> None:
    path = write_script(tmp_path, 'MESSAGE = "hello"\n')

    with pytest.raises(ValueError, match="must define an AgentProcess subclass"):
        await make_registry(tmp_path).run_path(str(path))


@pytest.mark.asyncio
async def test_missing_agent_name_has_beginner_friendly_error(tmp_path) -> None:
    path = write_script(
        tmp_path,
        "from agentos import AgentProcess\n\nclass MissingName(AgentProcess):\n    pass\n",
    )

    with pytest.raises(ValueError, match="must define a unique non-empty name"):
        await make_registry(tmp_path).run_path(str(path))


@pytest.mark.asyncio
async def test_invalid_import_points_to_public_sdk(tmp_path) -> None:
    path = write_script(
        tmp_path,
        "import os\nfrom agentos import AgentProcess\n\nclass BadImport(AgentProcess):\n    name = \"BadImport\"\n",
    )

    with pytest.raises(ValueError, match="from agentos import AgentProcess"):
        await make_registry(tmp_path).run_path(str(path))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("mailbox_size", "0"),
        ("token_budget", '"lots"'),
    ],
)
async def test_invalid_resource_setting_has_beginner_friendly_error(tmp_path, setting, value) -> None:
    path = write_script(
        tmp_path,
        "from agentos import AgentProcess\n\n"
        "class BadSetting(AgentProcess):\n"
        '    name = "BadSetting"\n'
        f"    {setting} = {value}\n",
    )

    with pytest.raises(ValueError, match=f"{setting} must be a positive integer"):
        await make_registry(tmp_path).run_path(str(path))
