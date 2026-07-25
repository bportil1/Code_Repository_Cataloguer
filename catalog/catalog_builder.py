from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .indexer import index_python_file
from .models import (
    CatalogNode,
    DependencyEdge,
    ModuleEntry,
    ProjectCatalog,
)
from .scanner import discover_entries


def _node_id(node_type: str, value: str) -> str:
    return f"{node_type}:{value or '.'}"


def _add_child(
    nodes: dict[str, CatalogNode],
    parent_id: str | None,
    child_id: str,
) -> None:
    if parent_id and child_id not in nodes[parent_id].children:
        nodes[parent_id].children.append(child_id)


def _directory_id(path: str) -> str:
    return _node_id("directory", path)


def _file_id(path: str) -> str:
    return _node_id("file", path)


def _module_id(module_name: str) -> str:
    return _node_id("module", module_name)


def _class_id(qualified_name: str) -> str:
    return _node_id("class", qualified_name)


def _function_id(kind: str, qualified_name: str) -> str:
    return _node_id(kind, qualified_name)


def _relative_import_source(module: ModuleEntry, imported: str, level: int) -> str:
    if level <= 0:
        return imported

    parts = module.module_name.split(".")
    if module.path.endswith("/__init__.py") or module.path == "__init__.py":
        package = parts
    else:
        package = parts[:-1]

    remove = max(0, level - 1)
    base = package[: len(package) - remove] if remove else package
    return ".".join([*base, imported] if imported else base)


def _resolve_internal_module(
    module: ModuleEntry,
    imported: str,
    level: int,
    known_modules: set[str],
) -> str | None:
    candidate = _relative_import_source(module, imported, level)

    if candidate in known_modules:
        return candidate

    matching = sorted(
        (
            name
            for name in known_modules
            if candidate and (
                name.startswith(f"{candidate}.")
                or candidate.startswith(f"{name}.")
            )
        ),
        key=len,
        reverse=True,
    )
    return matching[0] if matching else None


