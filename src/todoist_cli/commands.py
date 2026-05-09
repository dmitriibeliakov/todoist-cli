"""Pure command-layer logic.

Every public function takes typed arguments (no ``argparse.Namespace``),
returns plain dataclasses or primitives, and raises typed exceptions from
:mod:`todoist_cli.errors`. The v1.1 MCP server imports this module directly.

DO NOT import :mod:`todoist_cli.cli` or :mod:`todoist_cli.formatting` here —
that boundary is the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Any, Sequence

from . import filters
from .client import TodoistClientProtocol
from .errors import NotFoundError, UsageError


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskRow:
    """A flat, render-ready view of a Todoist task. PRD §5.1."""

    id: str
    due: str  # "" if no due, otherwise ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM``
    priority_ui: int  # 1-4
    project_id: str
    project_name: str
    parent_id: str | None
    content: str


@dataclass(frozen=True)
class ProjectRow:
    id: str
    name: str


@dataclass(frozen=True)
class CommentRow:
    id: str
    posted_at: str  # ISO-8601 UTC
    content: str


@dataclass(frozen=True)
class TaskDetail:
    """Full single-task view for §5.2 output."""

    task: TaskRow
    url: str
    created: str
    comments: list[CommentRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sort + helpers
# ---------------------------------------------------------------------------


def _due_string_from_task(t) -> str:
    """Render a Todoist Task's due as it appears in §5.1 column 2."""
    due = getattr(t, "due", None)
    if due is None or getattr(due, "date", None) is None:
        return ""
    raw = str(due.date)
    # Todoist returns either YYYY-MM-DD or an ISO datetime when a time is set.
    if "T" in raw:
        # Trim seconds + tz to keep column compact (PRD: ``YYYY-MM-DDTHH:MM``).
        head, _, _ = raw.partition("+")
        head = head.split("Z")[0]
        # Take YYYY-MM-DDTHH:MM (length 16).
        return head[:16]
    return raw


def _to_taskrow(t, project_lookup: dict[str, str]) -> TaskRow:
    return TaskRow(
        id=str(t.id),
        due=_due_string_from_task(t),
        priority_ui=filters.api_to_ui_priority(int(t.priority)),
        project_id=str(t.project_id),
        project_name=project_lookup.get(str(t.project_id), "-"),
        parent_id=str(t.parent_id) if getattr(t, "parent_id", None) else None,
        content=t.content or "",
    )


def _to_commentrow(c) -> CommentRow:
    posted = c.posted_at
    if hasattr(posted, "isoformat"):
        # datetime → ISO-8601 UTC.
        s = posted.isoformat()
        # Normalise ``+00:00`` to ``Z`` to match the README example shape.
        if s.endswith("+00:00"):
            s = s[:-6] + "Z"
    else:
        s = str(posted)
    return CommentRow(id=str(c.id), posted_at=s, content=c.content or "")


def _sort_key_due_first(row: TaskRow) -> tuple:
    """``due ASC, priority ASC, id ASC``; no-due last (PRD §6.1)."""
    no_due = row.due == ""
    due_sort = row.due if not no_due else "9999-99-99"
    # priority_ui ASC means p1 (1) sorts before p4 (4).
    try:
        id_int = int(row.id)
    except ValueError:
        id_int = 0
    return (no_due, due_sort, row.priority_ui, id_int)


def _project_lookup(client: TodoistClientProtocol) -> dict[str, str]:
    return {str(p.id): p.name for p in client.list_projects()}


def _find_inbox(projects: Sequence) -> Any | None:
    for p in projects:
        if getattr(p, "is_inbox_project", False):
            return p
    for p in projects:
        if p.name.lower() == "inbox":
            return p
    return None


# ---------------------------------------------------------------------------
# Public command functions
# ---------------------------------------------------------------------------


def task_ls(
    client: TodoistClientProtocol,
    *,
    project: str | None = None,
    due_buckets: Sequence[str] | None = None,
    priority_ui: int | None = None,
    limit: int | None = None,
    today: _date | None = None,
) -> tuple[list[TaskRow], list[Any]]:
    """List tasks. Returns ``(rows, raw_tasks)`` — raw_tasks is for ``--json``.

    PRD §6.1.
    """
    if limit is not None and limit <= 0:
        raise UsageError("--limit must be a positive integer")
    if priority_ui is not None and priority_ui not in (1, 2, 3, 4):
        raise UsageError("--priority must be 1-4")
    buckets = tuple(due_buckets) if due_buckets else filters.DEFAULT_DUE_BUCKETS
    for b in buckets:
        if b not in filters.DUE_BUCKETS:
            raise UsageError(
                f"--due must be one of {', '.join(filters.DUE_BUCKETS)} (got {b!r})"
            )

    today = today if today is not None else filters.today_local()
    projects = client.list_projects()
    plookup = {str(p.id): p.name for p in projects}

    project_id = filters.resolve_project(project, projects) if project else None
    raw = client.list_tasks(project_id=project_id)

    api_pri = filters.ui_to_api_priority(priority_ui) if priority_ui else None
    out_raw: list = []
    rows: list[TaskRow] = []
    for t in raw:
        # Skip completed tasks (defence in depth — get_tasks returns active).
        if getattr(t, "completed_at", None):
            continue
        if api_pri is not None and int(t.priority) != api_pri:
            continue
        d = filters.parse_due_date(_due_string_from_task(t)) if _due_string_from_task(t) else None
        if not filters.task_matches_due_buckets(d, buckets, today=today):
            continue
        rows.append(_to_taskrow(t, plookup))
        out_raw.append(t)

    # Sort + limit.
    paired = sorted(zip(rows, out_raw), key=lambda x: _sort_key_due_first(x[0]))
    if limit is not None:
        paired = paired[:limit]
    sorted_rows = [r for r, _ in paired]
    sorted_raw = [r for _, r in paired]
    return sorted_rows, sorted_raw


