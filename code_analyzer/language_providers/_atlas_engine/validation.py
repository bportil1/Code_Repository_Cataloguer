"""ATLAS-1.7: bounded, local, source-preserving legacy validation.

This module reports *structural inspection coverage*, not IEEE 716 grammar
compliance. It does not infer hardware semantics or use test execution data.
Exports contain source identifiers and locations, but not complete source text.
"""

from __future__ import annotations

import os
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from .analysis import AnalysisConfig, analyze_source
from .operations import _flatten, _significant
from .reconnaissance import (
    DEFAULT_ATLAS_EXTENSIONS,
    DEFAULT_MAX_BYTES,
    normalize_extensions,
)

VALIDATION_SCHEMA = "cps.atlas.validation@1"
CORPUS_SCHEMA = "cps.atlas.validation-corpus@1"
ENCODINGS = ("auto", "utf-8", "utf-16", "cp1252", "latin-1")
MAX_CORPUS_FILES = 10000


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _newline_style(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    styles = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    return "mixed" if len(styles) > 1 else (styles[0] if styles else "none")


def _decode_legacy(raw: bytes, requested: str) -> tuple[str, str, str | None]:
    """Decode deterministically, including UTF-16 only with an explicit BOM.

    The fallback encoding is a *candidate*, never a validated dialect property.
    Unknown 8-bit content may decode as Latin-1 even when it is not text.
    """
    if requested not in ENCODINGS:
        raise ValueError(f"encoding must be one of: {', '.join(ENCODINGS)}")
    utf16 = raw.startswith((b"\xff\xfe", b"\xfe\xff"))
    utf8_bom = raw.startswith(b"\xef\xbb\xbf")
    if requested != "auto":
        if utf16 and requested != "utf-16":
            raise ValueError("UTF-16 BOM conflicts with requested encoding")
        if utf8_bom and requested != "utf-8":
            raise ValueError("UTF-8 BOM conflicts with requested encoding")
        if requested == "utf-16" and not utf16:
            raise ValueError("UTF-16 input requires a BOM for reliable byte order")
        codec = ("utf-8-sig" if utf8_bom else requested)
        decoded = raw.decode(codec, errors="strict")
        used = "utf-8-sig" if utf8_bom else requested
        return decoded, used, None
    if utf16:
        return raw.decode("utf-16", errors="strict"), "utf-16", None
    if utf8_bom:
        return raw.decode("utf-8-sig", errors="strict"), "utf-8-sig", None
    try:
        return raw.decode("utf-8", errors="strict"), "utf-8", None
    except UnicodeDecodeError:
        pass
    try:
        return (raw.decode("cp1252", errors="strict"), "cp1252",
                "ENCODING_FALLBACK_UNVERIFIED")
    except UnicodeDecodeError:
        return (raw.decode("latin-1", errors="strict"), "latin-1",
                "ENCODING_LATIN1_FALLBACK_UNVERIFIED")


def _span_dict(span: Any) -> dict[str, Any]:
    return {
        "start": {"offset": span.start.offset, "line": span.start.line,
                  "column": span.start.column},
        "end": {"offset": span.end.offset, "line": span.end.line,
                "column": span.end.column},
    }


def validate_source(
    source: str, *, source_name: str = "<memory>",
    config: AnalysisConfig | None = None,
    raw_sha256: str | None = None,
    byte_count: int | None = None,
    encoding_candidate: str | None = None,
    encoding_warning: str | None = None,
) -> dict[str, Any]:
    """Inspect decoded source; every classification is unverified/heuristic.

    No raw source text is returned. Diagnostic messages and names may still
    reveal identifiers, so exported metadata should also be treated as private.
    """
    analysis = analyze_source(source, source_name=source_name, config=config)
    parsed = analysis.parsed
    extracted = analysis.indexed.extraction
    operations = {op.statement_id: op.family for op in extracted.candidates}
    statements: list[dict[str, Any]] = []
    for i, stmt in enumerate(parsed.statements, 1):
        sid = f"stmt-{i:06d}"
        codes = sorted({d.code for d in parsed.diagnostics
                        if (d.span.start.offset < stmt.span.end.offset
                            and d.span.end.offset > stmt.span.start.offset)})
        meaningful = _significant(_flatten(stmt.elements))
        start = meaningful[0].span.start if meaningful else stmt.span.start
        statements.append({
            "id": sid,
            "first_significant_line": start.line,
            "first_significant_column": start.column,
            "span": _span_dict(stmt.span),
            "head_candidate": stmt.head_candidate,
            "terminated": stmt.terminator is not None,
            "operation_candidate_family": operations.get(sid),
            "diagnostic_codes": codes,
            "grammar_validated": False,
            "hardware_semantics_verified": False,
        })

    diagnostics = [d.to_dict() for d in parsed.diagnostics]
    if encoding_warning:
        diagnostics.append({
            "code": encoding_warning, "severity": "warning",
            "message": "encoding inferred through an unverified legacy fallback",
            "span": None,
        })
    newline_style = _newline_style(source)
    if newline_style == "mixed":
        diagnostics.append({
            "code": "LEGACY_MIXED_NEWLINES", "severity": "warning",
            "message": "source contains more than one newline convention", "span": None,
        })
    if any(ord(c) < 32 and c not in "\n\r\t" for c in source):
        diagnostics.append({
            "code": "LEGACY_CONTROL_CHARACTERS", "severity": "warning",
            "message": "source contains control characters outside tab/newline", "span": None,
        })
    candidate_families = dict(sorted(Counter(operations.values()).items()))
    total = len(statements)
    terminated = sum(x["terminated"] for x in statements)
    unclassified = sum(x["operation_candidate_family"] is None for x in statements)
    structurally_diagnostic = sum(bool(x["diagnostic_codes"]) for x in statements)
    errors = sum(d["severity"] == "error" for d in diagnostics)
    warnings = sum(d["severity"] == "warning" for d in diagnostics)
    return {
        "schema": VALIDATION_SCHEMA,
        "source": {
            "name": source_name,
            "bytes": byte_count,
            "raw_sha256": raw_sha256,
            "decoded_text_sha256_utf8": sha256(source.encode("utf-8")).hexdigest(),
            "decoded_length": len(source),
            "encoding_candidate": encoding_candidate,
            "encoding_verified": False,
            "newline_style": newline_style,
            "roundtrip_complete": parsed.to_source() == source,
        },
        "interpretation": {
            "grammar_validated": False,
            "hardware_semantics_verified": False,
            "candidate_family_basis": "leading_head_heuristic_only",
            "statement_order_basis": "source_order_not_execution_order",
            "coverage_is_not_grammar_compliance": True,
            "source_text_included": False,
        },
        "summary": {
            "statement_count": total,
            "terminated_statement_count": terminated,
            "unterminated_statement_count": total - terminated,
            "statements_with_structural_diagnostics": structurally_diagnostic,
            "operation_candidate_count": len(operations),
            "unclassified_statement_count": unclassified,
            "operation_candidates_by_family": candidate_families,
            "termination_fraction": _ratio(terminated, total),
            "heuristic_classification_fraction": _ratio(len(operations), total),
            "grammar_validated_statement_count": 0,
            "error_count": errors,
            "warning_count": warnings,
        },
        "statements": statements,
        "diagnostics": diagnostics,
    }


def validate_file(
    path: Path, *, config: AnalysisConfig | None = None,
    encoding: str = "auto", max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Inspect one non-symlink source file with bounded binary I/O."""
    path = Path(path).expanduser()
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"source must be a regular non-symlink file: {path}")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"source exceeds max_bytes={max_bytes}: {path}")
    source, used, fallback_warning = _decode_legacy(raw, encoding)
    if "\x00" in source:
        raise ValueError("decoded source contains NUL characters; possible binary or incorrect encoding")
    return validate_source(source, source_name=str(path), config=config,
                           raw_sha256=sha256(raw).hexdigest(), byte_count=len(raw),
                           encoding_candidate=used, encoding_warning=fallback_warning)


def _iter_sources(root: Path, extensions: tuple[str, ...], include_hidden: bool) -> Iterable[Path]:
    def walk_error(exc: OSError) -> None:
        raise exc

    for current, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(n for n in dirs if (include_hidden or not n.startswith("."))
                         and not (Path(current) / n).is_symlink())
        for name in sorted(names):
            if not include_hidden and name.startswith("."):
                continue
            p = Path(current) / name
            if p.suffix.lower() in extensions and not p.is_symlink():
                yield p


def validate_corpus(
    root: Path, *, config: AnalysisConfig | None = None,
    encoding: str = "auto", max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = MAX_CORPUS_FILES,
    extensions: Iterable[str] = DEFAULT_ATLAS_EXTENSIONS,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """Validate a directory without aborting on errors in individual files."""
    root = Path(root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"root must be a non-symlink directory: {root}")
    if max_files < 1 or max_bytes <= 0:
        raise ValueError("max_files and max_bytes must be positive")
    if encoding not in ENCODINGS:
        raise ValueError(f"encoding must be one of: {', '.join(ENCODINGS)}")
    suffixes = normalize_extensions(extensions)
    files: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    visited = 0
    try:
        for p in _iter_sources(root, suffixes, include_hidden):
            visited += 1
            if visited > max_files:
                failures.append({"path": ".", "code": "CORPUS_FILE_LIMIT",
                                 "message": f"more than {max_files} files matched; report is incomplete"})
                break
            name = p.relative_to(root).as_posix()
            try:
                report = validate_file(p, config=config, encoding=encoding, max_bytes=max_bytes)
                # Avoid absolute paths in corpus artifacts; source file identity is relative.
                report["source"]["name"] = name
                files.append(report)
            except (OSError, UnicodeError, ValueError) as exc:
                failures.append({"path": name, "code": "SOURCE_READ_OR_DECODE_FAILED",
                                 "message": f"{type(exc).__name__}: {exc}"})
    except OSError as exc:
        failures.append({"path": ".", "code": "SOURCE_TREE_WALK_FAILED",
                         "message": f"{type(exc).__name__}: {exc}"})

    # os.walk sorts each directory; sort records by relative path for stable output.
    files.sort(key=lambda item: item["source"]["name"])
    failures.sort(key=lambda item: (item["path"], item["code"]))
    summary = {
        "files_analyzed": len(files),
        "file_errors": len(failures),
        "statement_count": sum(f["summary"]["statement_count"] for f in files),
        "terminated_statement_count": sum(f["summary"]["terminated_statement_count"] for f in files),
        "operation_candidate_count": sum(f["summary"]["operation_candidate_count"] for f in files),
        "unclassified_statement_count": sum(f["summary"]["unclassified_statement_count"] for f in files),
        "grammar_validated_statement_count": 0,
        "error_count": sum(f["summary"]["error_count"] for f in files),
        "warning_count": sum(f["summary"]["warning_count"] for f in files),
    }
    summary["termination_fraction"] = _ratio(summary["terminated_statement_count"], summary["statement_count"])
    summary["heuristic_classification_fraction"] = _ratio(summary["operation_candidate_count"], summary["statement_count"])
    return {
        "schema": CORPUS_SCHEMA,
        "root": str(root),
        "source_policy": "local_only; no full source text in report",
        "coverage_is_not_grammar_compliance": True,
        "extensions": list(suffixes),
        "files": files,
        "errors": failures,
        "summary": summary,
    }
