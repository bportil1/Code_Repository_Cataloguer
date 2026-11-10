"""Opt-in registry with Python and ATLAS; Python-only default is unchanged."""
from .registry import default_registry
from .atlas_provider import AtlasLanguageProvider


def atlas_enabled_registry():
    registry = default_registry()
    registry.register(AtlasLanguageProvider())
    return registry
