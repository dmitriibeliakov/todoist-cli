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
    # Path-encoded hierarchy, e.g. "Work/Pigment/Hiring". Top-level projects
    # render their name unchanged. Literal '/' in a project name is escaped
    # to '\/' so the separator is unambiguous (PRD §5.1).
    path: str


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
    scope_project_id: str | None = None,
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
    scope_ids = (
        _scope_subtree_ids(list(projects), scope_project_id)
        if scope_project_id
        else None
    )
    if scope_project_id and not scope_ids:
        raise NotFoundError(f"scope project {scope_project_id} not found")

    # Resolve against scope-only projects so leaf-name collisions across
    # scope boundary don't leak via 'ambiguous' UsageError.
    visible = _scoped_projects(list(projects), scope_ids)
    project_id = filters.resolve_project(project, visible) if project else None
    raw = client.list_tasks(project_id=project_id)
    if scope_ids is not None:
        raw = [t for t in raw if str(t.project_id) in scope_ids]

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
    client: TodoistClientProtocol, task_id: str, *, scope_project_id: str | None = None
) -> tuple[TaskDetail, dict[str, Any]]:
    """Fetch a task and its comments. Returns ``(detail, raw_payload)``."""
    if not task_id:
        raise UsageError("task id is required")
    projects = client.list_projects()
    scope_ids = _scope_subtree_ids(list(projects), scope_project_id) if scope_project_id else None
    if scope_project_id and not scope_ids:
        raise NotFoundError(f"scope project {scope_project_id} not found")
    task = client.get_task(task_id)
    if task is None:
        raise NotFoundError(f"task {task_id} not found")
    _require_in_scope(str(task.project_id), scope_ids, what="task", ident=task_id)
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
    scope_project_id: str | None = None,
) -> tuple[TaskRow, Any]:
    """Create a task. Default project: config's ``default_project`` else Inbox.

    Under a scope-lock the default falls back to the scope root and
    ``--project`` / ``--parent`` must resolve to something inside scope.
    """
    if not content or not content.strip():
        raise UsageError("task content is required")
    if priority_ui is not None and priority_ui not in (1, 2, 3, 4):
        raise UsageError("--priority must be 1-4")

    projects = client.list_projects()
    plookup = {str(p.id): p.name for p in projects}
    scope_ids = _scope_subtree_ids(list(projects), scope_project_id) if scope_project_id else None
    if scope_project_id and not scope_ids:
        raise NotFoundError(f"scope project {scope_project_id} not found")

    project_id: str | None = None
    if parent_id is not None:
        # Sub-tasks inherit project from parent. Validate parent in scope.
        parent_task = client.get_task(parent_id)
        if parent_task is None:
            raise NotFoundError(f"task {parent_id} not found")
        _require_in_scope(str(parent_task.project_id), scope_ids, what="task", ident=parent_id)
    else:
        # ``--project`` only matters when no --parent. Resolve against
        # scope-visible projects so cross-boundary name collisions don't
        # leak via 'ambiguous' UsageError.
        visible = _scoped_projects(list(projects), scope_ids)
        if project:
            project_id = filters.resolve_project(project, visible)
        elif default_project_name:
            try:
                project_id = filters.resolve_project(default_project_name, visible)
            except NotFoundError:
                project_id = None
        if project_id is None:
            if scope_ids is not None:
                # Default to the scope root rather than Inbox.
                project_id = scope_project_id
            else:
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


def _verify_task_in_scope(
    client: TodoistClientProtocol, task_id: str, scope_project_id: str | None
) -> None:
    """If a scope is set, GET the task and confirm its project is in scope.

    Out-of-scope ids surface as NotFoundError, indistinguishable from a
    truly-non-existent task (PRD §13).
    """
    if scope_project_id is None:
        return
    projects = client.list_projects()
    scope_ids = _scope_subtree_ids(list(projects), scope_project_id)
    if not scope_ids:
        raise NotFoundError(f"scope project {scope_project_id} not found")
    task = client.get_task(task_id)
    if task is None:
        raise NotFoundError(f"task {task_id} not found")
    _require_in_scope(str(task.project_id), scope_ids, what="task", ident=task_id)


