"""Thin facade over ``todoist-api-python`` that maps SDK errors to typed
exceptions and flattens paginated iterators.

This module is the only place that talks to the Todoist SDK. The rest of the
code consumes its plain return values so that tests can swap in a fake.

Exception mapping policy: any ``httpx.HTTPStatusError`` from the SDK is
caught at this boundary and re-raised as a typed
:class:`todoist_cli.errors.TodoistCliError` subclass so callers (CLI,
future MCP server) never see raw HTTPX text or stack traces. Network
errors (connection refused, DNS, timeouts) are mapped likewise.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date as _date
from typing import Any, Iterator, Protocol

from .errors import (
    AuthError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    TodoistCliError,
)


class TodoistClientProtocol(Protocol):
    """Surface used by :mod:`todoist_cli.commands`. Tests provide a fake."""

    def list_projects(self) -> list[Any]: ...
    def get_project(self, project_id: str) -> Any: ...
    def add_project(self, name: str, *, color: str | None = None) -> Any: ...
    def list_tasks(self, *, project_id: str | None = None) -> list[Any]: ...
    def get_task(self, task_id: str) -> Any: ...
    def add_task(
        self,
        content: str,
        *,
        project_id: str | None = None,
        parent_id: str | None = None,
        priority: int | None = None,
        due_string: str | None = None,
        due_date: _date | None = None,
    ) -> Any: ...
    def update_task(
        self,
        task_id: str,
        *,
        priority: int | None = None,
        due_string: str | None = None,
        due_date: _date | None = None,
    ) -> Any: ...
    def complete_task(self, task_id: str) -> None: ...
    def delete_task(self, task_id: str) -> None: ...
    def list_comments(self, *, task_id: str) -> list[Any]: ...
    def add_comment(self, *, task_id: str, content: str) -> Any: ...


def _flatten(it) -> list:
    out: list = []
    for page in it:
        out.extend(page)
    return out


def _map_http_status_error(exc, *, task_id: str | None = None) -> TodoistCliError:
    """Translate ``httpx.HTTPStatusError`` to a typed CLI exception.

    PRD §5.6 + §7: single-line, prefixed-``error:`` output. No stack traces,
    no Mozilla doc URLs.
    """
    status = None
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
    if status == 401 or status == 403:
        return AuthError("auth failed; check token")
    if status == 404:
        if task_id is not None:
            return NotFoundError(f"task {task_id} not found")
        return NotFoundError("not found")
    if status == 429:
        return RateLimitError("rate limited; retry later")
    # Todoist returns 400 with error_tag INVALID_ARGUMENT_VALUE when a
    # task_id argument is malformed (non-base32, wrong length, etc.). From
    # the agent's perspective that's still "task not found" — surfacing
    # "Invalid argument value" leaves the agent without an actionable
    # mapping. Treat as 404 when we know the call was task-id-scoped.
    if status == 400 and task_id is not None and response is not None:
        try:
            body = response.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and (
            body.get("error_tag") == "INVALID_ARGUMENT_VALUE"
            and body.get("error_extra", {}).get("argument") in ("task_id", "id")
        ):
            return NotFoundError(f"task {task_id} not found")
    # Other 4xx / 5xx: surface the API's own short reason if we can pull
    # it without leaking the verbose httpx message (which includes
    # Mozilla docs URLs).
    reason = ""
    if response is not None:
        try:
            body = response.json()
            if isinstance(body, dict):
                reason = body.get("error") or body.get("message") or ""
        except Exception:
            reason = ""
    if not reason and status is not None:
        reason = f"HTTP {status}"
    return TodoistCliError(reason or "request failed")


def _map_network_error(exc) -> NetworkError:
    msg = str(exc) or type(exc).__name__
    return NetworkError(f"network: {msg}")


@contextmanager
def _translate(*, task_id: str | None = None) -> Iterator[None]:
    """Catch SDK exceptions and re-raise as typed CLI exceptions."""
    import httpx

    try:
        yield
    except httpx.HTTPStatusError as exc:
        raise _map_http_status_error(exc, task_id=task_id) from None
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as exc:
        raise _map_network_error(exc) from None
    except httpx.HTTPError as exc:
        # Catch-all for any remaining httpx error (TransportError etc.).
        raise _map_network_error(exc) from None


class TodoistClient:
    """Wraps ``todoist_api_python.api.TodoistAPI``.

    Every public method funnels SDK calls through :func:`_translate` so the
    rest of the codebase only ever sees typed exceptions.
    """

    def __init__(self, token: str) -> None:
        # Imported lazily so tests that never touch the network don't pay the
        # SDK import cost (and so we never embed the token in import-time
        # state that something else could log).
        from todoist_api_python.api import TodoistAPI

        self._api = TodoistAPI(token)

    # ----- projects ------------------------------------------------------

    def list_projects(self) -> list:
        with _translate():
            return _flatten(self._api.get_projects())

    def get_project(self, project_id: str):
        with _translate():
            return self._api.get_project(project_id)

    def add_project(self, name: str, *, color: str | None = None):
        with _translate():
            if color is not None:
                return self._api.add_project(name, color=color)
            return self._api.add_project(name)

    # ----- tasks ---------------------------------------------------------

    def list_tasks(self, *, project_id: str | None = None) -> list:
        with _translate():
            return _flatten(self._api.get_tasks(project_id=project_id))

    def get_task(self, task_id: str):
        with _translate(task_id=task_id):
            return self._api.get_task(task_id)

    def add_task(
        self,
        content: str,
        *,
        project_id: str | None = None,
        parent_id: str | None = None,
        priority: int | None = None,
        due_string: str | None = None,
        due_date: _date | None = None,
    ):
        kwargs: dict = {}
        if project_id is not None:
            kwargs["project_id"] = project_id
        if parent_id is not None:
            kwargs["parent_id"] = parent_id
        if priority is not None:
            kwargs["priority"] = priority
        if due_string is not None:
            kwargs["due_string"] = due_string
        if due_date is not None:
            kwargs["due_date"] = due_date
        with _translate(task_id=parent_id):
            return self._api.add_task(content, **kwargs)

    def update_task(
        self,
        task_id: str,
        *,
        priority: int | None = None,
        due_string: str | None = None,
        due_date: _date | None = None,
    ):
        kwargs: dict = {}
        if priority is not None:
            kwargs["priority"] = priority
        if due_string is not None:
            kwargs["due_string"] = due_string
        if due_date is not None:
            kwargs["due_date"] = due_date
        with _translate(task_id=task_id):
            return self._api.update_task(task_id, **kwargs)

    def complete_task(self, task_id: str) -> None:
        with _translate(task_id=task_id):
            # ``task done`` is silently idempotent: closing an already-closed
            # task hits the same endpoint and Todoist returns 2xx. The PRD
            # doesn't mandate detection, and a pre-check would double the API
            # cost of every invocation.
            self._api.complete_task(task_id)

    def delete_task(self, task_id: str) -> None:
        with _translate(task_id=task_id):
            self._api.delete_task(task_id)

    # ----- comments ------------------------------------------------------

    def list_comments(self, *, task_id: str) -> list:
        with _translate(task_id=task_id):
            return _flatten(self._api.get_comments(task_id=task_id))

    def add_comment(self, *, task_id: str, content: str):
        with _translate(task_id=task_id):
            return self._api.add_comment(content, task_id=task_id)
