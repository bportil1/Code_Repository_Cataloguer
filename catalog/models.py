from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ImportEntry:
    module: str
    names: list[str] = field(default_factory=list)
    alias: str | None = None
    level: int = 0
    line: int = 0


@dataclass(slots=True)
class FunctionEntry:
    name: str
    qualified_name: str
    signature: str
    line_start: int
    line_end: int
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    parent: str | None = None
    kind: str = "function"


@dataclass(slots=True)
class ClassEntry:
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    docstring: str | None = None
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    methods: list[FunctionEntry] = field(default_factory=list)


@dataclass(slots=True)
class PythonModule:
    path: str
    module_name: str
    line_count: int
    docstring: str | None = None
    imports: list[ImportEntry] = field(default_factory=list)
    classes: list[ClassEntry] = field(default_factory=list)
    functions: list[FunctionEntry] = field(default_factory=list)


@dataclass(slots=True)
class TreeEntry:
    name: str
    path: str
    entry_type: str
    children: list["TreeEntry"] = field(default_factory=list)


@dataclass(slots=True)
class CatalogSummary:
    directories: int = 0
    files: int = 0
    python_files: int = 0
    classes: int = 0
    functions: int = 0
    methods: int = 0
    internal_imports: int = 0
    external_imports: int = 0


@dataclass(slots=True)
class Catalog:
    project_name: str
    project_root: str
    tree: TreeEntry
    modules: list[PythonModule]
    summary: CatalogSummary
    internal_dependencies: dict[str, list[str]] = field(default_factory=dict)
    external_dependencies: dict[str, list[str]] = field(default_factory=dict)
    mentions_index: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
