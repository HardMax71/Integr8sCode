#!/usr/bin/env python3
"""Detect orphan modules in the app package using grimp.

An orphan module is one that no other module within the package imports.
Entry points are whitelisted since they are invoked directly by gunicorn
or worker runner scripts, not imported by sibling modules.

Usage:
    uv run python scripts/check_orphan_modules.py
"""
import sys
from pathlib import Path

import grimp

ENTRY_POINTS: frozenset[str] = frozenset({
    "app.main",
})


def _is_empty_init(module: str) -> bool:
    """Return True if module is a package __init__.py with no meaningful code."""
    init_path = Path(module.replace(".", "/")) / "__init__.py"
    if not init_path.is_file():
        return False
    source = init_path.read_text()
    meaningful = [
        line
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return len(meaningful) == 0


def main() -> int:
    graph = grimp.build_graph("app")

    orphans: list[str] = []
    for module in sorted(graph.modules):
        if module in ENTRY_POINTS:
            continue
        if _is_empty_init(module):
            continue
        if not graph.find_modules_that_directly_import(module):
            orphans.append(module)

    if orphans:
        print(f"Found {len(orphans)} orphan module(s) — never imported by any other module in app/:")
        for m in orphans:
            print(f"  {m}")
        return 1

    print("No orphan modules found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
