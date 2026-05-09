"""Unit tests: priority inversion, due-bucket math, project resolution."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from todoist_cli import filters
from todoist_cli.errors import NotFoundError, UsageError


def test_priority_inversion_round_trip():
    for ui in (1, 2, 3, 4):
        api = filters.ui_to_api_priority(ui)
        assert filters.api_to_ui_priority(api) == ui
    # PRD §3 explicit mapping.
    assert filters.ui_to_api_priority(1) == 4
    assert filters.ui_to_api_priority(4) == 1


def test_priority_invalid():
    with pytest.raises(UsageError):
        filters.ui_to_api_priority(0)
    with pytest.raises(UsageError):
        filters.ui_to_api_priority(5)


def test_parse_due_date_iso():
    assert filters.parse_due_date("2026-05-09") == date(2026, 5, 9)
    assert filters.parse_due_date("2026-05-09T10:30") == date(2026, 5, 9)
    assert filters.parse_due_date("") is None
    assert filters.parse_due_date("garbage") is None


def test_due_buckets_today():
    today = date(2026, 5, 9)
    assert filters.task_matches_due_buckets(today, ["today"], today=today)
    assert not filters.task_matches_due_buckets(today, ["overdue"], today=today)


def test_due_buckets_overdue():
    today = date(2026, 5, 9)
    yesterday = today - timedelta(days=1)
    assert filters.task_matches_due_buckets(yesterday, ["overdue"], today=today)


def test_due_buckets_thisweek_inclusive_endpoints():
    today = date(2026, 5, 9)
    week_end = today + timedelta(days=7)
    assert filters.task_matches_due_buckets(today, ["thisweek"], today=today)
    assert filters.task_matches_due_buckets(week_end, ["thisweek"], today=today)
    assert not filters.task_matches_due_buckets(week_end + timedelta(days=1), ["thisweek"], today=today)


def test_due_buckets_none():
    today = date(2026, 5, 9)
    assert filters.task_matches_due_buckets(None, ["none"], today=today)
    assert not filters.task_matches_due_buckets(today, ["none"], today=today)


def test_due_buckets_future():
    today = date(2026, 5, 9)
    future = today + timedelta(days=30)
    assert filters.task_matches_due_buckets(future, ["future"], today=today)
    assert not filters.task_matches_due_buckets(today, ["future"], today=today)


def test_due_buckets_all_matches_everything():
    today = date(2026, 5, 9)
    assert filters.task_matches_due_buckets(None, ["all"], today=today)
    assert filters.task_matches_due_buckets(today, ["all"], today=today)
    assert filters.task_matches_due_buckets(today + timedelta(days=365), ["all"], today=today)


def test_due_buckets_combinable():
    today = date(2026, 5, 9)
    yesterday = today - timedelta(days=1)
    buckets = ("overdue", "today", "none")
    assert filters.task_matches_due_buckets(today, buckets, today=today)
    assert filters.task_matches_due_buckets(yesterday, buckets, today=today)
    assert filters.task_matches_due_buckets(None, buckets, today=today)
    assert not filters.task_matches_due_buckets(today + timedelta(days=2), buckets, today=today)


def test_resolve_project_by_id(fake_projects):
    assert filters.resolve_project("p_inbox", fake_projects) == "p_inbox"


def test_resolve_project_by_name_case_insensitive(fake_projects):
    assert filters.resolve_project("inbox", fake_projects) == "p_inbox"
    assert filters.resolve_project("Side project: book", fake_projects) == "p_book"


def test_resolve_project_not_found(fake_projects):
    with pytest.raises(NotFoundError):
        filters.resolve_project("nope", fake_projects)


def test_resolve_project_partial_does_not_match(fake_projects):
    # Per PRD: partial matches do not match.
    with pytest.raises(NotFoundError):
        filters.resolve_project("inb", fake_projects)


def test_resolve_project_ambiguous():
    from tests.conftest import FakeProject

    plist = [FakeProject(id="a", name="X"), FakeProject(id="b", name="x")]
    with pytest.raises(UsageError):
        filters.resolve_project("X", plist)


def test_resolve_project_none():
    assert filters.resolve_project(None, []) is None
    assert filters.resolve_project("", []) is None
