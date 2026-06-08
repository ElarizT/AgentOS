from pathlib import Path

import pytest

from agentos import AgentPermissions, inspect_external_agent, load_external_agent


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_project(tmp_path, manifest: str, *, entrypoint: bool = True) -> Path:
    project_dir = tmp_path / "external_agent"
    project_dir.mkdir()
    (project_dir / "agentos.toml").write_text(manifest, encoding="utf-8")
    if entrypoint:
        (project_dir / "agent.py").write_text("# external agent\n", encoding="utf-8")
    return project_dir


VALID_MANIFEST = """
name = "test_agent"
type = "basic"
entrypoint = "agent.py"
runtime = "python"

[permissions]
memory = true
ipc = true
"""


def test_valid_manifest_loads_successfully(tmp_path) -> None:
    project_dir = write_project(tmp_path, VALID_MANIFEST)

    manifest = load_external_agent(project_dir)

    assert manifest.name == "test_agent"
    assert manifest.type == "basic"
    assert manifest.runtime == "python"
    assert manifest.entrypoint_path == project_dir / "agent.py"
    assert manifest.permissions == AgentPermissions(memory=True, ipc=True)


def test_missing_manifest_fails_clearly(tmp_path) -> None:
    with pytest.raises(ValueError, match="external agent manifest not found"):
        load_external_agent(tmp_path)


def test_missing_required_field_fails_clearly(tmp_path) -> None:
    project_dir = write_project(tmp_path, VALID_MANIFEST.replace('name = "test_agent"\n', ""))

    with pytest.raises(ValueError, match="missing required field 'name'"):
        load_external_agent(project_dir)


def test_unsupported_runtime_fails_clearly(tmp_path) -> None:
    project_dir = write_project(tmp_path, VALID_MANIFEST.replace('runtime = "python"', 'runtime = "wasm"'))

    with pytest.raises(ValueError, match="unsupported external agent runtime 'wasm'"):
        load_external_agent(project_dir)


def test_unsupported_agent_type_fails_clearly(tmp_path) -> None:
    project_dir = write_project(tmp_path, VALID_MANIFEST.replace('type = "basic"', 'type = "supervisor"'))

    with pytest.raises(ValueError, match="unsupported external agent type 'supervisor'"):
        load_external_agent(project_dir)


def test_missing_entrypoint_file_fails_clearly(tmp_path) -> None:
    project_dir = write_project(tmp_path, VALID_MANIFEST, entrypoint=False)

    with pytest.raises(ValueError, match="external agent entrypoint file does not exist"):
        load_external_agent(project_dir)


def test_sample_external_agent_manifest_loads_successfully() -> None:
    manifest = load_external_agent(PROJECT_ROOT / "examples" / "external_basic_agent")

    assert manifest.name == "external_basic_agent"
    assert manifest.entrypoint == "agent.py"


def test_inspect_sample_external_agent_includes_manifest_and_permissions() -> None:
    output = inspect_external_agent(PROJECT_ROOT / "examples" / "external_basic_agent")

    for expected in (
        "External agent manifest loaded",
        "Name: external_basic_agent",
        "Type: basic",
        "Runtime: python",
        "Entrypoint: agent.py",
        "network: false",
        "filesystem: false",
        "memory: true",
        "ipc: true",
    ):
        assert expected in output


def test_inspect_missing_manifest_returns_friendly_error(tmp_path) -> None:
    with pytest.raises(ValueError, match="No agentos.toml found at:"):
        inspect_external_agent(tmp_path)


def test_inspect_unsupported_runtime_returns_friendly_error(tmp_path) -> None:
    project_dir = write_project(tmp_path, VALID_MANIFEST.replace('runtime = "python"', 'runtime = "node"'))

    with pytest.raises(ValueError, match="Unsupported runtime: node"):
        inspect_external_agent(project_dir)


def test_inspect_missing_entrypoint_returns_friendly_error(tmp_path) -> None:
    project_dir = write_project(tmp_path, VALID_MANIFEST, entrypoint=False)

    with pytest.raises(ValueError, match="Entrypoint not found: agent.py"):
        inspect_external_agent(project_dir)
