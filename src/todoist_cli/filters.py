"""Filter helpers — due-bucket math, project resolution, priority inversion."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

from .errors import NotFoundError, UsageError

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DUE_BUCKETS = ("overdue", "today", "thisweek", "none", "future", "all")
DEFAULT_DUE_BUCKETS = ("overdue", "today", "none")

# Todoist project colour allow-list (developer.todoist.com → Colors).
# Validated client-side per PRD §8.6.2 — invalid values must exit 2 BEFORE
# any API call.
PROJECT_COLORS = (
    "berry_red",
    "red",
    "orange",
    "yellow",
    "olive_green",
    "lime_green",
    "green",
    "mint_green",
    "teal",
    "sky_blue",
    "light_blue",
    "blue",
    "grape",
    "violet",
    "lavender",
    "magenta",
    "salmon",
    "charcoal",
    "grey",
    "taupe",
)


def validate_project_color(color: str) -> None:
    """Raise :class:`UsageError` if ``color`` is not in the allow-list.

    Called from the CLI command layer **before** any API call so that
    bad input fails fast with exit code 2 (PRD §8.6.2).
    """
    if color not in PROJECT_COLORS:
        raise UsageError(
            f"--color must be one of: {', '.join(PROJECT_COLORS)} (got {color!r})"
        )


def ui_to_api_priority(p: int) -> int:
    """Convert UI priority (1=urgent..4=lowest) to API priority. PRD §3."""
    if p not in (1, 2, 3, 4):
        raise UsageError(f"priority must be 1-4 (got {p!r})")
    return 5 - p


def api_to_ui_priority(p: int) -> int:
    """Inverse of :func:`ui_to_api_priority`."""
    return 5 - p


def parse_due_date(due_str: str) -> date | None:
    """Parse the ``date`` field of a Todoist Due into a date.

    Accepts ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM[:SS][...]``. Returns None on
    unrecognised input rather than raising — the caller treats that as 'no
    parseable date' which is still a date filter mismatch.
    """
    if not due_str:
        return None
    head = due_str.split("T", 1)[0]
    if ISO_DATE_RE.match(head):
        try:
            return date.fromisoformat(head)
        except ValueError:
            return None
    return None


def task_matches_due_buckets(
    task_due_date: date | None,
    buckets: Sequence[str],
    *,
    today: date,
) -> bool:
    """Return True if a task with given due date matches any of the buckets.

    ``buckets`` semantics per PRD §6.1.
    """
    if "all" in buckets:
        return True
    week_end = today + timedelta(days=7)
    for b in buckets:
        if b == "none":
            if task_due_date is None:
                return True
        elif b == "today":
            if task_due_date == today:
                return True
        elif b == "overdue":
            if task_due_date is not None and task_due_date < today:
                return True
        elif b == "thisweek":
            if task_due_date is not None and today <= task_due_date <= week_end:
                return True
        elif b == "future":
            if task_due_date is not None and task_due_date > today:
                return True
        else:
            raise UsageError(f"unknown due bucket: {b}")
    return False


def resolve_project(
    selector: str | None,
    projects: Iterable,  # iterable of objects with .id, .name, .parent_id
) -> str | None:
    """Resolve a ``--project`` selector to a project id.

    ``selector`` accepts:
      * an opaque project id (exact match);
      * a case-insensitive **path** like ``Work/Pigment/Hiring`` — disambiguates
        multiple projects that share a leaf name;
      * a case-insensitive **leaf name** like ``Pigment`` — only when unique.

    Returns ``None`` if selector is empty. Raises :class:`NotFoundError` on
    no match, :class:`UsageError` on ambiguous leaf name.
    """
    if selector is None or selector == "":
        return None
    plist = list(projects)
    # Exact-id match first.
    for p in plist:
        if str(p.id) == selector:
            return str(p.id)
    # Build path map (mirror of commands._project_paths but kept local to
    # avoid a circular import — small enough that DRY isn't worth it).
    by_id = {str(p.id): p for p in plist}
    paths: dict[str, str] = {}

    def _path(pid: str, seen: frozenset[str]) -> str:
        if pid in paths:
            return paths[pid]
        p = by_id.get(pid)
        if p is None:
            return ""
        seg = p.name.replace("\\", "\\\\").replace("/", "\\/")
        parent_id = getattr(p, "parent_id", None)
        if parent_id is None or str(parent_id) not in by_id or pid in seen:
            paths[pid] = seg
        else:
            prefix = _path(str(parent_id), seen | {pid})
            paths[pid] = f"{prefix}/{seg}" if prefix else seg
        return paths[pid]

    for p in plist:
        _path(str(p.id), frozenset())

    sel_lower = selector.lower()
    # Path match (preferred).
    path_matches = [pid for pid, path in paths.items() if path.lower() == sel_lower]
    if len(path_matches) == 1:
        return path_matches[0]
    # Leaf-name match.
    name_matches = [p for p in plist if p.name.lower() == sel_lower]
    if len(name_matches) == 1:
        return str(name_matches[0].id)
    if len(name_matches) > 1:
        raise UsageError(
            f'project "{selector}" is ambiguous ({len(name_matches)} matches); '
            f"use the full path (e.g. Parent/Child) or --project <id>"
        )
    raise NotFoundError(f'project "{selector}" not found')


def project_name_by_id(project_id: str, projects: Iterable) -> str:
    """Look up a project name by id, returning ``"-"`` if unknown."""
    for p in projects:
        if str(p.id) == str(project_id):
            return p.name
    return "-"


def today_local() -> date:
    """Today in the host system timezone (PRD §6.1)."""
    return datetime.now().astimezone().date()
