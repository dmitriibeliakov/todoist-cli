"""Shared pytest fixtures and a fake Todoist client."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# Make sure the src layout is importable when running pytest without install.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from todoist_cli.errors import NotFoundError  # noqa: E402


# ---------------------------------------------------------------------------
# Fake SDK objects (shape-compatible with todoist_api_python.models).
# ---------------------------------------------------------------------------


@dataclass
class FakeDue:
    date: str | None = None  # YYYY-MM-DD or YYYY-MM-DDTHH:MM
    string: str = ""
    lang: str = "en"
    is_recurring: bool = False
    timezone: str | None = None


@dataclass
class FakeProject:
    id: str
    name: str
    is_inbox_project: bool = False


@dataclass
class FakeTask:
    id: str
    content: str
    project_id: str
    priority: int = 1  # API priority (1=lowest..4=urgent)
    parent_id: str | None = None
    due: FakeDue | None = None
    completed_at: Any = None
    created_at: Any = None
    description: str = ""
    section_id: str | None = None
    labels: list = field(default_factory=list)


@dataclass
class FakeComment:
    id: str
    content: str
    posted_at: Any
    task_id: str | None = None
    project_id: str | None = None


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class FakeClient:
    """Implements :class:`todoist_cli.client.TodoistClientProtocol`."""

    def __init__(
        self,
        projects: list[FakeProject] | None = None,
        tasks: list[FakeTask] | None = None,
        comments: dict[str, list[FakeComment]] | None = None,
    ) -> None:
        self.projects = projects or []
        self.tasks = tasks or []
        self.comments = comments or {}
        # Mutation log for assertions.
        self.completed: list[str] = []
        self.deleted: list[str] = []
        self.added_tasks: list[FakeTask] = []
        self.updated: list[tuple[str, dict]] = []
        self.added_comments: list[FakeComment] = []
        self.added_projects: list[FakeProject] = []

    # --- projects ---
    def list_projects(self) -> list[FakeProject]:
        return list(self.projects)

    def get_project(self, project_id: str) -> FakeProject:
        for p in self.projects:
            if p.id == project_id:
                return p
        raise LookupError(f"project {project_id} not found")

    def add_project(self, name: str, *, color: str | None = None) -> FakeProject:
        new = FakeProject(id=f"new-proj-{len(self.added_projects) + 1}", name=name)
        self.projects.append(new)
        self.added_projects.append(new)
        return new

    # --- tasks ---
    def list_tasks(self, *, project_id: str | None = None) -> list[FakeTask]:
        if project_id is None:
            return list(self.tasks)
        return [t for t in self.tasks if t.project_id == project_id]

    def get_task(self, task_id: str) -> FakeTask:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise NotFoundError(f"task {task_id} not found")

    def add_task(
        self,
        content,
        *,
        project_id=None,
        parent_id=None,
        priority=None,
        due_string=None,
        due_date=None,
    ) -> FakeTask:
        due = None
        if due_date is not None:
            due = FakeDue(date=due_date.isoformat())
        elif due_string is not None:
            # Best-effort: map literal "tomorrow"/"today" to dates.
            from datetime import timedelta

            today = date.today()
            mapping = {"today": today, "tomorrow": today + timedelta(days=1)}
            d = mapping.get(due_string)
            if d:
                due = FakeDue(date=d.isoformat(), string=due_string)
            else:
                due = FakeDue(string=due_string)
        new = FakeTask(
            id=f"new-task-{len(self.added_tasks) + 1}",
            content=content,
            project_id=project_id or (self.projects[0].id if self.projects else "p0"),
            priority=int(priority) if priority is not None else 1,
            parent_id=parent_id,
            due=due,
            created_at=datetime.now(tz=timezone.utc),
        )
        self.tasks.append(new)
        self.added_tasks.append(new)
        return new

    def update_task(self, task_id, *, priority=None, due_string=None, due_date=None) -> FakeTask:
        self.updated.append((task_id, {"priority": priority, "due_string": due_string, "due_date": due_date}))
        for t in self.tasks:
            if t.id == task_id:
                if priority is not None:
                    t.priority = int(priority)
                if due_date is not None:
                    t.due = FakeDue(date=due_date.isoformat())
                elif due_string is not None:
                    from datetime import timedelta

                    today = date.today()
                    mapping = {"today": today, "tomorrow": today + timedelta(days=1)}
                    d = mapping.get(due_string)
                    if d:
                        t.due = FakeDue(date=d.isoformat(), string=due_string)
                    else:
                        t.due = FakeDue(string=due_string)
                return t
        raise NotFoundError(f"task {task_id} not found")

    def complete_task(self, task_id):
        if not any(t.id == task_id for t in self.tasks):
            raise NotFoundError(f"task {task_id} not found")
        self.completed.append(task_id)

    def delete_task(self, task_id):
        if not any(t.id == task_id for t in self.tasks):
            raise NotFoundError(f"task {task_id} not found")
        self.tasks = [t for t in self.tasks if t.id != task_id]
        self.deleted.append(task_id)

    # --- comments ---
    def list_comments(self, *, task_id):
        return list(self.comments.get(task_id, []))

    def add_comment(self, *, task_id, content):
        new = FakeComment(
            id=f"new-cmt-{len(self.added_comments) + 1}",
            content=content,
            posted_at=datetime.now(tz=timezone.utc),
            task_id=task_id,
        )
        self.comments.setdefault(task_id, []).append(new)
        self.added_comments.append(new)
        return new


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_projects() -> list[FakeProject]:
    return [
        FakeProject(id="p_inbox", name="Inbox", is_inbox_project=True),
        FakeProject(id="p_book", name="Side project: book"),
        FakeProject(id="p_work", name="Work\tstuff"),  # whitespace test
    ]


@pytest.fixture
def fake_tasks(fake_projects) -> list[FakeTask]:
    today = date.today().isoformat()
    return [
        FakeTask(id="1001", content="Buy milk", project_id="p_inbox", priority=4, due=FakeDue(date=today)),
        FakeTask(id="1002", content="Reply  to\tAnna", project_id="p_inbox", priority=2),  # no due
        FakeTask(id="1003", content="Ship PRD draft", project_id="p_book", priority=4, due=FakeDue(date=today)),
        FakeTask(id="1004", content="Future task", project_id="p_inbox", priority=1, due=FakeDue(date="2099-01-01")),
    ]


@pytest.fixture
def fake_client(fake_projects, fake_tasks) -> FakeClient:
    return FakeClient(projects=fake_projects, tasks=fake_tasks)
