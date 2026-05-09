"""Token loading and config-file IO. PRD §4."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # py3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from .errors import AuthError

CONFIG_DIR = Path.home() / ".config" / "todoist-cli"
CONFIG_PATH = CONFIG_DIR / "config.toml"
ENV_VAR = "TODOIST_TOKEN"


@dataclass(frozen=True)
class Config:
    token: str
    default_project: str | None = None
    # When set, the CLI restricts every read and write to the project with
    # this id and any of its descendants. Out-of-scope ids are reported as
    # "not found" (PRD §13). Note: the Todoist personal API token has full
    # account access; this is a CLI-side guardrail, not a hard security
    # boundary.
    scope_project_id: str | None = None
    # When True, `scope set` and `scope clear` refuse to run (exit 3). The
    # operator must edit config.toml by hand to change the scope. Intended
    # for handing the CLI to an agent: flip this on before delivery.
    scope_locked: bool = False


def load_config(*, env: dict[str, str] | None = None, path: Path | None = None) -> Config:
    """Resolve token + default project per PRD §4 precedence.

    Order:
    1. ``TODOIST_TOKEN`` env var.
    2. config.toml.
    3. AuthError.
    """
    env = env if env is not None else dict(os.environ)
    path = path if path is not None else CONFIG_PATH

    token_env = env.get(ENV_VAR, "").strip()
    file_data: dict = {}
    if path.exists():
        with path.open("rb") as fh:
            file_data = tomllib.load(fh)

    token = token_env or str(file_data.get("token", "")).strip()
    if not token:
        raise AuthError("no token. set TODOIST_TOKEN or run 'todoist auth login'")

    default_project = file_data.get("default_project")
    if default_project is not None:
        default_project = str(default_project)

    scope_section = file_data.get("scope") or {}
    scope_project_id = scope_section.get("project_id") if isinstance(scope_section, dict) else None
    if scope_project_id is not None:
        scope_project_id = str(scope_project_id).strip() or None
    scope_locked = bool(scope_section.get("locked", False)) if isinstance(scope_section, dict) else False

    return Config(
        token=token,
        default_project=default_project,
        scope_project_id=scope_project_id,
        scope_locked=scope_locked,
    )


def _read_raw(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _write_atomic(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _serialise(
    token: str,
    default_project: str | None,
    scope_project_id: str | None,
    scope_locked: bool = False,
) -> str:
    body = f'token = "{_toml_escape(token)}"\n'
    if default_project is not None:
        body += f'default_project = "{_toml_escape(default_project)}"\n'
    if scope_project_id is not None or scope_locked:
        body += "\n[scope]\n"
        if scope_project_id is not None:
            body += f'project_id = "{_toml_escape(scope_project_id)}"\n'
        if scope_locked:
            body += "locked = true\n"
    return body


def write_token(token: str, *, path: Path | None = None, default_project: str | None = None) -> None:
    """Write token to config.toml with mode 0600. Preserves an existing
    [scope] section if present. PRD §4."""
    path = path if path is not None else CONFIG_PATH
    existing = _read_raw(path)
    scope_section = existing.get("scope") or {}
    if isinstance(scope_section, dict):
        scope_id = scope_section.get("project_id")
        scope_locked = bool(scope_section.get("locked", False))
    else:
        scope_id = None
        scope_locked = False
    body = _serialise(
        token,
        default_project,
        str(scope_id) if scope_id else None,
        scope_locked,
    )
    _write_atomic(path, body)


def write_scope(project_id: str | None, *, path: Path | None = None) -> None:
    """Set or clear the scope project_id in config.toml. ``None`` clears it.
    Preserves the existing token, default_project, and scope.locked flag.

    Note: this function does NOT itself enforce scope_locked — callers
    (cli._cmd_scope_set / _cmd_scope_clear) check before invoking.
    """
    path = path if path is not None else CONFIG_PATH
    existing = _read_raw(path)
    token = str(existing.get("token", "")).strip()
    if not token:
        raise AuthError("no token saved; run 'todoist auth login' first")
    default_project = existing.get("default_project")
    if default_project is not None:
        default_project = str(default_project)
    scope_section = existing.get("scope") or {}
    scope_locked = bool(scope_section.get("locked", False)) if isinstance(scope_section, dict) else False
    body = _serialise(token, default_project, project_id, scope_locked)
    _write_atomic(path, body)
