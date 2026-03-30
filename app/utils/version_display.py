"""Read ``__version__.py`` from disk for UI and /version.

Long-lived WSGI workers keep imported ``__version__`` frozen until reload. Reading the
file each request lets headers match the tree after ``git pull`` without restarting.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict


def _version_py_path() -> Path:
    # app/utils/version_display.py → parents[2] = project root
    return Path(__file__).resolve().parents[2] / "__version__.py"


def read_version_constants() -> Dict[str, Any]:
    """Parse string constants from ``__version__.py`` (best-effort)."""
    path = _version_py_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "__version__": "unknown",
            "__title__": "TabletTracker",
            "__description__": "",
        }
    out: Dict[str, str] = {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {
            "__version__": "unknown",
            "__title__": "TabletTracker",
            "__description__": "",
        }

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.startswith("__"):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out[target.id] = node.value.value

    return {
        "__version__": out.get("__version__", "unknown"),
        "__title__": out.get("__title__", "TabletTracker"),
        "__description__": out.get("__description__", ""),
    }
