from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EXCLUDES = {
    ".git",
    ".codebase_catalog",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "site-packages",
}


@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    negated: bool = False
    directory_only: bool = False
    anchored: bool = False


def read_gitignore(root: Path) -> list[IgnoreRule]:
    path = root / ".gitignore"
    if not path.exists():
        return []

    rules: list[IgnoreRule] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        negated = line.startswith("!")
        if negated:
            line = line[1:]

        directory_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = line.startswith("/")
        line = line.lstrip("/")

        if line:
            rules.append(
                IgnoreRule(
                    pattern=line,
                    negated=negated,
                    directory_only=directory_only,
                    anchored=anchored,
                )
            )
    return rules


def _rule_matches(rule: IgnoreRule, relative: str, is_dir: bool) -> bool:
    if rule.directory_only and not is_dir:
        return False

    relative = relative.replace("\\", "/")
    parts = relative.split("/")

    if rule.anchored:
        return fnmatch.fnmatch(relative, rule.pattern)

    if "/" in rule.pattern:
        return fnmatch.fnmatch(relative, rule.pattern) or fnmatch.fnmatch(
            relative, f"*/{rule.pattern}"
        )

    return any(fnmatch.fnmatch(part, rule.pattern) for part in parts)


def is_ignored(
    path: Path,
    root: Path,
    excludes: set[str],
    rules: list[IgnoreRule],
) -> bool:
    relative = path.relative_to(root).as_posix()

    if any(part in excludes for part in path.relative_to(root).parts):
        return True

    ignored = False
    for rule in rules:
        if _rule_matches(rule, relative, path.is_dir()):
            ignored = not rule.negated
    return ignored


def discover_entries(
    root: Path,
    extra_excludes: set[str] | None = None,
    use_gitignore: bool = True,
) -> tuple[list[Path], list[Path]]:
    excludes = DEFAULT_EXCLUDES | (extra_excludes or set())
    rules = read_gitignore(root) if use_gitignore else []

    directories: list[Path] = []
    files: list[Path] = []

    def walk(directory: Path) -> None:
        for entry in sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
            if is_ignored(entry, root, excludes, rules):
                continue

            if entry.is_dir():
                directories.append(entry)
                walk(entry)
            elif entry.is_file():
                files.append(entry)

    walk(root)
    return directories, files
