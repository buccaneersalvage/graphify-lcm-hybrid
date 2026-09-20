"""Resolve the memory-tree root. Paths must stay inside it."""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def memory_root() -> Path:
    raw = os.environ.get("MEMORY_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return _REPO_ROOT


def under_root(path: Path | str, label: str, root: Path | None = None) -> Path:
    root = root or memory_root()
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_relative_to(root):
        raise SystemExit(f"{label} escapes {root}: {resolved}")
    return resolved