def _definition_lookup(
    modules: Iterable[ModuleEntry],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    by_qualified: dict[str, str] = {}
    by_simple: dict[str, str] = {}
    owner_module: dict[str, str] = {}

    for module in modules:
        for cls in module.classes:
            class_id = _class_id(cls.qualified_name)
            by_qualified[cls.qualified_name] = class_id
            by_simple.setdefault(cls.name, class_id)
            owner_module[class_id] = module.module_name

            for method in cls.methods:
                method_id = _function_id("method", method.qualified_name)
                by_qualified[method.qualified_name] = method_id
                by_simple.setdefault(method.name, method_id)
                owner_module[method_id] = module.module_name

        for fn in module.functions:
            function_id = _function_id("function", fn.qualified_name)
            by_qualified[fn.qualified_name] = function_id
            by_simple.setdefault(fn.name, function_id)
            owner_module[function_id] = module.module_name

    return by_qualified, by_simple, owner_module


def _resolve_call_target(
    expression: str,
    source_module: ModuleEntry,
    import_aliases: dict[str, str],
    by_qualified: dict[str, str],
    by_simple: dict[str, str],
) -> str | None:
    if expression in by_qualified:
        return by_qualified[expression]

    local_candidate = f"{source_module.module_name}.{expression}"
    if local_candidate in by_qualified:
        return by_qualified[local_candidate]

    parts = expression.split(".")
    if parts and parts[0] in import_aliases:
        mapped = import_aliases[parts[0]]
        expanded = ".".join([mapped, *parts[1:]])
        if expanded in by_qualified:
            return by_qualified[expanded]

        matching = [
            node_id
            for qualified, node_id in by_qualified.items()
            if qualified.endswith(f".{expanded.split('.')[-1]}")
            and qualified.startswith(mapped)
        ]
        if len(matching) == 1:
            return matching[0]

    simple = parts[-1] if parts else expression
    return by_simple.get(simple)


def build_catalog(
    project_root: Path,
    extra_excludes: set[str] | None = None,
    use_gitignore: bool = True,
) -> ProjectCatalog:
    root = project_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")

    directories, files = discover_entries(
        root,
        extra_excludes=extra_excludes,
        use_gitignore=use_gitignore,
    )
    python_files = [path for path in files if path.suffix == ".py"]
    modules = [index_python_file(path, root) for path in python_files]

    nodes: dict[str, CatalogNode] = {}
    relationships: list[DependencyEdge] = []
    warnings: list[str] = []

    root_id = _node_id("project", root.name)
    nodes[root_id] = CatalogNode(
        id=root_id,
        node_type="project",
        name=root.name,
        qualified_name=root.name,
        path="",
    )

    directory_paths = {path.relative_to(root).as_posix() for path in directories}
    for relative in sorted(directory_paths, key=lambda value: (value.count("/"), value)):
        parent_path = Path(relative).parent.as_posix()
        parent_id = root_id if parent_path == "." else _directory_id(parent_path)
        current_id = _directory_id(relative)
        nodes[current_id] = CatalogNode(
            id=current_id,
            node_type="directory",
            name=Path(relative).name,
            path=relative,
            parent_id=parent_id,
        )
        _add_child(nodes, parent_id, current_id)

    module_by_path = {module.path: module for module in modules}
    module_id_by_name = {
        module.module_name: _module_id(module.module_name) for module in modules
    }

    for path in files:
        relative = path.relative_to(root).as_posix()
        parent_path = Path(relative).parent.as_posix()
        parent_id = root_id if parent_path == "." else _directory_id(parent_path)
        current_id = _file_id(relative)

        metadata = {
            "suffix": path.suffix,
            "size_bytes": path.stat().st_size,
        }
        if relative in module_by_path:
            metadata["module_id"] = module_id_by_name[module_by_path[relative].module_name]

        nodes[current_id] = CatalogNode(
            id=current_id,
            node_type="file",
            name=path.name,
            path=relative,
            parent_id=parent_id,
            metadata=metadata,
        )
        _add_child(nodes, parent_id, current_id)

    for module in modules:
        file_id = _file_id(module.path)
        module_id = module_id_by_name[module.module_name]

        nodes[module_id] = CatalogNode(
            id=module_id,
            node_type="module",
            name=Path(module.path).name,
            qualified_name=module.module_name,
            path=module.path,
            parent_id=file_id,
            metadata={
                "line_count": module.line_count,
                "docstring": module.docstring,
                "parse_error": module.parse_error,
                "imports": [
                    {
                        "module": item.module,
                        "names": item.names,
                        "alias": item.alias,
                        "level": item.level,
                        "line": item.line,
                    }
                    for item in module.imports
                ],
            },
        )
        _add_child(nodes, file_id, module_id)

        if module.parse_error:
            warnings.append(f"{module.path}: {module.parse_error}")

        for cls in module.classes:
            class_id = _class_id(cls.qualified_name)
            nodes[class_id] = CatalogNode(
                id=class_id,
                node_type="class",
                name=cls.name,
                qualified_name=cls.qualified_name,
                path=module.path,
                parent_id=module_id,
                metadata={
                    "line_start": cls.line_start,
                    "line_end": cls.line_end,
                    "docstring": cls.docstring,
                    "bases": cls.bases,
                    "decorators": cls.decorators,
                    "source_code": cls.source_code,
                },
            )
            _add_child(nodes, module_id, class_id)

            for method in cls.methods:
                method_id = _function_id("method", method.qualified_name)
                nodes[method_id] = CatalogNode(
                    id=method_id,
                    node_type="method",
                    name=method.name,
                    qualified_name=method.qualified_name,
                    path=module.path,
                    parent_id=class_id,
                    metadata={
                        "signature": method.signature,
                        "line_start": method.line_start,
                        "line_end": method.line_end,
                        "docstring": method.docstring,
                        "decorators": method.decorators,
                        "mentions": method.mentions,
                        "calls": method.calls,
                        "source_code": method.source_code,
                    },
                )
                _add_child(nodes, class_id, method_id)

        for fn in module.functions:
            function_id = _function_id("function", fn.qualified_name)
            nodes[function_id] = CatalogNode(
                id=function_id,
                node_type="function",
                name=fn.name,
                qualified_name=fn.qualified_name,
                path=module.path,
                parent_id=module_id,
                metadata={
                    "signature": fn.signature,
                    "line_start": fn.line_start,
                    "line_end": fn.line_end,
                    "docstring": fn.docstring,
                    "decorators": fn.decorators,
                    "mentions": fn.mentions,
                    "calls": fn.calls,
                    "source_code": fn.source_code,
                },
            )
            _add_child(nodes, module_id, function_id)

    known_modules = set(module_id_by_name)
    internal_dependencies: dict[str, list[str]] = {}
    external_dependencies: dict[str, list[str]] = {}

    by_qualified, by_simple, _ = _definition_lookup(modules)

    for module in modules:
        source_module_id = module_id_by_name[module.module_name]
        internal: set[str] = set()
        external: set[str] = set()
        aliases: dict[str, str] = {}

        for imported in module.imports:
            resolved = _resolve_internal_module(
                module,
                imported.module,
                imported.level,
                known_modules,
            )
            display_name = _relative_import_source(
                module,
                imported.module,
                imported.level,
            )

            alias_root = imported.alias or (
                imported.module.split(".")[0] if imported.module else ""
            )
            if alias_root:
                aliases[alias_root] = display_name

            for imported_name in imported.names:
                aliases[imported_name] = (
                    f"{display_name}.{imported_name}"
                    if display_name
                    else imported_name
                )

            if resolved:
                target_module_id = module_id_by_name[resolved]
                internal.add(resolved)
                relationships.append(
                    DependencyEdge(
                        source_id=source_module_id,
                        target_id=target_module_id,
                        relationship_type="imports",
                        source_level="module",
                        target_level="module",
                        evidence={
                            "file": module.path,
                            "line": imported.line,
                            "import": display_name,
                        },
                    )
                )
            else:
                package = (imported.module or display_name).split(".")[0]
                if package:
                    external.add(package)
                    external_id = _node_id("external", package)
                    if external_id not in nodes:
                        nodes[external_id] = CatalogNode(
                            id=external_id,
                            node_type="external",
                            name=package,
                            qualified_name=package,
                        )
                    relationships.append(
                        DependencyEdge(
                            source_id=source_module_id,
                            target_id=external_id,
                            relationship_type="imports",
                            source_level="module",
                            target_level="external",
                            evidence={
                                "file": module.path,
                                "line": imported.line,
                                "import": display_name,
                            },
                        )
                    )

        internal_dependencies[module.module_name] = sorted(internal)
        external_dependencies[module.module_name] = sorted(external)

        definitions = [
            *module.functions,
            *(method for cls in module.classes for method in cls.methods),
        ]

        for definition in definitions:
            source_id = _function_id(definition.kind, definition.qualified_name)
            for expression in definition.calls:
                target_id = _resolve_call_target(
                    expression,
                    module,
                    aliases,
                    by_qualified,
                    by_simple,
                )
                if target_id and target_id != source_id:
                    relationships.append(
                        DependencyEdge(
                            source_id=source_id,
                            target_id=target_id,
                            relationship_type="calls",
                            source_level=definition.kind,
                            target_level=nodes[target_id].node_type,
                            evidence={
                                "file": module.path,
                                "line_start": definition.line_start,
                                "expression": expression,
                            },
                        )
                    )

    unique_relationships: dict[tuple[str, str, str, str], DependencyEdge] = {}
    for edge in relationships:
        key = (
            edge.source_id,
            edge.target_id,
            edge.relationship_type,
            str(edge.evidence),
        )
        unique_relationships[key] = edge
    relationships = list(unique_relationships.values())

    summary = {
        "directories": len(directories) + 1,
        "files": len(files),
        "python_files": len(python_files),
        "modules": len(modules),
        "classes": sum(len(module.classes) for module in modules),
        "functions": sum(len(module.functions) for module in modules),
        "methods": sum(
            len(cls.methods)
            for module in modules
            for cls in module.classes
        ),
        "relationships": len(relationships),
        "internal_imports": sum(
            len(value) for value in internal_dependencies.values()
        ),
        "external_imports": sum(
            len(value) for value in external_dependencies.values()
        ),
    }

    return ProjectCatalog(
        project_name=root.name,
        project_root=str(root),
        root_node_id=root_id,
        nodes=nodes,
        relationships=relationships,
        modules=modules,
        summary=summary,
        internal_dependencies=internal_dependencies,
        external_dependencies=external_dependencies,
        warnings=warnings,
    )
