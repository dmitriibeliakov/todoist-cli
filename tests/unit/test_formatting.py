"""Schema-regression tests — these are explicitly required by the PRD.

These tests are the stable agent contract. Output drift here means an
agent parser breaks; fail loudly.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from todoist_cli import formatting
from todoist_cli.commands import CommentRow, ProjectRow, TaskDetail, TaskRow


# ---------------------------------------------------------------------------
# Tab-separated 6-column task line.
# ---------------------------------------------------------------------------


def _task_row(**overrides) -> TaskRow:
    base = dict(
        id="123",
        due="2026-05-09",
        priority_ui=1,
        project_id="p1",
        project_name="Inbox",
        parent_id=None,
        content="Buy milk",
    )
    base.update(overrides)
    return TaskRow(**base)


def test_task_row_six_tabs():
    line = formatting.render_task_row(_task_row())
    assert line.count("\t") == 5  # 6 columns = 5 separators
    parts = line.split("\t")
    assert parts == ["123", "2026-05-09", "p1", "Inbox", "-", "Buy milk"]


def test_task_row_no_due_renders_dash():
    line = formatting.render_task_row(_task_row(due=""))
    assert line.split("\t")[1] == "-"


def test_task_row_priority_token():
    for ui in (1, 2, 3, 4):
        line = formatting.render_task_row(_task_row(priority_ui=ui))
        assert line.split("\t")[2] == f"p{ui}"


def test_task_row_parent_dash_when_top_level():
    assert formatting.render_task_row(_task_row()).split("\t")[4] == "-"


def test_task_row_parent_set_for_subtask():
    line = formatting.render_task_row(_task_row(parent_id="9999"))
    assert line.split("\t")[4] == "9999"


def test_task_row_whitespace_normalised_in_content():
    line = formatting.render_task_row(_task_row(content="Hello\t\n  world\n\nthere"))
    assert line.split("\t")[5] == "Hello world there"


def test_task_row_whitespace_normalised_in_project():
    line = formatting.render_task_row(_task_row(project_name="Work\tstuff\n  more"))
    assert line.split("\t")[3] == "Work stuff more"


def test_task_row_no_trailing_whitespace():
    line = formatting.render_task_row(_task_row())
    assert line == line.rstrip()


def test_task_row_no_embedded_newlines_even_with_multiline_content():
    line = formatting.render_task_row(_task_row(content="a\nb\nc"))
    assert "\n" not in line


# ---------------------------------------------------------------------------
# Project rows.
# ---------------------------------------------------------------------------


def test_project_row_two_columns():
    row = ProjectRow(id="6cV", name="Inbox")
    line = formatting.render_project_row(row)
    assert line.count("\t") == 1
    assert line.split("\t") == ["6cV", "Inbox"]


def test_project_row_whitespace_normalised():
    row = ProjectRow(id="x", name="Side\tproject:\nbook")
    line = formatting.render_project_row(row)
    assert line.split("\t")[1] == "Side project: book"


# ---------------------------------------------------------------------------
# Comment rows.
# ---------------------------------------------------------------------------


def test_comment_row_three_columns_and_escapes_newlines():
    c = CommentRow(id="42", posted_at="2026-05-08T12:00:00Z", content="line1\nline2\twith tab")
    line = formatting.render_comment_row(c)
    assert line.count("\t") == 2
    parts = line.split("\t")
    # The content column itself contains escaped \n and \t (literal backslash-n).
    assert parts[0] == "42"
    assert parts[1] == "2026-05-08T12:00:00Z"
    assert "\\n" in parts[2]
    assert "\\t" in parts[2]
    # No real newline must appear anywhere in the line.
    assert "\n" not in line


# ---------------------------------------------------------------------------
# task get §5.2 layout.
# ---------------------------------------------------------------------------


def test_task_detail_no_comments_omits_separator():
    detail = TaskDetail(
        task=_task_row(content="Ship PRD"),
        url="https://todoist.com/showTask?id=123",
        created="2026-05-01T10:23:00Z",
        comments=[],
    )
    out = formatting.render_task_detail(detail)
    lines = out.split("\n")
    assert "--" not in lines
    # First lines in fixed order.
    assert lines[0] == "id\t123"
    assert lines[1] == "content\tShip PRD"
    assert lines[2].startswith("project\t")
    assert lines[3] == "parent\t-"
    assert lines[4] == "due\t2026-05-09"
    assert lines[5] == "priority\tp1"
    assert lines[6].startswith("url\t")
    assert lines[7].startswith("created\t")
    assert lines[8] == "comments\t0"


def test_task_detail_with_comments_includes_separator_and_lines():
    detail = TaskDetail(
        task=_task_row(),
        url="u",
        created="2026-05-01T10:23:00Z",
        comments=[
            CommentRow(id="c1", posted_at="2026-05-08T12:00:00Z", content="x"),
            CommentRow(id="c2", posted_at="2026-05-09T09:00:00Z", content="y"),
        ],
    )
    out = formatting.render_task_detail(detail)
    lines = out.split("\n")
    assert lines.count("--") == 1
    sep = lines.index("--")
    assert lines[sep + 1].startswith("c1\t")
    assert lines[sep + 2].startswith("c2\t")


def test_task_detail_project_row_includes_id_and_name():
    detail = TaskDetail(
        task=_task_row(project_id="p_book", project_name="Side project: book"),
        url="u",
        created="c",
        comments=[],
    )
    out = formatting.render_task_detail(detail)
    proj_line = next(l for l in out.split("\n") if l.startswith("project\t"))
    parts = proj_line.split("\t")
    assert parts == ["project", "p_book", "Side project: book"]


# ---------------------------------------------------------------------------
# JSON passthrough — no pretty-printing.
# ---------------------------------------------------------------------------


def test_render_json_is_compact():
    out = formatting.render_json({"a": 1, "b": [1, 2]})
    # No newlines inside the JSON payload itself (caller adds final \n).
    assert "\n" not in out
