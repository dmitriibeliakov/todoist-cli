"""Package-boundary contract: ``commands.*`` must not import the CLI surface.

The future MCP server imports ``todoist_cli.commands`` directly. Any import
of ``cli`` or ``formatting`` from the core would pull in argparse / printing
machinery that has no business in an MCP tool handler.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "todoist_cli"
CORE_MODULES = ["commands.py", "client.py", "models.py", "filters.py", "config.py", "errors.py"]
FORBIDDEN = {"todoist_cli.cli", "todoist_cli.formatting", ".cli", ".formatting"}


def _imports_in(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = ("." * node.level) + (node.module or "")
            found.add(module)
    return found


def test_core_modules_do_not_import_cli_or_formatting():
    for mod in CORE_MODULES:
        path = ROOT / mod
        if not path.exists():
            continue
        imps = _imports_in(path)
        bad = imps & FORBIDDEN
        # Also catch ``from .cli import ...`` style explicitly.
        for imp in imps:
            if imp in ("cli", "formatting") or imp.endswith(".cli") or imp.endswith(".formatting"):
                bad.add(imp)
        assert not bad, f"{mod} imports forbidden CLI-only module(s): {bad}"
