from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .gitignore import GitIgnoreMatcher
from .models import TreeEntry


DEFAULT_EXCLUDES = {
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
}


@dataclass(slots=True)
class ProjectScan:
    root: Path
    tree: TreeEntry
    all_files: list[Path]
    python_files: list[Path]
    directory_count: int
    gitignore_path: Path | None = None


def _load_gitignore(root: Path) -> tuple[GitIgnoreMatcher | None, Path | None]:
    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        return None, None

    lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return GitIgnoreMatcher.from_lines(lines), gitignore_path


def scan_project(
    root: Path,
    extra_excludes: set[str] | None = None,
    *,
    use_gitignore: bool = True,
) -> ProjectScan:
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {root}")

    excludes = DEFAULT_EXCLUDES | (extra_excludes or set())
    gitignore_spec, gitignore_path = _load_gitignore(root) if use_gitignore else (None, None)
    all_files: list[Path] = []
    python_files: list[Path] = []
    directory_count = 0

    def is_excluded(item: Path) -> bool:
        if item.name in excludes:
            return True
        if gitignore_spec is None:
            return False

        relative = item.relative_to(root).as_posix()
        return gitignore_spec.matches(relative, is_directory=item.is_dir())

    def build_tree(directory: Path) -> TreeEntry:
        nonlocal directory_count
        directory_count += 1
        children: list[TreeEntry] = []

        for item in sorted(directory.iterdir(), key=lambda value: (value.is_file(), value.name.lower())):
            if is_excluded(item):
                continue
            relative = item.relative_to(root).as_posix()
            if item.is_dir():
                children.append(build_tree(item))
            elif item.is_file():
                all_files.append(item)
                if item.suffix == ".py":
                    python_files.append(item)
                children.append(TreeEntry(name=item.name, path=relative, entry_type="file"))

        return TreeEntry(
            name=directory.name if directory != root else root.name,
            path="" if directory == root else directory.relative_to(root).as_posix(),
            entry_type="directory",
            children=children,
        )

    tree = build_tree(root)
    return ProjectScan(
        root=root,
        tree=tree,
        all_files=all_files,
        python_files=python_files,
        directory_count=directory_count,
        gitignore_path=gitignore_path,
    )
