"""UCA-08: opt-in ATLAS structural analysis; CPS artifact remains authoritative."""
from __future__ import annotations

from pathlib import Path

from .contracts import (CONTRACT_VERSION, LanguageAnalysis, ProviderCapabilities,
                        ProviderDescriptor, StructuralItem)
from ._atlas_engine.analysis import analyze_file


class AtlasLanguageProvider:
    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="cps.atlas.structural", language="atlas",
            suffixes=(".as", ".atl", ".atlas"),
            capabilities=ProviderCapabilities(
                lexical=True, structural=True, symbols=True, references=True,
                diagnostics=True, source_spans=True,
                semantic=False, similarity=False,
            ),
        )

    def analyze(self, path: Path, root: Path) -> LanguageAnalysis:
        # UCA-07 registry supplies ordinary path containment/symlink checks.
        relative = path.relative_to(root).as_posix()
        result = analyze_file(path)
        artifact = result.to_dict()
        items = []
        for node in result.nodes:
            span = node.span
            start = span["start"]["line"]
            end = span["end"]["line"]
            if end < start:
                raise ValueError("ATLAS parser emitted reversed source span")
            # CPS offsets are decoded code-point positions, not byte offsets.
            items.append(StructuralItem(
                item_id=node.id, kind=node.kind, name=node.name or node.id,
                relative_path=relative, line_start=start, line_end=end,
                confidence="unverified",
            ))
        diagnostics = tuple(
            f"{d['code']}: {d['message']}"
            for d in artifact.get("diagnostics", ())
        )
        return LanguageAnalysis(
            contract_version=CONTRACT_VERSION,
            provider_id=self.descriptor.provider_id,
            language=self.descriptor.language, relative_path=relative,
            items=tuple(items), diagnostics=diagnostics,
            provider_artifact=artifact,
        )