def task_postpone(
    client: TodoistClientProtocol, task_id: str, due: str, *,
    scope_project_id: str | None = None,
) -> tuple[TaskRow, Any]:
    if not due:
        raise UsageError("due value required")
    _verify_task_in_scope(client, task_id, scope_project_id)
    kwargs: dict = {}
    if filters.ISO_DATE_RE.match(due):
        kwargs["due_date"] = _date.fromisoformat(due)
    else:
        kwargs["due_string"] = due
    updated = client.update_task(task_id, **kwargs)
    plookup = _project_lookup(client)
    return _to_taskrow(updated, plookup), updated


def task_pri(
    client: TodoistClientProtocol, task_id: str, priority_ui: int, *,
    scope_project_id: str | None = None,
) -> tuple[TaskRow, Any]:
    _verify_task_in_scope(client, task_id, scope_project_id)
    api_pri = filters.ui_to_api_priority(priority_ui)
    updated = client.update_task(task_id, priority=api_pri)
    plookup = _project_lookup(client)
    return _to_taskrow(updated, plookup), updated


def task_done(
    client: TodoistClientProtocol, task_id: str, *, scope_project_id: str | None = None
) -> str:
    _verify_task_in_scope(client, task_id, scope_project_id)
    client.complete_task(task_id)
    return task_id


def task_rm(
    client: TodoistClientProtocol, task_id: str, *, scope_project_id: str | None = None
) -> str:
    _verify_task_in_scope(client, task_id, scope_project_id)
    client.delete_task(task_id)
    return task_id


def task_comment(
    client: TodoistClientProtocol, task_id: str, content: str, *,
    scope_project_id: str | None = None,
) -> tuple[CommentRow, Any]:
    if content is None or content == "":
        raise UsageError("comment content is required")
    _verify_task_in_scope(client, task_id, scope_project_id)
    new = client.add_comment(task_id=task_id, content=content)
    return _to_commentrow(new), new


# ---------------------------------------------------------------------------
# Scope-lock public commands + helpers (PRD §13)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeInfo:
    project_id: str | None
    path: str | None  # absolute path of the scope root, or None when unset


def scope_resolve(
    client: TodoistClientProtocol, selector: str
) -> tuple[str, str]:
    """Resolve a user-supplied scope selector to ``(project_id, path)``."""
    if not selector or not selector.strip():
        raise UsageError("scope selector is required")
    projects = list(client.list_projects())
    pid = filters.resolve_project(selector.strip(), projects)
    if pid is None:
        raise NotFoundError(f'project "{selector}" not found')
    paths = _project_paths(projects)
    return pid, paths.get(pid, selector.strip())


def scope_show(
    client: TodoistClientProtocol, scope_project_id: str | None
) -> ScopeInfo:
    """Return current scope. Resolves the path so callers can render it."""
    if not scope_project_id:
        return ScopeInfo(project_id=None, path=None)
    projects = list(client.list_projects())
    paths = _project_paths(projects)
    return ScopeInfo(project_id=scope_project_id, path=paths.get(scope_project_id))


def _scope_subtree_ids(projects: list[Any], scope_id: str) -> set[str]:
    """Return the set of project ids in ``scope_id``'s subtree (root + descendants).

    If ``scope_id`` is not present in ``projects``, returns an empty set —
    every downstream check will then fail-closed with NotFoundError.
    """
    ids = {str(p.id) for p in projects}
    if scope_id not in ids:
        return set()
    children: dict[str, list[str]] = {pid: [] for pid in ids}
    for p in projects:
        parent = getattr(p, "parent_id", None)
        if parent is not None and str(parent) in children:
            children[str(parent)].append(str(p.id))
    out: set[str] = set()
    stack = [scope_id]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, ()))
    return out


