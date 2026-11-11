"""Explicit local provider registry with no dynamic discovery or network access."""
from __future__ import annotations

from pathlib import Path

from .contracts import LanguageAnalysis, LanguageProvider, validate_descriptor, CONTRACT_VERSION


class LanguageProviderRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, LanguageProvider] = {}
        self._by_suffix: dict[str, str] = {}

    def register(self, provider: LanguageProvider) -> None:
        descriptor = provider.descriptor
        validate_descriptor(descriptor)
        if descriptor.provider_id in self._by_id:
            raise ValueError(f"Provider already registered: {descriptor.provider_id}")
        for suffix in descriptor.suffixes:
            if suffix in self._by_suffix:
                raise ValueError(f"Suffix already registered: {suffix}")
        self._by_id[descriptor.provider_id] = provider
        for suffix in descriptor.suffixes:
            self._by_suffix[suffix] = descriptor.provider_id

    def descriptors(self) -> tuple:
        return tuple(p.descriptor for p in self._by_id.values())

    def provider_for(self, file_path: str | Path) -> LanguageProvider | None:
        suffix = Path(file_path).suffix.lower()
        owner = self._by_suffix.get(suffix)
        return self._by_id.get(owner) if owner is not None else None

    def analyze(self, path: str | Path, root: str | Path) -> LanguageAnalysis:
        """Explicit opt-in analysis; no modifications to legacy catalog generation."""
        root_path = Path(root).resolve(strict=True)
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root_path / candidate
        # Reject symlinked components, not only a final symlink. A verified
        # source-navigation endpoint remains necessary for hostile live trees.
        try:
            relative = candidate.relative_to(root_path)
        except ValueError as exc:
            raise ValueError("Source outside repository") from exc
        if not relative.parts or ".." in relative.parts:
            raise ValueError("Invalid repository-relative source")
        walk = root_path
        for part in relative.parts:
            walk = walk / part
            if walk.is_symlink():
                raise ValueError("Symlinked source paths are unsupported")
        if not walk.is_file():
            raise ValueError("Source file does not exist")
        provider = self.provider_for(walk)
        if provider is None:
            raise ValueError("No provider registered for source extension")
        result = provider.analyze(walk, root_path)
        if (result.contract_version != CONTRACT_VERSION
                or result.provider_id != provider.descriptor.provider_id
                or result.language != provider.descriptor.language
                or result.relative_path != relative.as_posix()):
            raise ValueError("Provider returned an incompatible result")
        return result


def default_registry() -> LanguageProviderRegistry:
    from .python_provider import PythonLanguageProvider

    registry = LanguageProviderRegistry()
    registry.register(PythonLanguageProvider())
    return registry
