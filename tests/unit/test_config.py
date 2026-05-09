"""Tests for config-path env override and env-token sanitisation."""

from __future__ import annotations

from pathlib import Path

import pytest

from todoist_cli import config
from todoist_cli.errors import AuthError


# ---------------------------------------------------------------------------
# TODOIST_CLI_CONFIG env override (Issue 1)
# ---------------------------------------------------------------------------


def test_resolved_config_path_default_when_unset():
    assert config.resolved_config_path({}) == config.CONFIG_PATH


def test_resolved_config_path_honours_env_override(tmp_path: Path):
    custom = tmp_path / "custom.toml"
    env = {"TODOIST_CLI_CONFIG": str(custom)}
    assert config.resolved_config_path(env) == custom


def test_resolved_config_path_expands_tilde():
    env = {"TODOIST_CLI_CONFIG": "~/foo/bar.toml"}
    assert config.resolved_config_path(env).is_absolute()


def test_load_config_reads_from_overridden_path(tmp_path: Path):
    custom = tmp_path / "x.toml"
    custom.write_text('token = "abc123"\n')
    cfg = config.load_config(env={"TODOIST_CLI_CONFIG": str(custom)})
    assert cfg.token == "abc123"


def test_load_config_overridden_path_with_scope(tmp_path: Path):
    custom = tmp_path / "x.toml"
    custom.write_text(
        'token = "abc123"\n\n[scope]\nproject_id = "p1"\nlocked = true\n'
    )
    cfg = config.load_config(env={"TODOIST_CLI_CONFIG": str(custom)})
    assert cfg.scope_project_id == "p1"
    assert cfg.scope_locked is True


# ---------------------------------------------------------------------------
# Junk env-token fallback (Issue 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "${TODOIST_TOKEN}",   # un-interpolated shell expansion
        "$TODOIST_TOKEN",     # un-interpolated, no braces
        "abc 123",            # whitespace inside token
        "abc\t123",
    ],
)
def test_clean_env_token_rejects_junk(raw):
    assert config._clean_env_token(raw) is None


def test_clean_env_token_accepts_real_looking_value():
    assert config._clean_env_token("a9de51a623340f287476befbddf525fe743c18a1") == \
        "a9de51a623340f287476befbddf525fe743c18a1"


def test_clean_env_token_strips_surrounding_whitespace():
    assert config._clean_env_token("  abc123\n") == "abc123"


def test_load_config_falls_back_to_file_when_env_token_is_junk(tmp_path: Path):
    custom = tmp_path / "c.toml"
    custom.write_text('token = "from-file"\n')
    env = {
        "TODOIST_CLI_CONFIG": str(custom),
        "TODOIST_TOKEN": "${TODOIST_TOKEN}",  # un-interpolated literal
    }
    cfg = config.load_config(env=env)
    assert cfg.token == "from-file"


def test_load_config_env_token_wins_when_clean(tmp_path: Path):
    custom = tmp_path / "c.toml"
    custom.write_text('token = "from-file"\n')
    env = {
        "TODOIST_CLI_CONFIG": str(custom),
        "TODOIST_TOKEN": "from-env-clean-token",
    }
    cfg = config.load_config(env=env)
    assert cfg.token == "from-env-clean-token"


def test_load_config_raises_when_env_junk_and_no_file(tmp_path: Path):
    missing = tmp_path / "missing.toml"
    env = {
        "TODOIST_CLI_CONFIG": str(missing),
        "TODOIST_TOKEN": "${TODOIST_TOKEN}",
    }
    with pytest.raises(AuthError):
        config.load_config(env=env)
