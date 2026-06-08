"""Load and validate external Agent OS project manifests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


MANIFEST_FILENAME = "agentos.toml"
SUPPORTED_AGENT_TYPES = {"basic"}
SUPPORTED_RUNTIMES = {"python"}


@dataclass(frozen=True)
class AgentPermissions:
    network: bool = False
    filesystem: bool = False
    memory: bool = False
    ipc: bool = False


@dataclass(frozen=True)
class ExternalAgentManifest:
    name: str
    type: str
    entrypoint: str
    runtime: str
    permissions: AgentPermissions
    project_dir: Path

    @property
    def entrypoint_path(self) -> Path:
        return self.project_dir / self.entrypoint


def load_external_agent(project_dir: str | Path) -> ExternalAgentManifest:
    """Load and validate an external agent project without executing it."""
    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.is_dir():
        raise ValueError(f"external agent project directory does not exist: {project_path}")

    manifest_path = project_path / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValueError(f"external agent manifest not found: {manifest_path}")

    try:
        with manifest_path.open("rb") as manifest_file:
            raw_manifest = tomllib.load(manifest_file)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid external agent manifest {manifest_path}: {exc}") from exc

    values = {
        field: _required_string(raw_manifest, field, manifest_path)
        for field in ("name", "type", "entrypoint", "runtime")
    }
    if values["type"] not in SUPPORTED_AGENT_TYPES:
        raise ValueError(
            f"unsupported external agent type '{values['type']}'; "
            f"supported types: {', '.join(sorted(SUPPORTED_AGENT_TYPES))}"
        )
    if values["runtime"] not in SUPPORTED_RUNTIMES:
        raise ValueError(
            f"unsupported external agent runtime '{values['runtime']}'; "
            f"supported runtimes: {', '.join(sorted(SUPPORTED_RUNTIMES))}"
        )

    entrypoint_path = (project_path / values["entrypoint"]).resolve()
    if not entrypoint_path.is_relative_to(project_path):
        raise ValueError("external agent entrypoint must be inside the project directory")
    if not entrypoint_path.is_file():
        raise ValueError(f"external agent entrypoint file does not exist: {entrypoint_path}")

    return ExternalAgentManifest(
        **values,
        permissions=_load_permissions(raw_manifest.get("permissions"), manifest_path),
        project_dir=project_path,
    )


def inspect_external_agent(project_dir: str | Path) -> str:
    """Return user-facing inspection output without executing external code."""
    try:
        manifest = load_external_agent(project_dir)
    except ValueError as exc:
        message = str(exc)
        if (
            "external agent manifest not found:" in message
            or "external agent project directory does not exist:" in message
        ):
            project_path = Path(project_dir).expanduser()
            raise ValueError(f"No agentos.toml found at: {project_path}") from exc
        if "unsupported external agent runtime '" in message:
            runtime = message.split("'", 2)[1]
            raise ValueError(f"Unsupported runtime: {runtime}") from exc
        if "unsupported external agent type '" in message:
            agent_type = message.split("'", 2)[1]
            raise ValueError(f"Unsupported agent type: {agent_type}") from exc
        if "external agent entrypoint file does not exist:" in message:
            entrypoint = _manifest_entrypoint(project_dir)
            raise ValueError(f"Entrypoint not found: {entrypoint}") from exc
        raise

    permissions = manifest.permissions
    return (
        "External agent manifest loaded\n"
        "\n"
        f"Name: {manifest.name}\n"
        f"Type: {manifest.type}\n"
        f"Runtime: {manifest.runtime}\n"
        f"Entrypoint: {manifest.entrypoint}\n"
        "\n"
        "Permissions:\n"
        f"network: {_format_bool(permissions.network)}\n"
        f"filesystem: {_format_bool(permissions.filesystem)}\n"
        f"memory: {_format_bool(permissions.memory)}\n"
        f"ipc: {_format_bool(permissions.ipc)}"
    )


def _required_string(manifest: dict[str, Any], field: str, manifest_path: Path) -> str:
    value = manifest.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"external agent manifest {manifest_path} is missing required field '{field}'")
    return value.strip()


def _load_permissions(raw_permissions: Any, manifest_path: Path) -> AgentPermissions:
    if raw_permissions is None:
        return AgentPermissions()
    if not isinstance(raw_permissions, dict):
        raise ValueError(f"external agent manifest {manifest_path} permissions must be a table")

    values: dict[str, bool] = {}
    for field in ("network", "filesystem", "memory", "ipc"):
        value = raw_permissions.get(field, False)
        if not isinstance(value, bool):
            raise ValueError(
                f"external agent manifest {manifest_path} permission '{field}' must be a boolean"
            )
        values[field] = value
    return AgentPermissions(**values)


def _manifest_entrypoint(project_dir: str | Path) -> str:
    manifest_path = Path(project_dir).expanduser().resolve() / MANIFEST_FILENAME
    try:
        with manifest_path.open("rb") as manifest_file:
            entrypoint = tomllib.load(manifest_file).get("entrypoint")
    except (OSError, tomllib.TOMLDecodeError):
        return "unknown"
    return entrypoint if isinstance(entrypoint, str) else "unknown"


def _format_bool(value: bool) -> str:
    return "true" if value else "false"
