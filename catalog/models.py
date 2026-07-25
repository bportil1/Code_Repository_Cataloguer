from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ImportEntry:
    module: str
    names: list[str] = field(default_factory=list)
    alias: str | None = None
    level: int = 0
    line: int = 0


@dataclass
class FunctionEntry:
    name: str
    qualified_name: str
    signature: str
    line_start: int
    line_end: int
    docstring: str | None
    decorators: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    parent: str | None = None
    kind: str = "function"
    source_code: str = ""


@dataclass
class ClassEntry:
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    docstring: str | None
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    methods: list[FunctionEntry] = field(default_factory=list)
    source_code: str = ""


@dataclass
class ModuleEntry:
    path: str
    module_name: str
    line_count: int
    docstring: str | None
    imports: list[ImportEntry] = field(default_factory=list)
    classes: list[ClassEntry] = field(default_factory=list)
    functions: list[FunctionEntry] = field(default_factory=list)
    parse_error: str | None = None


@dataclass
class CatalogNode:
    id: str
    node_type: str
    name: str
    qualified_name: str | None = None
    path: str | None = None
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DependencyEdge:
    source_id: str
    target_id: str
    relationship_type: str
    source_level: str
    target_level: str
    evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectCatalog:
    project_name: str
    project_root: str
    root_node_id: str
    nodes: dict[str, CatalogNode]
    relationships: list[DependencyEdge]
    modules: list[ModuleEntry]
    summary: dict[str, int]
    internal_dependencies: dict[str, list[str]]
    external_dependencies: dict[str, list[str]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