def _scoped_projects(projects: list[Any], scope_ids: set[str] | None) -> list[Any]:
    """Return ``projects`` filtered to ``scope_ids`` (or unchanged if no scope).

    Used before ``filters.resolve_project`` so name-based selectors only see
    in-scope projects. This avoids the ambiguity-error info leak where an
    in-scope project sharing a leaf name with an out-of-scope project would
    surface 'ambiguous (N matches)' — disclosing the existence of the
    out-of-scope namesake (CTO security review #1).
    """
    if scope_ids is None:
        return projects
    return [p for p in projects if str(p.id) in scope_ids]


def _require_in_scope(project_id: str | None, scope_ids: set[str] | None, *, what: str, ident: str) -> None:
    """If a scope is set, fail-closed when ``project_id`` is outside it.

    ``what`` is 'task' or 'project' for the error message; ``ident`` is the
    user-supplied id/name. Out-of-scope is reported as not-found per PRD §13.
    """
    if scope_ids is None:
        return
    if project_id is None or str(project_id) not in scope_ids:
        raise NotFoundError(f"{what} {ident} not found")


def _escape_path_segment(name: str) -> str:
    """Escape '/' in a project name so '/' can be the path separator."""
    return name.replace("\\", "\\\\").replace("/", "\\/")


def _project_paths(projects: list[Any]) -> dict[str, str]:
    """Map project id → 'Parent/Child/Leaf' path. Robust to cycles / orphans."""
    by_id = {str(p.id): p for p in projects}
    paths: dict[str, str] = {}

    def resolve(pid: str, seen: frozenset[str]) -> str:
        if pid in paths:
            return paths[pid]
        p = by_id.get(pid)
        if p is None:
            return ""
        seg = _escape_path_segment(p.name)
        parent_id = getattr(p, "parent_id", None)
        if parent_id is None or str(parent_id) not in by_id or pid in seen:
            paths[pid] = seg
        else:
            prefix = resolve(str(parent_id), seen | {pid})
            paths[pid] = f"{prefix}/{seg}" if prefix else seg
        return paths[pid]

    for p in projects:
        resolve(str(p.id), frozenset())
    return paths


def project_ls(
    client: TodoistClientProtocol, *, scope_project_id: str | None = None
) -> tuple[list[ProjectRow], list[Any]]:
    raw = client.list_projects()
    raw_list = list(raw)
    paths = _project_paths(raw_list)
    if scope_project_id:
        scope_ids = _scope_subtree_ids(raw_list, scope_project_id)
        if not scope_ids:
            raise NotFoundError(f"scope project {scope_project_id} not found")
        raw_list = [p for p in raw_list if str(p.id) in scope_ids]
    rows = [ProjectRow(id=str(p.id), path=paths[str(p.id)]) for p in raw_list]
    rows.sort(key=lambda r: r.path.lower())
    return rows, raw_list


def project_add(
    client: TodoistClientProtocol,
    name: str,
    *,
    color: str | None = None,
    parent: str | None = None,
    scope_project_id: str | None = None,
) -> tuple[ProjectRow, Any]:
    if not name or not name.strip():
        raise UsageError("project name is required")
    if color is not None:
        # Client-side validation per PRD §8.6.2 — must reject before any API
        # call so bad input exits 2, not 1.
        filters.validate_project_color(color)

    parent_id: str | None = None
    if parent is not None or scope_project_id is not None:
        projects = client.list_projects()
        scope_ids = (
            _scope_subtree_ids(list(projects), scope_project_id)
            if scope_project_id
            else None
        )
        if scope_project_id and not scope_ids:
            raise NotFoundError(f"scope project {scope_project_id} not found")
        if parent is not None:
            visible = _scoped_projects(list(projects), scope_ids)
            parent_id = filters.resolve_project(parent, visible)
        else:
            # Under scope, default parent to scope root so the new project
            # can never escape the lock.
            parent_id = scope_project_id

    new = client.add_project(name.strip(), color=color, parent_id=parent_id)
    # Compute the full path of the new project rather than guessing.
    projects_after = list(client.list_projects())
    paths = _project_paths(projects_after)
    new_path = paths.get(str(new.id), _escape_path_segment(new.name))
    return ProjectRow(id=str(new.id), path=new_path), new
