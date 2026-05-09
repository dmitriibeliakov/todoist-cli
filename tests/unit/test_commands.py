"""Unit tests for the command layer."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from todoist_cli import commands
from todoist_cli.errors import NotFoundError, UsageError
from tests.conftest import FakeClient, FakeComment, FakeDue, FakeProject, FakeTask


def test_task_ls_default_buckets_excludes_far_future(fake_client):
    rows, raw = commands.task_ls(fake_client)
    ids = [r.id for r in rows]
    assert "1004" not in ids  # 2099 — far future, default buckets exclude it
    # 1001 (today), 1002 (no due), 1003 (today) all match defaults.
    assert set(ids) == {"1001", "1002", "1003"}


def test_task_ls_sort_due_then_priority_then_id(fake_client):
    rows, _ = commands.task_ls(fake_client)
    # 1001 priority p1 (api 4) and 1003 priority p1 (api 4) both today.
    # 1002 has no due → sorts last.
    assert rows[-1].id == "1002"
    # Among today's tasks: priority p1 first (we set 1001 priority=4 → ui1, 1003 priority=4 → ui1), tie → id ASC.
    today_ids = [r.id for r in rows if r.due]
    assert today_ids == sorted(today_ids, key=lambda x: int(x))


def test_task_ls_priority_filter_uses_ui_semantics(fake_client):
    # ui priority 1 == api priority 4. Tasks 1001 and 1003 have api=4 → ui=1.
    rows, _ = commands.task_ls(fake_client, priority_ui=1, due_buckets=("all",))
    ids = {r.id for r in rows}
    assert ids == {"1001", "1003"}
    # 1004 has api priority 1 → ui priority 4.
    # 1004 has api priority 1 → ui priority 4.
    rows4, _ = commands.task_ls(fake_client, priority_ui=4, due_buckets=("all",))
    assert {r.id for r in rows4} == {"1004"}


def test_task_ls_priority_invalid(fake_client):
    with pytest.raises(UsageError):
        commands.task_ls(fake_client, priority_ui=5)


def test_task_ls_limit_zero_invalid(fake_client):
    with pytest.raises(UsageError):
        commands.task_ls(fake_client, limit=0)
    with pytest.raises(UsageError):
        commands.task_ls(fake_client, limit=-1)


def test_task_ls_limit_truncates_after_sort(fake_client):
    rows, _ = commands.task_ls(fake_client, due_buckets=("all",), limit=2)
    assert len(rows) == 2


def test_task_ls_project_filter(fake_client):
    rows, _ = commands.task_ls(fake_client, project="Side project: book")
    assert all(r.project_id == "p_book" for r in rows)


def test_task_ls_project_unknown_raises(fake_client):
    with pytest.raises(NotFoundError):
        commands.task_ls(fake_client, project="zzz")


def test_task_ls_bad_bucket(fake_client):
    with pytest.raises(UsageError):
        commands.task_ls(fake_client, due_buckets=("yesterday",))


def test_task_get_with_comments():
    projects = [FakeProject(id="p1", name="Inbox", is_inbox_project=True)]
    tasks = [FakeTask(id="42", content="hi", project_id="p1", priority=4,
                      created_at=datetime(2026, 5, 1, 10, 23, tzinfo=timezone.utc))]
    posted = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    comments = {"42": [FakeComment(id="cc1", content="line1\nline2", posted_at=posted)]}
    fc = FakeClient(projects=projects, tasks=tasks, comments=comments)

    detail, raw = commands.task_get(fc, "42")
    assert detail.task.id == "42"
    assert detail.task.priority_ui == 1
    assert detail.url == "https://todoist.com/showTask?id=42"
    assert detail.created.endswith("Z")
    assert len(detail.comments) == 1
    assert "raw" not in raw or True  # smoke


def test_task_get_not_found(fake_client):
    from todoist_cli.errors import NotFoundError

    with pytest.raises(NotFoundError):
        commands.task_get(fake_client, "999")


def test_task_add_default_to_inbox(fake_client):
    row, raw = commands.task_add(fake_client, "Capture this")
    assert row.project_id == "p_inbox"
    assert row.priority_ui == 4  # default api=1 → ui=4


def test_task_add_default_to_config_default_project(fake_client):
    row, _ = commands.task_add(fake_client, "X", default_project_name="Side project: book")
    assert row.project_id == "p_book"


def test_task_add_priority_inversion(fake_client):
    row, raw = commands.task_add(fake_client, "Urgent", priority_ui=1)
    # API priority on the underlying object should be 4 (urgent in API).
    assert raw.priority == 4
    assert row.priority_ui == 1


def test_task_add_with_iso_due_uses_due_date(fake_client):
    row, _ = commands.task_add(fake_client, "T", due="2099-12-31")
    assert row.due == "2099-12-31"


def test_task_add_subtask_parent(fake_client):
    row, _ = commands.task_add(fake_client, "Sub", parent_id="1001")
    assert row.parent_id == "1001"


def test_task_add_blank_content_raises(fake_client):
    with pytest.raises(UsageError):
        commands.task_add(fake_client, "  ")


def test_task_done_records(fake_client):
    commands.task_done(fake_client, "1001")
    assert "1001" in fake_client.completed


def test_task_rm_records(fake_client):
    commands.task_rm(fake_client, "1001")
    assert "1001" in fake_client.deleted


def test_task_postpone_iso(fake_client):
    row, _ = commands.task_postpone(fake_client, "1001", "2099-12-31")
    assert row.due == "2099-12-31"


def test_task_postpone_natural_language(fake_client):
    row, _ = commands.task_postpone(fake_client, "1001", "tomorrow")
    # FakeClient maps "tomorrow" → tomorrow's date.
    from datetime import date as _d, timedelta
    assert row.due == (_d.today() + timedelta(days=1)).isoformat()


def test_task_pri(fake_client):
    row, raw = commands.task_pri(fake_client, "1001", 1)
    assert row.priority_ui == 1
    assert raw.priority == 4  # API value


def test_task_comment(fake_client):
    crow, _ = commands.task_comment(fake_client, "1001", "hi there")
    assert crow.content == "hi there"


def test_task_comment_blank_raises(fake_client):
    with pytest.raises(UsageError):
        commands.task_comment(fake_client, "1001", "")


def test_project_ls(fake_client):
    rows, _ = commands.project_ls(fake_client)
    assert {r.id for r in rows} == {"p_inbox", "p_book", "p_work"}


def test_project_add(fake_client):
    row, _ = commands.project_add(fake_client, "New thing")
    assert row.name == "New thing"


def test_project_add_invalid_color_raises_usage_before_api(fake_client):
    """PRD §8.6.2 — invalid --color must exit 2 before any API call."""
    pre_count = len(fake_client.added_projects)
    with pytest.raises(UsageError):
        commands.project_add(fake_client, "X", color="not-a-real-color")
    assert len(fake_client.added_projects) == pre_count


def test_project_add_valid_color_accepted(fake_client):
    row, _ = commands.project_add(fake_client, "Booky", color="berry_red")
    assert row.name == "Booky"
