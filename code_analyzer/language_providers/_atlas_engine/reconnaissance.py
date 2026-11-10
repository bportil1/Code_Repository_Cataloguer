"""Offline source inventory used to plan the ATLAS grammar implementation.

This module intentionally does **not** tokenize, parse or interpret ATLAS.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable

from .grammar_coverage import grammar_register

INVENTORY_SCHEMA = "cps.atlas.source-inventory@1"
DEFAULT_ATLAS_EXTENSIONS = (".atl", ".atlas", ".atls")
DEFAULT_C_EXTENSIONS = (".c", ".h")
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


def normalize_extensions(extensions: Iterable[str]) -> tuple[str, ...]:
    """Validate and normalize a user-selected set of file suffixes."""
    result: set[str] = set()
    for expression in extensions:
        for item in expression.split(","):
            value = item.strip().lower()
            if not value:
                continue
            if not value.startswith("."):
                value = "." + value
            if value == "." or any(char in value for char in "/*?\\ "):
                raise ValueError(f"invalid extension: {item!r}")
            result.add(value)
    if not result:
        raise ValueError("at least one filename extension is required")
    return tuple(sorted(result))


def _iter_source_files(
    root: Path, extensions: tuple[str, ...], include_hidden: bool,
    on_walk_error: Callable[[OSError], None],
) -> Iterable[Path]:
    # Path.rglob does not follow directory symlinks in supported Python versions,
    # but walk explicitly to keep the rule visible and avoid symlinked files.
    import os

    for current, dirs, filenames in os.walk(
        root, followlinks=False, onerror=on_walk_error
    ):
        dirs[:] = sorted(
            d for d in dirs
            if (include_hidden or not d.startswith("."))
            and not (Path(current) / d).is_symlink()
        )
        for name in sorted(filenames):
            if not include_hidden and name.startswith("."):
                continue
            file_path = Path(current) / name
            if file_path.is_symlink() or file_path.suffix.lower() not in extensions:
                continue
            yield file_path


def _decode_source(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding, errors="strict"), encoding
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 must decode arbitrary bytes")


def _newline_style(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    styles = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    return "mixed" if len(styles) > 1 else (styles[0] if styles else "none")


def _read_metadata(path: Path, root: Path, kind: str, max_bytes: int) -> dict[str, Any]:
    # Do not store decoded source in the exported inventory.
    # Bound reads even when a source file is unexpectedly large.
    with path.open("rb") as source:
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"file exceeds max_bytes={max_bytes}")
    decoded, encoding = _decode_source(data)
    return {
        "kind": kind,
        "path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "physical_lines": len(decoded.splitlines()),
        "encoding_candidate": encoding,
        "newline_style": _newline_style(data),
        "contains_nul": b"\x00" in data,
    }


def _root_files(
    root: Path,
    kind: str,
    extensions: tuple[str, ...],
    include_hidden: bool,
    max_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    def on_walk_error(exc: OSError) -> None:
        try:
            relative_path = Path(exc.filename).relative_to(root).as_posix()
        except (TypeError, ValueError):
            relative_path = "."
        errors.append({
            "kind": kind,
            "path": relative_path,
            "message": f"{type(exc).__name__}: {exc}",
        })

    for path in _iter_source_files(root, extensions, include_hidden, on_walk_error):
        try:
            records.append(_read_metadata(path, root, kind, max_bytes))
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append({
                "kind": kind,
                "path": path.relative_to(root).as_posix(),
                "message": f"{type(exc).__name__}: {exc}",
            })
    return records, errors


def _candidate_pairs(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    c_by_stem: dict[str, list[str]] = defaultdict(list)
    for item in records:
        if item["kind"] == "c" and Path(item["path"]).suffix.lower() == ".c":
            c_by_stem[Path(item["path"]).stem.casefold()].append(item["path"])
    candidates = []
    for item in records:
        if item["kind"] != "atlas":
            continue
        for c_path in c_by_stem[Path(item["path"]).stem.casefold()]:
            candidates.append({
                "atlas_path": item["path"],
                "c_path": c_path,
                "evidence": "matching_filename_stem_only",
                "status": "unverified_candidate",
            })
    return sorted(candidates, key=lambda x: (x["atlas_path"], x["c_path"]))


def build_inventory(
    atlas_root: Path,
    *,
    c_root: Path | None = None,
    atlas_extensions: Iterable[str] = DEFAULT_ATLAS_EXTENSIONS,
    include_hidden: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Inventory sources without parsing them or exporting their contents.

    Raises ValueError if the requested input paths or options are invalid.
    A readable tree with problematic files returns per-file ``errors`` instead.
    """
    root = Path(atlas_root).expanduser()
    if not root.is_dir():
        raise ValueError(f"ATLAS source directory does not exist: {root}")
    if root.is_symlink():
        raise ValueError("ATLAS root must not be a symbolic link")
    other = Path(c_root).expanduser() if c_root is not None else None
    if other is not None and (not other.is_dir() or other.is_symlink()):
        raise ValueError(f"C source directory does not exist or is a symlink: {other}")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    suffixes = normalize_extensions(atlas_extensions)
    atlas_files, errors = _root_files(root, "atlas", suffixes, include_hidden, max_bytes)
    c_files: list[dict[str, Any]] = []
    if other is not None:
        c_files, c_errors = _root_files(
            other, "c", DEFAULT_C_EXTENSIONS, include_hidden, max_bytes
        )
        errors.extend(c_errors)

    files = sorted(atlas_files + c_files, key=lambda item: (item["kind"], item["path"]))
    summary = {
        "atlas_files": len(atlas_files),
        "c_files": len(c_files),
        "total_bytes": sum(item["bytes"] for item in files),
        "error_count": len(errors),
        "encoding_candidates": dict(sorted(Counter(
            item["encoding_candidate"] for item in files
        ).items())),
        "newline_styles": dict(sorted(Counter(
            item["newline_style"] for item in files
        ).items())),
    }
    return {
        "schema": INVENTORY_SCHEMA,
        "atlas_root": str(root),
        "c_root": str(other) if other is not None else None,
        "atlas_extensions": list(suffixes),
        "files": files,
        "candidates": _candidate_pairs(files),
        "errors": errors,
        "summary": summary,
        "grammar": grammar_register(),
    }
