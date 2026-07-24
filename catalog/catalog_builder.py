from __future__ import annotations

from collections import defaultdict

from .models import Catalog, CatalogSummary, PythonModule
from .scanner import ProjectScan


def _resolve_import(module: PythonModule, imported: str, level: int) -> str:
    if level == 0:
        return imported

    current_parts = module.module_name.split(".")
    package_parts = current_parts[:-1]
    keep = max(0, len(package_parts) - (level - 1))
    prefix = package_parts[:keep]
    if imported:
        prefix.extend(imported.split("."))
    return ".".join(prefix)


def build_catalog(scan: ProjectScan, modules: list[PythonModule]) -> Catalog:
    module_names = {module.module_name for module in modules}
    package_names = {name.split(".")[0] for name in module_names if name}

    internal: dict[str, list[str]] = {}
    external: dict[str, list[str]] = {}
    internal_count = 0
    external_count = 0

    for module in modules:
        internal_targets: set[str] = set()
        external_targets: set[str] = set()
        for entry in module.imports:
            resolved = _resolve_import(module, entry.module, entry.level)
            root_name = resolved.split(".")[0] if resolved else ""
            matching = {
                candidate
                for candidate in module_names
                if candidate == resolved or candidate.startswith(f"{resolved}.")
            }
            if matching or root_name in package_names:
                internal_targets.add(resolved or root_name)
            elif resolved:
                external_targets.add(root_name)

        internal[module.module_name] = sorted(internal_targets)
        external[module.module_name] = sorted(external_targets)
        internal_count += len(internal_targets)
        external_count += len(external_targets)

    mentions_index: dict[str, list[dict[str, object]]] = defaultdict(list)
    for module in modules:
        entries = [*module.functions]
        for class_entry in module.classes:
            entries.extend(class_entry.methods)
        for entry in entries:
            for mention in entry.mentions:
                mentions_index[mention].append(
                    {
                        "module": module.module_name,
                        "path": module.path,
                        "definition": entry.qualified_name,
                        "line": entry.line_start,
                    }
                )

    summary = CatalogSummary(
        directories=scan.directory_count,
        files=len(scan.all_files),
        python_files=len(modules),
        classes=sum(len(module.classes) for module in modules),
        functions=sum(len(module.functions) for module in modules),
        methods=sum(len(item.methods) for module in modules for item in module.classes),
        internal_imports=internal_count,
        external_imports=external_count,
    )

    return Catalog(
        project_name=scan.root.name,
        project_root=str(scan.root),
        tree=scan.tree,
        modules=modules,
        summary=summary,
        internal_dependencies=internal,
        external_dependencies=external,
        mentions_index=dict(mentions_index),
    )
