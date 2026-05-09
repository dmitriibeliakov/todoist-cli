"""End-to-end CLI tests, with the SDK monkey-patched out."""

from __future__ import annotations

import io
import os
import sys

import pytest

from todoist_cli import cli, config
from tests.conftest import FakeClient


@pytest.fixture
def patched_cli(monkeypatch, fake_client):
    """Replace ``TodoistClient`` so cli.py never imports the real SDK."""
    monkeypatch.setattr(cli, "TodoistClient", lambda token: fake_client)
    monkeypatch.setattr(cli, "load_config", lambda: config.Config(token="fake-token"))
    return fake_client


def _capture(monkeypatch, argv, stdin_text: str = ""):
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    if stdin_text:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def test_cli_task_ls_default(patched_cli, monkeypatch):
    code, out, err = _capture(monkeypatch, ["task", "ls"])
    assert code == 0
    lines = [l for l in out.splitlines() if l]
    # Each line has 6 tab-separated columns.
    for line in lines:
        assert line.count("\t") == 5


def test_cli_top_level_ls_alias(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["ls"])
    assert code == 0
    assert "\t" in out


def test_cli_task_ls_limit(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["task", "ls", "--due", "all", "--limit", "1"])
    assert code == 0
    assert len([l for l in out.splitlines() if l]) == 1


def test_cli_task_ls_limit_zero_exits_2(patched_cli, monkeypatch):
    code, _, err = _capture(monkeypatch, ["task", "ls", "--limit", "0"])
    assert code == 2
    assert err.startswith("error:")


def test_cli_task_ls_json_passthrough(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["task", "ls", "--json"])
    assert code == 0
    assert out.startswith("[")
    assert out.endswith("\n")


def test_cli_task_ls_empty_no_output(patched_cli, monkeypatch):
    # No fixture task has UI priority 2 (api=3).
    code, out, _ = _capture(monkeypatch, ["task", "ls", "--priority", "2", "--due", "all"])
    assert code == 0
    assert out == ""


def test_cli_task_add(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["add", "Buy bread"])
    assert code == 0
    assert "Buy bread" in out
    assert out.count("\t") == 5  # one line, 6 cols


def test_cli_task_add_quiet_silences_stdout(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["add", "X", "--quiet"])
    assert code == 0
    assert out == ""


def test_cli_task_add_priority_inversion(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["add", "Urgent", "--priority", "1"])
    assert code == 0
    line = out.strip()
    assert line.split("\t")[2] == "p1"
    # Underlying API priority should be 4.
    assert patched_cli.added_tasks[-1].priority == 4


def test_cli_task_get(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["task", "get", "1001"])
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("id\t1001")


def test_cli_task_get_unknown_exits_4(patched_cli, monkeypatch):
    code, _, err = _capture(monkeypatch, ["task", "get", "99999"])
    assert code == 4
    assert err.startswith("error:")


def test_cli_task_done(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["done", "1001"])
    assert code == 0
    assert out.strip() == "done\t1001"


def test_cli_task_rm(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["rm", "1001"])
    assert code == 0
    assert out.strip() == "deleted\t1001"


def test_cli_task_pp(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["pp", "1001", "2099-12-31"])
    assert code == 0
    assert "2099-12-31" in out


def test_cli_task_pri(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["task", "pri", "1001", "1"])
    assert code == 0
    assert out.strip().split("\t")[2] == "p1"


def test_cli_task_comment_stdin(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["task", "comment", "1001", "-"], stdin_text="multi\nline body\n")
    assert code == 0
    parts = out.strip().split("\t")
    assert len(parts) == 2  # id, posted_at


def test_cli_proj_ls(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["proj", "ls"])
    assert code == 0
    for line in out.splitlines():
        if line:
            assert line.count("\t") == 1


def test_cli_proj_add(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["proj", "add", "Newp"])
    assert code == 0
    assert out.strip().endswith("\tNewp")


def test_cli_no_token_exits_3(monkeypatch, tmp_path):
    monkeypatch.delenv("TODOIST_TOKEN", raising=False)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "nope.toml")
    # Restore real load_config for this test (no need to patch client).
    code, _, err = _capture(monkeypatch, ["task", "ls"])
    assert code == 3
    assert "no token" in err


def test_cli_help_does_not_raise(monkeypatch):
    code, out, _ = _capture(monkeypatch, ["--help"])
    assert code == 0
    assert "todoist" in out


def test_cli_no_token_in_version(monkeypatch):
    code, out, _ = _capture(monkeypatch, ["--version"])
    assert code == 0
    assert "fake-token" not in out  # belt and braces
    assert "TODOIST_TOKEN" not in out


def test_cli_unknown_command_exits_2(monkeypatch):
    code, _, err = _capture(monkeypatch, ["wat"])
    assert code == 2


# --- Top-level aliases (PRD §6) -----------------------------------------


def test_cli_top_level_get_alias(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["get", "1001"])
    assert code == 0
    assert out.splitlines()[0].startswith("id\t1001")


def test_cli_top_level_add_alias(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["add", "Hi"])
    assert code == 0
    assert "Hi" in out


def test_cli_top_level_done_alias(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["done", "1001"])
    assert code == 0
    assert out.strip() == "done\t1001"


def test_cli_top_level_rm_alias(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["rm", "1001"])
    assert code == 0
    assert out.strip() == "deleted\t1001"


