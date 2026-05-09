"""--help snapshot test (PRD §6.7 / §8.7).

We don't pin the exact byte-for-byte argparse output (it changes across
Python versions) — instead we snapshot the *contract surface* of each
subcommand's help: the listed flags and their argument names. That's what
agents and the README pointer actually depend on.
"""

from __future__ import annotations

import io
import re
import sys
from contextlib import redirect_stdout, redirect_stderr

import pytest

from todoist_cli import cli

# (argv that prints help, set of strings every help block must contain)
HELP_CASES = [
    (["--help"], {"task", "project", "--version"}),
    (["task", "--help"], {"ls", "get", "add", "done", "rm", "postpone", "pri", "comment"}),
    (["task", "ls", "--help"], {"--project", "--due", "--priority", "--limit", "--json", "--quiet"}),
    (["task", "get", "--help"], {"id", "--json"}),
    (["task", "add", "--help"], {"content", "--due", "--priority", "--project", "--parent"}),
    (["task", "done", "--help"], {"id"}),
    (["task", "rm", "--help"], {"id"}),
    (["task", "postpone", "--help"], {"id", "due"}),
    (["task", "pri", "--help"], {"id", "priority"}),
    (["task", "comment", "--help"], {"id", "text"}),
    (["project", "--help"], {"ls", "add"}),
    (["project", "ls", "--help"], {"--json"}),
    (["project", "add", "--help"], {"name", "--color"}),
    (["proj", "ls", "--help"], {"--json"}),
    (["auth", "--help"], {"login"}),
    (["auth", "login", "--help"], {"login"}),
]


def _run_help(argv):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("argv, must_contain", HELP_CASES)
def test_help_block_contains_required_tokens(argv, must_contain):
    rc, out, err = _run_help(argv)
    assert rc == 0, f"--help for {argv} exited {rc}: {err}"
    text = out + err
    missing = [tok for tok in must_contain if tok not in text]
    assert not missing, f"{argv} --help missing tokens {missing}\n--- output ---\n{text}"


def test_priority_inversion_documented_where_priority_accepted():
    """PRD §8.8 — every command that accepts --priority documents the inversion."""
    for argv in (["task", "ls", "--help"], ["task", "add", "--help"], ["task", "pri", "--help"]):
        _, out, _ = _run_help(argv)
        # Look for either the flag line or the explainer.
        text = out.lower()
        assert "ui" in text and "1" in text, f"{argv} should explain UI priority semantics"


def test_due_examples_documented_where_due_accepted():
    """PRD §8.8 — commands accepting due strings show NL examples."""
    for argv in (["task", "add", "--help"], ["task", "postpone", "--help"]):
        _, out, _ = _run_help(argv)
        text = out.lower()
        assert "tomorrow" in text or "today" in text, f"{argv} should document due-string examples"


def test_exit_codes_documented_at_top_level():
    _, out, _ = _run_help(["--help"])
    assert "exit codes" in out.lower()
