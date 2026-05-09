"""Typed exceptions for the CLI core.

The ``cli.py`` argparse layer maps these to exit codes per PRD §5.7.
"""

from __future__ import annotations


class TodoistCliError(Exception):
    """Base class. Maps to exit code 1 unless a subclass overrides."""

    exit_code: int = 1


class UsageError(TodoistCliError):
    exit_code = 2


class AuthError(TodoistCliError):
    exit_code = 3


class NotFoundError(TodoistCliError):
    exit_code = 4


class NetworkError(TodoistCliError):
    exit_code = 5


class RateLimitError(TodoistCliError):
    exit_code = 6
