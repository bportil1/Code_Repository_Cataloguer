"""P5-18 read-only Code Analyzer inspection of verified pyPIQUE source evidence.

The PAH host authorizes the repository and the project identity. This module
independently enforces confinement, source fingerprint and preview bounds and
cannot write source files or initiate a refactor.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
from collections.abc import Mapping

_SCHEMA = "pah.source-evidence@1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_EXCERPT_BYTES = 24 * 1024
_MAX_LINES = 80


class EvidenceNavigationError(ValueError):
    """Evidence is invalid, stale, unauthorized, or cannot be inspected."""


def inspect_verified_finding(
    locator: Mapping[str, object], *, repository_root: str | Path, active_project_id: str
) -> dict[str, object]:
    """Read an exact-source excerpt; never infer SAT positions or mutate sources.

    The *calling host* must authorize repository_root and active_project_id;
    this local boundary checks both constraints again for each request.
    Caller should recheck authorization whenever its selected project changes.
    """
    if not isinstance(locator, Mapping):
        raise EvidenceNavigationError("Expected source-evidence locator mapping")
    for key in ("producer_module", "finding_id", "project_id", "relative_path", "source_sha256"):
        value = locator.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 1024:
            raise EvidenceNavigationError(f"Invalid locator {key}")
    if locator.get("producer_module") != "pypique":
        raise EvidenceNavigationError("Only pyPIQUE source evidence is supported")
    if not isinstance(active_project_id, str) or not active_project_id or locator["project_id"] != active_project_id:
        raise EvidenceNavigationError("Source evidence belongs to a different project")
    relative = locator["relative_path"]
    parts = relative.split("/")
    parsed = PurePosixPath(relative)
    if (relative.startswith("/") or "\\" in relative or "\x00" in relative or
        not parts or any(part in ("", ".", "..") for part in parts) or
        ":" in parts[0] or parsed.as_posix() != relative):
        raise EvidenceNavigationError("Source path must be canonical and project-relative")
    start, end = locator.get("start_line"), locator.get("end_line")
    if (type(start) is not int or type(end) is not int or start < 1 or
        end < start or end - start + 1 > _MAX_LINES):
        raise EvidenceNavigationError("Invalid or excessive source line range")
    expected = locator["source_sha256"]
    if not _SHA256.fullmatch(expected):
        raise EvidenceNavigationError("Source fingerprint must be SHA-256 lowercase hex")
    try:
        root = Path(repository_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise EvidenceNavigationError("Authorized repository root is not a directory")
        target = (root / relative).resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file():
            raise EvidenceNavigationError("Source file escapes authorized repository")
        # Open only after checking the size; refuse unexpected changes during read.
        before = target.stat()
        if before.st_size > _MAX_FILE_BYTES:
            raise EvidenceNavigationError("Source file exceeds size limit")
        with target.open("rb") as handle:
            raw = handle.read(_MAX_FILE_BYTES + 1)
            after = handle.stat() if hasattr(handle, "stat") else target.stat()
        if len(raw) > _MAX_FILE_BYTES or before.st_size != len(raw) or after.st_size != len(raw):
            raise EvidenceNavigationError("Source changed during inspection")
    except (OSError, RuntimeError) as exc:
        raise EvidenceNavigationError("Cannot safely access source file") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected:
        raise EvidenceNavigationError("Stale finding: source fingerprint mismatch")
    if b"\x00" in raw:
        raise EvidenceNavigationError("Binary source is not supported")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise EvidenceNavigationError("Source must be UTF-8") from exc
    if end > len(lines):
        raise EvidenceNavigationError("Source line range no longer exists")
    excerpt = "\n".join(lines[start - 1:end])
    if len(excerpt.encode("utf-8")) > _MAX_EXCERPT_BYTES:
        raise EvidenceNavigationError("Source excerpt exceeds byte limit")
    return {
        "schema": _SCHEMA, "mode": "read_only",
        "producer_module": "pypique", "finding_id": locator["finding_id"],
        "project_id": active_project_id, "relative_path": relative,
        "start_line": start, "end_line": end, "source_sha256": digest,
        "excerpt": excerpt,
    }
