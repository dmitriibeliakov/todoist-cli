"""Compact line / JSON renderers — the §5 output contract.

CLI-only; **must not** be imported from :mod:`todoist_cli.commands`.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime
from typing import Any

from .commands import CommentRow, ProjectRow, TaskDetail, TaskRow

_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Collapse whitespace runs to a single space and trim. PRD §5.1."""
    if not text:
        return ""
    return _WS_RE.sub(" ", text).strip()


def _esc_comment(text: str) -> str:
    """Escape newlines/tabs in comment bodies. PRD §5.1 / §5.2."""
    if not text:
        return ""
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def render_task_row(row: TaskRow) -> str:
    """One line, 6 tab-separated columns. PRD §5.1."""
    due = row.due if row.due else "-"
    p = f"p{row.priority_ui}"
    project = _norm(row.project_name) or "-"
    parent = row.parent_id if row.parent_id else "-"
    content = _norm(row.content)
    return "\t".join([row.id, due, p, project, parent, content])


def render_task_rows(rows: list[TaskRow]) -> str:
    return "\n".join(render_task_row(r) for r in rows)


def render_project_row(p: ProjectRow) -> str:
    # _norm strips embedded tabs/newlines from the (already-escaped) path.
    # The '/' separator is preserved; literal '/' inside names is escaped
    # upstream as '\/' (see commands._escape_path_segment).
    return f"{p.id}\t{_norm(p.path)}"


def render_project_rows(rows: list[ProjectRow]) -> str:
    return "\n".join(render_project_row(r) for r in rows)


def render_comment_row(c: CommentRow) -> str:
    return f"{c.id}\t{c.posted_at}\t{_esc_comment(c.content)}"


def render_task_detail(detail: TaskDetail) -> str:
    """PRD §5.2 — header block, optional ``--`` separator, comments."""
    t = detail.task
    project_val = f"{t.project_id}\t{_norm(t.project_name)}"
    parent = t.parent_id if t.parent_id else "-"
    due = t.due if t.due else "-"
    lines = [
        f"id\t{t.id}",
        f"content\t{_norm(t.content)}",
        f"project\t{project_val}",
        f"parent\t{parent}",
        f"due\t{due}",
        f"priority\tp{t.priority_ui}",
        f"url\t{detail.url}",
        f"created\t{detail.created or '-'}",
        f"comments\t{len(detail.comments)}",
    ]
    if detail.comments:
        lines.append("--")
        lines.extend(render_comment_row(c) for c in detail.comments)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON passthrough — raw API objects.
# ---------------------------------------------------------------------------


def _json_default(o: Any) -> Any:
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    # Fallback — anything else stringifies (e.g. enums).
    return str(o)


def render_json(obj: Any) -> str:
    """PRD §5.3 — raw, unmodified, unstable. Newline at EOF added by caller."""
    return json.dumps(obj, default=_json_default, ensure_ascii=False)
