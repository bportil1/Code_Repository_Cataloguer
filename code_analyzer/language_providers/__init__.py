"""Opt-in, capability-declared language analysis, independent of legacy catalog."""
from .contracts import (
    CONTRACT_VERSION, LanguageAnalysis, LanguageProvider,
    ProviderCapabilities, ProviderDescriptor, StructuralItem,
)
from .python_provider import PythonLanguageProvider
from .registry import LanguageProviderRegistry, default_registry

__all__ = [
    "CONTRACT_VERSION", "LanguageAnalysis", "LanguageProvider",
    "ProviderCapabilities", "ProviderDescriptor", "StructuralItem",
    "PythonLanguageProvider", "LanguageProviderRegistry", "default_registry",
]
