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
    return Config(token=token, default_project=default_project)


def write_token(token: str, *, path: Path | None = None, default_project: str | None = None) -> None:
    """Write token to config.toml with mode 0600. PRD §4."""
    path = path if path is not None else CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    # Quote-safe TOML emit; tokens are alphanumeric but be defensive.
    body = f'token = "{token}"\n'
    if default_project is not None:
        # Escape backslash and double-quotes per TOML basic strings.
        esc = default_project.replace("\\", "\\\\").replace('"', '\\"')
        body += f'default_project = "{esc}"\n'

    # Write with restrictive perms from creation.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body.encode("utf-8"))
    finally:
        os.close(fd)
    # Belt-and-braces in case umask interfered.
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
