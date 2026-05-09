"""Todoist MCP server.

Wraps :mod:`todoist_cli.commands` as MCP tools using FastMCP. Stdio transport.
Same auth + config as the CLI: ``TODOIST_TOKEN`` env var or
``~/.config/todoist-cli/config.toml``.

Scope-lock (PRD §13) is enforced server-side: ``scope_project_id`` is loaded
from config once at startup and passed to every command call. It is NOT
exposed as a tool parameter, so an LLM cannot reach outside the configured
scope by setting it on the call.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import commands
from .client import TodoistClient
from .config import Config, load_config

mcp = FastMCP("todoist")

_cfg: Config | None = None


def _config() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


def _client() -> TodoistClient:
    return TodoistClient(_config().token)


def _scope() -> str | None:
    return _config().scope_project_id


def _row(d: Any) -> dict[str, Any]:
    return asdict(d)


@mcp.tool()
def list_tasks(
    project: str | None = None,
    due_buckets: list[str] | None = None,
    priority: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """List active Todoist tasks.

    Args:
        project: Project name or id to filter by.
        due_buckets: Subset of ``today``, ``overdue``, ``upcoming``, ``no_due``.
            Defaults to today + overdue.
        priority: 1 (highest) to 4 (lowest).
        limit: Maximum number of tasks to return.
    """
    rows, _ = commands.task_ls(
        _client(),
        project=project,
        due_buckets=due_buckets,
        priority_ui=priority,
        limit=limit,
        scope_project_id=_scope(),
    )
    return [_row(r) for r in rows]


@mcp.tool()
def get_task(task_id: str) -> dict:
    """Fetch one task with its comments and metadata."""
    detail, _ = commands.task_get(_client(), task_id, scope_project_id=_scope())
    return {
        "task": _row(detail.task),
        "url": detail.url,
        "created": detail.created,
        "comments": [_row(c) for c in detail.comments],
    }


@mcp.tool()
def add_task(
    content: str,
    due: str | None = None,
    priority: int | None = None,
    project: str | None = None,
    parent_id: str | None = None,
) -> dict:
    """Create a new task.

    Args:
        content: Task content (required).
        due: Either ``YYYY-MM-DD`` or a Todoist natural-language string
            (e.g. ``tomorrow at 5pm``).
        priority: 1 (highest) to 4 (lowest). Defaults to 4.
        project: Project name or id. Defaults to the configured default
            project, then the scope root, then Inbox.
        parent_id: Parent task id (creates a sub-task; project is inherited).
    """
    row, _ = commands.task_add(
        _client(),
        content,
        due=due,
        priority_ui=priority,
        project=project,
        parent_id=parent_id,
        default_project_name=_config().default_project,
        scope_project_id=_scope(),
    )
    return _row(row)


@mcp.tool()
def postpone_task(task_id: str, due: str) -> dict:
    """Change a task's due date.

    ``due`` can be ``YYYY-MM-DD`` or a Todoist natural-language string.
    """
    row, _ = commands.task_postpone(_client(), task_id, due, scope_project_id=_scope())
    return _row(row)


@mcp.tool()
def set_task_priority(task_id: str, priority: int) -> dict:
    """Set task priority. 1 (highest) to 4 (lowest)."""
    row, _ = commands.task_pri(_client(), task_id, priority, scope_project_id=_scope())
    return _row(row)


@mcp.tool()
def complete_task(task_id: str) -> dict:
    """Mark a task as done."""
    tid = commands.task_done(_client(), task_id, scope_project_id=_scope())
    return {"task_id": tid, "status": "completed"}


@mcp.tool()
def delete_task(task_id: str) -> dict:
    """Delete a task permanently."""
    tid = commands.task_rm(_client(), task_id, scope_project_id=_scope())
    return {"task_id": tid, "status": "deleted"}


@mcp.tool()
def comment_on_task(task_id: str, content: str) -> dict:
    """Post a comment on a task."""
    row, _ = commands.task_comment(_client(), task_id, content, scope_project_id=_scope())
    return _row(row)


@mcp.tool()
def list_projects() -> list[dict]:
    """List projects with hierarchical paths (e.g. ``Work/Pigment/Hiring``)."""
    rows, _ = commands.project_ls(_client(), scope_project_id=_scope())
    return [_row(r) for r in rows]


@mcp.tool()
def add_project(
    name: str,
    color: str | None = None,
    parent: str | None = None,
) -> dict:
    """Create a new project. Under scope-lock, defaults to the scope root as parent."""
    row, _ = commands.project_add(
        _client(),
        name,
        color=color,
        parent=parent,
        scope_project_id=_scope(),
    )
    return _row(row)


@mcp.tool()
def show_scope() -> dict:
    """Return the current scope-lock setting (read-only)."""
    info = commands.scope_show(_client(), _scope())
    return _row(info)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
