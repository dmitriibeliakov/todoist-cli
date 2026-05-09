"""Client-layer error translation: SDK / httpx exceptions → typed CLI errors.

The QA bug was that ``task get <bogus-id>`` leaked a raw httpx traceback;
the fix is to catch ``httpx.HTTPStatusError`` at the client boundary and
re-raise as a typed exception that ``cli.py`` maps to the correct exit
code (PRD §7 + §8.2.6).
"""

from __future__ import annotations

import httpx
import pytest

from todoist_cli import client as client_mod
from todoist_cli.errors import AuthError, NetworkError, NotFoundError, RateLimitError, TodoistCliError


def _make_status_error(status: int, body: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.todoist.com/v1/tasks/x")
    response = httpx.Response(status_code=status, request=request, json=body or {})
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


def test_translate_404_with_task_id_maps_to_taskmsg():
    with pytest.raises(NotFoundError) as exc_info:
        with client_mod._translate(task_id="bogus_id_12345"):
            raise _make_status_error(404)
    assert str(exc_info.value) == "task bogus_id_12345 not found"
    assert exc_info.value.exit_code == 4


def test_translate_404_without_task_id():
    with pytest.raises(NotFoundError):
        with client_mod._translate():
            raise _make_status_error(404)


def test_translate_401_maps_to_auth_error():
    with pytest.raises(AuthError) as exc_info:
        with client_mod._translate():
            raise _make_status_error(401)
    assert exc_info.value.exit_code == 3


def test_translate_403_maps_to_auth_error():
    with pytest.raises(AuthError):
        with client_mod._translate():
            raise _make_status_error(403)


def test_translate_429_maps_to_ratelimit():
    with pytest.raises(RateLimitError) as exc_info:
        with client_mod._translate():
            raise _make_status_error(429)
    assert exc_info.value.exit_code == 6


def test_translate_400_maps_to_generic_clean_message():
    """4xx other than the typed ones must NOT leak Mozilla docs URLs."""
    with pytest.raises(TodoistCliError) as exc_info:
        with client_mod._translate():
            raise _make_status_error(400, {"error": "bad request"})
    msg = str(exc_info.value)
    assert "developer.mozilla.org" not in msg
    assert "Traceback" not in msg


def test_translate_connect_error_maps_to_network():
    request = httpx.Request("GET", "https://api.todoist.com")
    with pytest.raises(NetworkError) as exc_info:
        with client_mod._translate():
            raise httpx.ConnectError("dns failure", request=request)
    assert exc_info.value.exit_code == 5
    assert "network:" in str(exc_info.value)
