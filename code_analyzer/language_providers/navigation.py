"""UCA-09: read-only, source-revision-aware navigation projections.

This module intentionally does not expose provider-specific source fragments,
change the legacy Python index, or claim ATLAS semantic verification.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import os
import stat

from .contracts import CONTRACT_VERSION
from .atlas_registry import atlas_enabled_registry

NAVIGATION_SCHEMA = "code-analyzer.provider-navigation@1"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_NAVIGATION_ITEMS = 5000


class SourceChangedError(ValueError):
    """Source changed while its provider analysis was being prepared."""


def _verified_source_digest(path: Path, root: Path) -> str:
    """Read a local source without following symlink components.

    The registry separately checks containment; avoid trusting path strings
    after verification. This is a bounded identity check, not an immutable
    filesystem snapshot against an uncooperative concurrent writer.
    """
    relative = path.relative_to(root)
    if not relative.parts or '..' in relative.parts:
        raise ValueError("Invalid source path")
    flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0)
    nofollow = getattr(os, 'O_NOFOLLOW', None)
    directory = getattr(os, 'O_DIRECTORY', None)
    if nofollow is None or directory is None or os.open not in os.supports_dir_fd:
        raise OSError("Descriptor-safe source verification is unavailable")
    parent_fd = os.open(root, flags | directory | nofollow)
    try:
        for component in relative.parts[:-1]:
            fd = os.open(component, flags | directory | nofollow, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = fd
        fd = os.open(relative.parts[-1], flags | nofollow, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SOURCE_BYTES:
                raise ValueError("Unsupported source type or size")
            chunks = []
            length = 0
            while True:
                block = os.read(fd, min(65536, MAX_SOURCE_BYTES + 1 - length))
                if not block:
                    break
                length += len(block)
                if length > MAX_SOURCE_BYTES:
                    raise ValueError("Source exceeds navigation size limit")
                chunks.append(block)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise SourceChangedError("Source changed during fingerprinting")
            return sha256(b''.join(chunks)).hexdigest()
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def build_navigation_snapshot(source: str | Path, repository_root: str | Path) -> dict:
    """Analyze one explicitly selected source and return navigation-only data.

    This opt-in function never edits source files or publishes an artifact.
    It preserves provider confidence, so ATLAS candidates are not upgraded to
    verified semantic statements.
    """
    root = Path(repository_root).resolve(strict=True)
    relative = Path(source)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise ValueError("Expected repository-relative source path")
    target = root / relative
    registry = atlas_enabled_registry()
    provider = registry.provider_for(relative)
    if provider is None:
        raise ValueError("No registered provider for source extension")
    first = _verified_source_digest(target, root)
    result = registry.analyze(target, root)
    second = _verified_source_digest(target, root)
    if first != second:
        raise SourceChangedError("Source revision changed during analysis")
    if result.contract_version != CONTRACT_VERSION:
        raise ValueError("Incompatible provider result")
    if len(result.items) > MAX_NAVIGATION_ITEMS:
        raise ValueError("Too many structural items to publish")
    nodes = []
    ids = set()
    for item in result.items:
        if item.item_id in ids or not item.item_id:
            raise ValueError("Duplicate or empty structural node id")
        ids.add(item.item_id)
        if (item.relative_path != result.relative_path or
                not isinstance(item.line_start,int) or isinstance(item.line_start,bool) or
                not isinstance(item.line_end,int) or isinstance(item.line_end,bool) or
                item.line_start < 1 or item.line_end < item.line_start):
            raise ValueError("Invalid structural item source span")
        nodes.append({"id":item.item_id,"kind":item.kind,"name":item.name,
                      "relative_path":item.relative_path,"start_line":item.line_start,
                      "end_line":item.line_end,"parent_id":item.parent_id,
                      "confidence":item.confidence})
    for node in nodes:
        if node['parent_id'] is not None and node['parent_id'] not in ids:
            # ATLAS graphs may contain nonhierarchical relationships: do not
            # synthesize parents from graph edges.
            raise ValueError("Unknown hierarchy parent")
    return {
        "schema": NAVIGATION_SCHEMA,
        "provider_contract": CONTRACT_VERSION,
        "provider_id": result.provider_id,
        "language": result.language,
        "capabilities": asdict(provider.descriptor.capabilities),
        "relative_path": result.relative_path,
        "source_sha256": second,
        "source_revision_verified": True,
        "items": nodes,
        "diagnostics": list(result.diagnostics),
        "semantics_verified": provider.descriptor.capabilities.semantic,
        "provenance_note": "Source bytes matched before and after local parsing; no immutable snapshot guarantee",
    }
