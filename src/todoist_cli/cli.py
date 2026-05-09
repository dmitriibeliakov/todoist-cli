"""Argparse layer — the human/shell surface.

Wires user input to :mod:`todoist_cli.commands` and renders results via
:mod:`todoist_cli.formatting`. Exit codes per PRD §5.7.

This module is the **only** place that may ``print`` or ``sys.exit``. The
v1.1 MCP server does not import this file.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from . import __version__
from .client import TodoistClient
from .commands import (
    project_add,
    project_ls,
    scope_resolve,
    scope_show,
    task_add,
    task_comment,
    task_done,
    task_get,
    task_ls,
    task_postpone,
    task_pri,
    task_rm,
)
from .config import Config, load_config, resolved_config_path, write_scope, write_token
from .errors import TodoistCliError
from .formatting import (
    render_json,
    render_project_row,
    render_project_rows,
    render_task_detail,
    render_task_row,
    render_task_rows,
)

# ---------------------------------------------------------------------------
# Help text snippets — kept small; --help is the syntax SoT (PRD §6.7).
# ---------------------------------------------------------------------------

_PRIORITY_HELP = (
    "UI priority: 1=urgent (highest), 4=lowest. The CLI inverts internally — "
    "the Todoist API uses the opposite numbering."
)
_DUE_HELP = (
    "Natural language ('today', 'tomorrow', 'next monday', 'in 3 days') "
    "or ISO date 'YYYY-MM-DD'."
)
_BUCKETS_HELP = (
    "overdue | today | thisweek | none | future | all. Repeatable. "
    "Default: overdue + today + none."
)

_EXIT_CODES = (
    "Exit codes: 0 ok, 1 generic, 2 usage, 3 auth, 4 not-found, 5 network, 6 rate-limited."
)


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _add_global_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="emit raw Todoist API JSON (UNSTABLE).")
    p.add_argument("--quiet", action="store_true", help="suppress success messages from mutating commands.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todoist",
        description=(
            "Personal Todoist CLI optimised for AI agents. "
            "Default output is tab-separated compact lines (the stable contract); "
            "use --json for raw API passthrough (unstable). " + _EXIT_CODES
        ),
    )
    parser.add_argument("--version", action="version", version=f"todoist {__version__}")
    # --json / --quiet are subcommand-scoped only. Putting them on the root
    # parser is misleading: argparse's subcommand namespace would shadow
    # ns.json/ns.quiet, so `todoist --json task ls` would silently no-op.

    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    # auth
    p_auth = sub.add_parser("auth", help="auth: log in / save token.")
    sub_auth = p_auth.add_subparsers(dest="auth_cmd", required=True, metavar="<subcommand>")
    p_login = sub_auth.add_parser(
        "login",
        help="read a token from stdin (or prompt), validate, and save to ~/.config/todoist-cli/config.toml (mode 0600).",
        description=(
            "Read a Todoist personal API token from stdin (or prompt if a TTY), "
            "validate it via GET /projects, then write it to the config file "
            "(mode 0600). The token is never printed. "
            "Path: $TODOIST_CLI_CONFIG if set, else ~/.config/todoist-cli/config.toml. "
            "On success: prints 'saved <path>' (suppressed by --quiet) or "
            "emits {\"saved\": \"<path>\"} under --json."
        ),
    )
    _add_global_flags(p_login)

    # scope
    p_scope = sub.add_parser(
        "scope",
        help="scope: lock the CLI to one project (and its sub-projects).",
        description=(
            "Lock every CLI read and write to a single project subtree. "
            "Out-of-scope ids are reported as 'not found' (exit 4). "
            "Note: the Todoist API token still has full account access; "
            "this is a CLI-side guardrail, not a hard security boundary. " + _EXIT_CODES
        ),
    )
    sub_scope = p_scope.add_subparsers(dest="scope_cmd", required=True, metavar="<subcommand>")
    p_scope_show = sub_scope.add_parser(
        "show",
        help="print the current scope (id + path), or '-' if unset.",
        description="Print 'id\\tpath' for the current scope, or '-' if no scope is set.",
    )
    _add_global_flags(p_scope_show)
    p_scope_set = sub_scope.add_parser(
        "set",
        help="lock to a project (id, full path, or unique leaf name).",
        description=(
            "Resolve <project> to a project id and persist it to the config file. "
            "After this, every command only sees the chosen project and its descendants."
        ),
    )
    p_scope_set.add_argument("project", help="project id, full path, or leaf name.")
    _add_global_flags(p_scope_set)
    p_scope_clear = sub_scope.add_parser(
        "clear",
        help="remove the scope lock.",
        description="Remove the [scope] section from config, restoring full-account visibility.",
    )
    _add_global_flags(p_scope_clear)

    # task
    p_task = sub.add_parser("task", help="task: list / get / create / mutate.")
    sub_task = p_task.add_subparsers(dest="task_cmd", required=True, metavar="<subcommand>")

    # task ls (alias: ls)
    p_ls = sub_task.add_parser(
        "ls",
        help="list tasks (compact, agent-tailored).",
        description=(
            "List active tasks. Sort: due ASC (no-due last), priority ASC (p1 first), id ASC. "
            "Output: 6 tab-separated columns — id, due, p, project, parent, content. "
            f"{_PRIORITY_HELP} {_EXIT_CODES}"
        ),
    )
    p_ls.add_argument(
        "--project",
        help="project id, full path (e.g. Work/Pigment), or leaf name (case-insensitive).",
    )
    p_ls.add_argument(
        "--due",
        action="append",
        help=_BUCKETS_HELP,
    )
    p_ls.add_argument("--priority", type=int, help=f"filter by UI priority 1-4. {_PRIORITY_HELP}")
    p_ls.add_argument("--limit", type=int, help="truncate output to first N rows after sort.")
    _add_global_flags(p_ls)

    # task get (alias: get)
    p_get = sub_task.add_parser(
        "get",
        help="full single-task view + comments.",
        description=(
            "Fetch one task with its comments in §5.2 format. "
            "comments=0 → header block only. " + _EXIT_CODES
        ),
    )
    p_get.add_argument("id", help="task id.")
    _add_global_flags(p_get)

    # task add (alias: add)
    p_add = sub_task.add_parser(
        "add",
        help="create a task or sub-task.",
        description=(
            "Create a task. Default project: config 'default_project' or Inbox. "
            f"--due: {_DUE_HELP} --priority: {_PRIORITY_HELP} " + _EXIT_CODES
        ),
    )
    p_add.add_argument("content", help="task content.")
    p_add.add_argument("-d", "--due", help=_DUE_HELP)
    p_add.add_argument("-p", "--priority", type=int, help=f"UI priority 1-4. {_PRIORITY_HELP}")
    p_add.add_argument(
        "-P", "--project",
        help="project id, full path (e.g. Work/Pigment), or leaf name (case-insensitive).",
    )
    p_add.add_argument("--parent", help="parent task id (creates a sub-task).")
    _add_global_flags(p_add)

    # task done
    p_done = sub_task.add_parser(
        "done",
        help="complete a task. Recurring tasks roll forward per Todoist.",
        description="Complete a task. Stdout: 'done\\t<id>'. " + _EXIT_CODES,
    )
    p_done.add_argument("id", help="task id.")
    _add_global_flags(p_done)

    # task rm
    p_rm = sub_task.add_parser(
        "rm",
        help="delete a task (no confirmation).",
        description="Delete a task. Stdout: 'deleted\\t<id>'. " + _EXIT_CODES,
    )
    p_rm.add_argument("id", help="task id.")
    _add_global_flags(p_rm)

    # task postpone (alias: pp at task-level and top-level)
    p_pp = sub_task.add_parser(
        "postpone",
        aliases=["pp"],
        help="reschedule a task.",
        description=f"Reschedule. {_DUE_HELP} Echoes new task line. " + _EXIT_CODES,
    )
    p_pp.add_argument("id", help="task id.")
    p_pp.add_argument("due", help=_DUE_HELP)
    _add_global_flags(p_pp)

    # task pri
    p_pri = sub_task.add_parser(
        "pri",
        help="set priority.",
        description=f"Set task priority. {_PRIORITY_HELP} Echoes new task line. " + _EXIT_CODES,
    )
    p_pri.add_argument("id", help="task id.")
    p_pri.add_argument("priority", type=int, help="UI priority 1-4.")
    _add_global_flags(p_pri)

    # task comment
    p_cmt = sub_task.add_parser(
        "comment",
        help="add a comment to a task.",
        description=(
            "Add a comment to a task. Pass '-' for <text> to read body from stdin. "
            "Stdout: '<comment_id>\\t<posted_at>'. " + _EXIT_CODES
        ),
    )
    p_cmt.add_argument("id", help="task id.")
    p_cmt.add_argument("text", help="comment body, or '-' to read from stdin.")
    _add_global_flags(p_cmt)

    # project (alias: proj)
    p_proj = sub.add_parser("project", aliases=["proj"], help="project: list / create.")
    sub_proj = p_proj.add_subparsers(dest="project_cmd", required=True, metavar="<subcommand>")

    p_proj_ls = sub_proj.add_parser(
        "ls",
        help="list projects (compact).",
        description=(
            "List projects. Output: 2 tab-separated columns — id, path. "
            "Path encodes hierarchy with '/' (e.g. 'Work/Pigment/Hiring'); "
            "literal '/' in a project name is escaped as '\\/'. " + _EXIT_CODES
        ),
    )
    _add_global_flags(p_proj_ls)

    p_proj_add = sub_proj.add_parser(
        "add",
        help="create a project.",
        description="Create a project. Stdout: '<id>\\t<name>'. " + _EXIT_CODES,
    )
    p_proj_add.add_argument("name", help="project name.")
    p_proj_add.add_argument("--color", help="Todoist colour name.")
    p_proj_add.add_argument(
        "--parent",
        help=(
            "parent project id, full path, or leaf name. Under a scope "
            "lock, parent must resolve inside scope; if omitted, the new "
            "project is created as a child of the scope root."
        ),
    )
    _add_global_flags(p_proj_add)

    # Top-level shorthand verbs (PRD §6 alias column).
    for alias, target in (
        ("ls", ["task", "ls"]),
        ("get", ["task", "get"]),
        ("add", ["task", "add"]),
        ("done", ["task", "done"]),
        ("rm", ["task", "rm"]),
        ("pp", ["task", "postpone"]),
    ):
        # Implemented in main() by argv rewriting (cleaner than re-parsing).
        pass

    return parser


# ---------------------------------------------------------------------------
# argv rewriting for top-level shorthand verbs
# ---------------------------------------------------------------------------

_SHORTHAND = {
    "ls": ("task", "ls"),
    "get": ("task", "get"),
    "add": ("task", "add"),
    "done": ("task", "done"),
    "rm": ("task", "rm"),
    "pp": ("task", "postpone"),
}


def _rewrite_argv(argv: Sequence[str]) -> list[str]:
    """Expand top-level aliases ('ls' → 'task ls', etc.) without crowding
    argparse's namespace. Aliases only fire if they appear before any
    explicit subcommand grouping.
    """
    argv = list(argv)
    for i, tok in enumerate(argv):
        if tok.startswith("-"):
            continue
        if tok in _SHORTHAND:
            target = list(_SHORTHAND[tok])
            return argv[:i] + target + argv[i + 1 :]
        # First non-flag token decided.
        return argv
    return argv


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print(out: str, *, file=None) -> None:
    if out == "":
        return
    print(out, file=file or sys.stdout)


def _emit_json(obj: Any) -> None:
    sys.stdout.write(render_json(obj))
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Command dispatchers
# ---------------------------------------------------------------------------


def _make_client(cfg: Config) -> TodoistClient:
    return TodoistClient(cfg.token)


def _cmd_auth_login(ns: argparse.Namespace) -> int:
    if sys.stdin.isatty():
        try:
            token = input("token: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("error: no token provided", file=sys.stderr)
            return 2
    else:
        token = sys.stdin.read().strip()
    if not token:
        print("error: no token provided", file=sys.stderr)
        return 2
    # Validate.
    try:
        client = TodoistClient(token)
        client.list_projects()
    except Exception as e:
        # Map any failure to auth-failed without leaking the token.
        msg = _scrub(str(e), token)
        print(f"error: auth failed; check token ({msg})", file=sys.stderr)
        return 3
    write_token(token)
    if ns.json:
        # PRD §5.3 — under --json we emit a JSON acknowledgement instead of
        # the human "saved <path>" line so callers parsing stdout as JSON
        # don't choke. Documented in `auth login --help`.
        _emit_json({"saved": str(resolved_config_path())})
    elif not ns.quiet:
        print(f"saved {resolved_config_path()}")
    return 0


def _scrub(msg: str, token: str) -> str:
    """Defence in depth: never let the token bleed into stdout/stderr."""
    if token and token in msg:
        return msg.replace(token, "<redacted>")
    return msg


def _cmd_task_ls(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    rows, raw = task_ls(
        client,
        project=ns.project,
        due_buckets=ns.due,
        priority_ui=ns.priority,
        limit=ns.limit,
        scope_project_id=cfg.scope_project_id,
    )
    if ns.json:
        _emit_json(raw)
    else:
        if rows:
            _print(render_task_rows(rows))
    return 0


def _cmd_task_get(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    detail, raw = task_get(client, ns.id, scope_project_id=cfg.scope_project_id)
    if ns.json:
        _emit_json(raw)
    else:
        _print(render_task_detail(detail))
    return 0


def _cmd_task_add(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    row, raw = task_add(
        client,
        ns.content,
        due=ns.due,
        priority_ui=ns.priority,
        project=ns.project,
        parent_id=ns.parent,
        default_project_name=cfg.default_project,
        scope_project_id=cfg.scope_project_id,
    )
    if ns.json:
        _emit_json(raw)
    elif not ns.quiet:
        _print(render_task_row(row))
    return 0


def _cmd_task_done(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    task_done(client, ns.id, scope_project_id=cfg.scope_project_id)
    if ns.json:
        _emit_json({"done": ns.id})
    elif not ns.quiet:
        _print(f"done\t{ns.id}")
    return 0


def _cmd_task_rm(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    task_rm(client, ns.id, scope_project_id=cfg.scope_project_id)
    if ns.json:
        _emit_json({"deleted": ns.id})
    elif not ns.quiet:
        _print(f"deleted\t{ns.id}")
    return 0


def _cmd_task_pp(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    row, raw = task_postpone(client, ns.id, ns.due, scope_project_id=cfg.scope_project_id)
    if ns.json:
        _emit_json(raw)
    elif not ns.quiet:
        _print(render_task_row(row))
    return 0


def _cmd_task_pri(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    row, raw = task_pri(client, ns.id, ns.priority, scope_project_id=cfg.scope_project_id)
    if ns.json:
        _emit_json(raw)
    elif not ns.quiet:
        _print(render_task_row(row))
    return 0


def _cmd_task_comment(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    body = ns.text
    if body == "-":
        body = sys.stdin.read()
    crow, raw = task_comment(client, ns.id, body, scope_project_id=cfg.scope_project_id)
    if ns.json:
        _emit_json(raw)
    elif not ns.quiet:
        _print(f"{crow.id}\t{crow.posted_at}")
    return 0


def _cmd_project_ls(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    rows, raw = project_ls(client, scope_project_id=cfg.scope_project_id)
    if ns.json:
        _emit_json(raw)
    else:
        if rows:
            _print(render_project_rows(rows))
    return 0


def _cmd_project_add(ns: argparse.Namespace, cfg: Config) -> int:
    client = _make_client(cfg)
    row, raw = project_add(
        client,
        ns.name,
        color=ns.color,
        parent=ns.parent,
        scope_project_id=cfg.scope_project_id,
    )
    if ns.json:
        _emit_json(raw)
    elif not ns.quiet:
        _print(render_project_row(row))
    return 0


def _cmd_scope_show(ns: argparse.Namespace, cfg: Config) -> int:
    if cfg.scope_project_id is None:
        if ns.json:
            _emit_json({"scope": None, "locked": cfg.scope_locked})
        else:
            _print("-" + ("\tlocked" if cfg.scope_locked else ""))
        return 0
    client = _make_client(cfg)
    info = scope_show(client, cfg.scope_project_id)
    if ns.json:
        _emit_json({
            "project_id": info.project_id,
            "path": info.path,
            "locked": cfg.scope_locked,
        })
    else:
        path = info.path or "?"
        suffix = "\tlocked" if cfg.scope_locked else ""
        _print(f"{info.project_id}\t{path}{suffix}")
    return 0


def _scope_locked_msg() -> str:
    return f"scope is locked; edit {resolved_config_path()} (set [scope].locked = false) to change it"


def _cmd_scope_set(ns: argparse.Namespace, cfg: Config) -> int:
    if cfg.scope_locked:
        print(f"error: {_scope_locked_msg()}", file=sys.stderr)
        return 3
    # Resolve against full account (ignoring any current scope) so that a
    # user can switch scope without first clearing it.
    client = _make_client(cfg)
    pid, path = scope_resolve(client, ns.project)
    write_scope(pid)
    if ns.json:
        _emit_json({"project_id": pid, "path": path})
    elif not ns.quiet:
        _print(f"scope\t{pid}\t{path}")
    return 0


def _cmd_scope_clear(ns: argparse.Namespace, cfg: Config) -> int:
    if cfg.scope_locked:
        print(f"error: {_scope_locked_msg()}", file=sys.stderr)
        return 3
    write_scope(None)
    if ns.json:
        _emit_json({"scope": None})
    elif not ns.quiet:
        _print("scope cleared")
    return 0


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    rewritten = _rewrite_argv(raw_argv)
    parser = build_parser()
    try:
        ns = parser.parse_args(rewritten)
    except SystemExit as e:
        # argparse exits 2 on usage errors and 0 on --help; respect both.
        return int(e.code) if isinstance(e.code, int) else 2

    # Auth login is special — it bootstraps the config.
    if ns.cmd == "auth" and getattr(ns, "auth_cmd", None) == "login":
        try:
            return _cmd_auth_login(ns)
        except TodoistCliError as e:
            print(f"error: {e}", file=sys.stderr)
            return e.exit_code

    # All other commands need a token.
    try:
        cfg = load_config()
    except TodoistCliError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code

    dispatch = {
        ("task", "ls"): _cmd_task_ls,
        ("task", "get"): _cmd_task_get,
        ("task", "add"): _cmd_task_add,
        ("task", "done"): _cmd_task_done,
        ("task", "rm"): _cmd_task_rm,
        ("task", "postpone"): _cmd_task_pp,
        ("task", "pp"): _cmd_task_pp,
        ("task", "pri"): _cmd_task_pri,
        ("task", "comment"): _cmd_task_comment,
        ("project", "ls"): _cmd_project_ls,
        ("project", "add"): _cmd_project_add,
        ("scope", "show"): _cmd_scope_show,
        ("scope", "set"): _cmd_scope_set,
        ("scope", "clear"): _cmd_scope_clear,
    }

    if ns.cmd == "task":
        key = ("task", ns.task_cmd)
    elif ns.cmd in ("project", "proj"):
        key = ("project", ns.project_cmd)
    elif ns.cmd == "scope":
        key = ("scope", ns.scope_cmd)
    else:
        print(f"error: unknown command {ns.cmd!r}", file=sys.stderr)
        return 2

    handler = dispatch.get(key)
    if handler is None:
        print(f"error: unknown command {' '.join(key)!r}", file=sys.stderr)
        return 2

    try:
        return handler(ns, cfg)
    except TodoistCliError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 1
    except Exception as e:
        # Belt-and-braces: client._translate maps every known SDK/httpx error
        # to TodoistCliError. Anything reaching here is a genuine internal bug
        # — surface a single line and a non-zero exit, scrubbing the token.
        msg = _scrub(f"internal: {type(e).__name__}: {e}", cfg.token)
        print(f"error: {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