def task_get(
    client: TodoistClientProtocol, task_id: str
) -> tuple[TaskDetail, dict[str, Any]]:
    """Fetch a task and its comments. Returns ``(detail, raw_payload)``."""
    if not task_id:
        raise UsageError("task id is required")
    task = client.get_task(task_id)
    if task is None:
        raise NotFoundError(f"task {task_id} not found")
    projects = client.list_projects()
    plookup = {str(p.id): p.name for p in projects}
    row = _to_taskrow(task, plookup)

    comments_raw = client.list_comments(task_id=task_id)
    comments = [_to_commentrow(c) for c in comments_raw]

    url = f"https://todoist.com/showTask?id={task.id}"
    created_raw = getattr(task, "created_at", "") or ""
    if hasattr(created_raw, "isoformat"):
        created = created_raw.isoformat()
        if created.endswith("+00:00"):
            created = created[:-6] + "Z"
    else:
        created = str(created_raw)
    detail = TaskDetail(task=row, url=url, created=created, comments=comments)
    raw = {"task": task, "comments": comments_raw}
    return detail, raw


def task_add(
    client: TodoistClientProtocol,
    content: str,
    *,
    due: str | None = None,
    priority_ui: int | None = None,
    project: str | None = None,
    parent_id: str | None = None,
    default_project_name: str | None = None,
) -> tuple[TaskRow, Any]:
    """Create a task. Default project: config's ``default_project`` else Inbox."""
    if not content or not content.strip():
        raise UsageError("task content is required")
    if priority_ui is not None and priority_ui not in (1, 2, 3, 4):
        raise UsageError("--priority must be 1-4")

    projects = client.list_projects()
    plookup = {str(p.id): p.name for p in projects}

    project_id: str | None = None
    if parent_id is None:
        # ``--project`` only matters when no --parent. Sub-tasks inherit project.
        if project:
            project_id = filters.resolve_project(project, projects)
        elif default_project_name:
            try:
                project_id = filters.resolve_project(default_project_name, projects)
            except NotFoundError:
                project_id = None
        if project_id is None:
            inbox = _find_inbox(projects)
            project_id = str(inbox.id) if inbox else None

    api_pri = filters.ui_to_api_priority(priority_ui) if priority_ui else None

    due_kwargs: dict = {}
    if due:
        if filters.ISO_DATE_RE.match(due):
            due_kwargs["due_date"] = _date.fromisoformat(due)
        else:
            due_kwargs["due_string"] = due

    new = client.add_task(
        content.strip(),
        project_id=project_id,
        parent_id=parent_id,
        priority=api_pri,
        **due_kwargs,
    )
    return _to_taskrow(new, plookup), new


def task_postpone(
    client: TodoistClientProtocol, task_id: str, due: str
) -> tuple[TaskRow, Any]:
    if not due:
        raise UsageError("due value required")
    kwargs: dict = {}
    if filters.ISO_DATE_RE.match(due):
        kwargs["due_date"] = _date.fromisoformat(due)
    else:
        kwargs["due_string"] = due
    updated = client.update_task(task_id, **kwargs)
    plookup = _project_lookup(client)
    return _to_taskrow(updated, plookup), updated


def task_pri(
    client: TodoistClientProtocol, task_id: str, priority_ui: int
) -> tuple[TaskRow, Any]:
    api_pri = filters.ui_to_api_priority(priority_ui)
    updated = client.update_task(task_id, priority=api_pri)
    plookup = _project_lookup(client)
    return _to_taskrow(updated, plookup), updated


def task_done(client: TodoistClientProtocol, task_id: str) -> str:
    client.complete_task(task_id)
    return task_id


def task_rm(client: TodoistClientProtocol, task_id: str) -> str:
    client.delete_task(task_id)
    return task_id


def task_comment(
    client: TodoistClientProtocol, task_id: str, content: str
) -> tuple[CommentRow, Any]:
    if content is None or content == "":
        raise UsageError("comment content is required")
    new = client.add_comment(task_id=task_id, content=content)
    return _to_commentrow(new), new


def project_ls(client: TodoistClientProtocol) -> tuple[list[ProjectRow], list[Any]]:
    raw = client.list_projects()
    rows = [ProjectRow(id=str(p.id), name=p.name) for p in raw]
    return rows, raw


def project_add(
    client: TodoistClientProtocol, name: str, *, color: str | None = None
) -> tuple[ProjectRow, Any]:
    if not name or not name.strip():
        raise UsageError("project name is required")
    if color is not None:
        # Client-side validation per PRD §8.6.2 — must reject before any API
        # call so bad input exits 2, not 1.
        filters.validate_project_color(color)
    new = client.add_project(name.strip(), color=color)
    return ProjectRow(id=str(new.id), name=new.name), new