def test_cli_top_level_pp_alias(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["pp", "1001", "2099-12-31"])
    assert code == 0
    assert "2099-12-31" in out


def test_cli_task_pp_alias(patched_cli, monkeypatch):
    """PRD §6 — `task pp` is the alias for `task postpone`."""
    code, out, _ = _capture(monkeypatch, ["task", "pp", "1001", "2099-12-31"])
    assert code == 0
    assert "2099-12-31" in out


# --- Bogus-id error mapping (PRD §7) ------------------------------------


def test_cli_task_rm_unknown_exits_4_single_line(patched_cli, monkeypatch):
    code, _, err = _capture(monkeypatch, ["rm", "99999"])
    assert code == 4
    # Single line, prefixed `error:`, no stack trace.
    err_lines = [l for l in err.splitlines() if l]
    assert len(err_lines) == 1
    assert err_lines[0].startswith("error:")


def test_cli_task_get_unknown_single_line(patched_cli, monkeypatch):
    code, _, err = _capture(monkeypatch, ["task", "get", "99999"])
    assert code == 4
    err_lines = [l for l in err.splitlines() if l]
    assert len(err_lines) == 1
    assert err_lines[0].startswith("error:")


# --- project add color validation (PRD §8.6.2) --------------------------


def test_cli_project_add_invalid_color_exits_2_before_api(patched_cli, monkeypatch):
    pre_count = len(patched_cli.added_projects)
    code, _, err = _capture(monkeypatch, ["project", "add", "X", "--color", "rainbow"])
    assert code == 2
    assert err.startswith("error:")
    # No API call was made.
    assert len(patched_cli.added_projects) == pre_count


def test_cli_project_add_valid_color_succeeds(patched_cli, monkeypatch):
    code, out, _ = _capture(monkeypatch, ["project", "add", "X", "--color", "berry_red"])
    assert code == 0
    assert "X" in out


# --- auth login --json --------------------------------------------------


def test_cli_auth_login_json_emits_json(monkeypatch, tmp_path):
    import json as _json

    from todoist_cli import config as _config

    # Patch config write target and TodoistClient validation.
    monkeypatch.setattr(_config, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(cli, "TodoistClient", lambda token: type("C", (), {"list_projects": lambda self: []})())
    code, out, err = _capture(monkeypatch, ["auth", "login", "--json"], stdin_text="abc123\n")
    assert code == 0
    # Stdout must be parseable JSON, NOT the human "saved <path>" line.
    assert "saved /" not in out
    parsed = _json.loads(out)
    assert "saved" in parsed


# ---------------------------------------------------------------------------
# scope.locked enforcement (CTO security review #2)
# ---------------------------------------------------------------------------


def test_cli_scope_set_blocked_when_locked(patched_cli, monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: config.Config(token="fake-token", scope_project_id="p_inbox", scope_locked=True),
    )
    code, out, err = _capture(monkeypatch, ["scope", "set", "Side project: book"])
    assert code == 3
    assert "scope is locked" in err
    assert out == ""


def test_cli_scope_clear_blocked_when_locked(patched_cli, monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: config.Config(token="fake-token", scope_project_id="p_inbox", scope_locked=True),
    )
    code, out, err = _capture(monkeypatch, ["scope", "clear"])
    assert code == 3
    assert "scope is locked" in err


def test_cli_scope_show_reports_locked(patched_cli, monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: config.Config(token="fake-token", scope_project_id="p_inbox", scope_locked=True),
    )
    code, out, _ = _capture(monkeypatch, ["scope", "show"])
    assert code == 0
    assert "locked" in out


def test_cli_task_get_outside_scope_exits_4(patched_cli, monkeypatch):
    """Belt-and-braces: out-of-scope task id surfaces as 'not found'."""
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: config.Config(token="fake-token", scope_project_id="p_inbox"),
    )
    # 1003 lives in p_book per the fake fixture; p_inbox is the scope.
    code, _, err = _capture(monkeypatch, ["task", "get", "1003"])
    assert code == 4
    assert "not found" in err


# ---------------------------------------------------------------------------
# MCP server fail-closed (delegation safety)
# ---------------------------------------------------------------------------


def test_mcp_main_refuses_to_start_without_scope(monkeypatch):
    """MCP wrapper must NOT silently expose full account access when no
    scope is set. The whole purpose of running in MCP mode is delegation."""
    from todoist_cli import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_config",
        lambda: config.Config(token="t", scope_project_id=None),
    )
    monkeypatch.delenv("TODOIST_MCP_ALLOW_UNSCOPED", raising=False)
    with pytest.raises(SystemExit) as exc:
        mcp_server.main()
    assert exc.value.code == 3


def test_mcp_main_starts_with_scope(monkeypatch):
    from todoist_cli import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_config",
        lambda: config.Config(token="t", scope_project_id="6abc"),
    )
    started = {"called": False}

    def fake_run():
        started["called"] = True

    monkeypatch.setattr(mcp_server.mcp, "run", fake_run)
    mcp_server.main()
    assert started["called"]


def test_mcp_main_allow_unscoped_env_overrides(monkeypatch):
    from todoist_cli import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_config",
        lambda: config.Config(token="t", scope_project_id=None),
    )
    monkeypatch.setenv("TODOIST_MCP_ALLOW_UNSCOPED", "1")
    started = {"called": False}
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: started.__setitem__("called", True))
    mcp_server.main()
    assert started["called"]
