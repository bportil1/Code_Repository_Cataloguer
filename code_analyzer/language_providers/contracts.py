"""UCA-07: offline language-provider contracts; no shared AST semantics."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

CONTRACT_VERSION = "code-analyzer.language-analysis@1"


@dataclass(frozen=True)
class ProviderCapabilities:
    """A provider declares precisely which operations are implemented."""
    lexical: bool = False
    structural: bool = False
    symbols: bool = False
    references: bool = False
    diagnostics: bool = False
    semantic: bool = False
    similarity: bool = False
    source_spans: bool = False


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    language: str
    suffixes: tuple[str, ...]
    capabilities: ProviderCapabilities
    contract_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class StructuralItem:
    """Minimal source-linked item; language semantics live in the owner artifact."""
    item_id: str
    kind: str
    name: str
    relative_path: str
    line_start: int
    line_end: int
    parent_id: str | None = None
    confidence: str = "structural"


@dataclass(frozen=True)
class LanguageAnalysis:
    contract_version: str
    provider_id: str
    language: str
    relative_path: str
    items: tuple[StructuralItem, ...] = ()
    diagnostics: tuple[str, ...] = ()
    # The original provider-specific artifact remains authoritative.
    provider_artifact: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class LanguageProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def analyze(self, path: Path, root: Path) -> LanguageAnalysis: ...


def validate_descriptor(descriptor: ProviderDescriptor) -> None:
    if descriptor.contract_version != CONTRACT_VERSION:
        raise ValueError("Unsupported language-provider contract version")
    if not descriptor.provider_id or not descriptor.language:
        raise ValueError("Provider identity and language are required")
    if not descriptor.suffixes or len(set(descriptor.suffixes)) != len(descriptor.suffixes):
        raise ValueError("Nonempty distinct suffixes are required")
    if any(not value.startswith(".") or value.lower() != value or "/" in value or "\\" in value for value in descriptor.suffixes):
        raise ValueError("Provider suffixes must be lowercase file extensions")
    if not isinstance(descriptor.capabilities, ProviderCapabilities):
        raise ValueError("Provider capabilities must be explicit")
