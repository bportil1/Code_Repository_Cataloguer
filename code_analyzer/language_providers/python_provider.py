"""Read-only adapter around the existing Python AST indexer."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from code_analyzer.catalog.indexer import index_python_file

from .contracts import (
    CONTRACT_VERSION, LanguageAnalysis, ProviderCapabilities,
    ProviderDescriptor, StructuralItem,
)


class PythonLanguageProvider:
    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="python.ast", language="python", suffixes=(".py",),
            capabilities=ProviderCapabilities(
                structural=True, symbols=True, references=True,
                diagnostics=True, source_spans=True,
            ),
        )

    def analyze(self, path: Path, root: Path) -> LanguageAnalysis:
        module = index_python_file(path, root)
        items: list[StructuralItem] = []
        for cls in module.classes:
            cls_id = f"class:{cls.qualified_name}"
            items.append(StructuralItem(
                cls_id, "class", cls.name, module.path,
                cls.line_start, cls.line_end,
            ))
            for method in cls.methods:
                items.append(StructuralItem(
                    f"method:{method.qualified_name}", "method", method.name,
                    module.path, method.line_start, method.line_end, cls_id,
                ))
        for fn in module.functions:
            items.append(StructuralItem(
                f"function:{fn.qualified_name}", "function", fn.name,
                module.path, fn.line_start, fn.line_end,
            ))
        diagnostics = (module.parse_error,) if module.parse_error else ()
        return LanguageAnalysis(
            contract_version=CONTRACT_VERSION,
            provider_id=self.descriptor.provider_id,
            language=self.descriptor.language,
            relative_path=module.path,
            items=tuple(items),
            diagnostics=diagnostics,
            provider_artifact=asdict(module),
        )
