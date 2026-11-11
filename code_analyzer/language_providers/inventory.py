"""Local, bounded-page ATLAS file discovery for UI and CLI consumers."""
from __future__ import annotations

import os
from pathlib import Path

ATLAS_SUFFIXES = frozenset({".as", ".atl", ".atlas"})
EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules",
    "build", "dist", ".mypy_cache", ".pytest_cache", ".tox",
})


def atlas_files(root: str | Path, *, query: str = "") -> list[str]:
    """Discover actual ATLAS sources under the currently selected repository.

    Do not follow symlinked directories/files or walk dependency/build folders.
    Paths are returned relative to the active root, never absolute.
    """
    base = Path(root).resolve(strict=True)
    if not base.is_dir():
        raise ValueError("Repository root must be a directory")
    needle = str(query).strip().lower()
    result: list[str] = []
    for current, dirs, files in os.walk(base, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS
                         and not d.startswith(".")
                         and not (Path(current) / d).is_symlink())
        for filename in files:
            if Path(filename).suffix.lower() not in ATLAS_SUFFIXES:
                continue
            entry = Path(current) / filename
            if entry.is_symlink() or not entry.is_file():
                continue
            relative = entry.relative_to(base).as_posix()
            if needle and needle not in relative.lower():
                continue
            result.append(relative)
    return sorted(result, key=str.casefold)
