"""ATLAS-1.6 local analysis API: consolidated *candidate* graph and inventory.

The graph captures source order and provisional lexical associations only.
Neither adjacent statements nor lexical references imply execution ordering,
hardware connectivity, causal relations, or validated IEEE 716 semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from .ast import StatementNode
from .lexer import LexerConfig
from .operations import ExtractionConfig, extract_source, extract_file, _flatten, _significant
from .parser import ParseConfig
from .reconnaissance import DEFAULT_MAX_BYTES
from .semantics import SymbolConfig, SymbolIndexResult, index_symbols

ANALYSIS_SCHEMA = "cps.atlas.analysis@1"


@dataclass(frozen=True)
class AnalysisConfig:
    """Compose existing opt-in heuristics without changing their semantics."""

    lexer: LexerConfig = field(default_factory=LexerConfig)
    parser: ParseConfig = field(default_factory=ParseConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    symbols: SymbolConfig = field(default_factory=SymbolConfig)


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    statement_id: str | None
    name: str | None
    span: dict[str, Any]
    semantic_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source: str
    target: str
    relationship: str
    evidence: str
    execution_semantics: str = "unknown"
    semantic_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisResult:
    """All views come from a single parse, preserving stable source offsets."""

    indexed: SymbolIndexResult
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @property
    def parsed(self):
        return self.indexed.extraction.parsed

    def statement_at_line(self, line: int) -> tuple[tuple[str, StatementNode], ...]:
        """Find statements intersecting a 1-based source line, including multiline ones."""
        if line < 1:
            raise ValueError("line must be >= 1")
        # Source envelopes can begin with inter-statement whitespace. For a
        # line-based search use meaningful token spans, not leading trivia.
        found: list[tuple[str, StatementNode]] = []
        for i, statement in enumerate(self.parsed.statements, 1):
            meaningful = _significant(_flatten(statement.elements))
            if (meaningful and meaningful[0].span.start.line <= line
                    <= meaningful[-1].span.end.line):
                found.append((f"stmt-{i:06d}", statement))
        return tuple(found)

    def adjacent_edges(self, node_id: str) -> tuple[GraphEdge, ...]:
        """Return edges touching a known node; unknown IDs are errors, not empty results."""
        if not any(node.id == node_id for node in self.nodes):
            raise KeyError(node_id)
        return tuple(edge for edge in self.edges
                     if edge.source == node_id or edge.target == node_id)

    def to_dict(self) -> dict[str, Any]:
        """Versioned, deterministic local artifact; may contain PRIVATE source text."""
        parsed = self.parsed
        extraction = self.indexed.extraction
        source = parsed.to_source()
        kinds: dict[str, int] = {}
        for candidate in extraction.candidates:
            kinds[candidate.family] = kinds.get(candidate.family, 0) + 1
        return {
            "schema": ANALYSIS_SCHEMA,
            "source": {
                "name": parsed.source_name,
                "decoded_length": parsed.source_length,
                "decoded_text_sha256_utf8": sha256(source.encode("utf-8")).hexdigest(),
                "encoding_candidate": parsed.encoding_candidate,
                "source_roundtrip_complete": len(source) == parsed.source_length,
            },
            "source_policy": "local_only_contains_original_source_fragments",
            "interpretation": {
                "syntax": "structural_only",
                "operation_classification": "heuristic_candidates",
                "symbols": "lexical_candidates_no_scoping",
                "graph": "source_order_and_candidate_references_not_execution_or_causation",
                "grammar_validated": False,
                "hardware_semantics_verified": False,
            },
            "configuration": {
                "parser": {"terminators": list(parsed.terminators), "strict": parsed.strict},
                "operation_heads": [
                    {"head": head, "family": family}
                    for head, family in extraction.configured_heads
                ],
                "symbols": self.indexed.to_dict()["configuration"],
            },
            "statements": [
                {"id": f"stmt-{i:06d}", **statement.to_dict()}
                for i, statement in enumerate(parsed.statements, 1)
            ],
            "trailing_text": parsed.trailing_text,
            "operations": [_json_safe(c.to_dict()) for c in extraction.candidates],
            "unclassified_statement_ids": list(extraction.unclassified_statement_ids),
            "symbols": [_json_safe(s.to_dict()) for s in self.indexed.symbols],
            "references": [_json_safe(r.to_dict()) for r in self.indexed.references],
            "graph": {
                "nodes": [n.to_dict() for n in self.nodes],
                "edges": [e.to_dict() for e in self.edges],
            },
            "diagnostics": [d.to_dict() for d in self.indexed.diagnostics],
            "summary": {
                "statement_count": len(parsed.statements),
                "terminated_count": sum(s.terminator is not None for s in parsed.statements),
                "unclassified_count": len(extraction.unclassified_statement_ids),
                "operation_candidate_count": len(extraction.candidates),
                "operation_candidates_by_family": dict(sorted(kinds.items())),
                "symbol_candidate_count": len(self.indexed.symbols),
                "reference_candidate_count": len(self.indexed.references),
                "unique_name_match_count": sum(r.resolution == "unique_candidate"
                                               for r in self.indexed.references),
                "ambiguous_reference_count": sum(r.resolution == "ambiguous"
                                                 for r in self.indexed.references),
                "unresolved_reference_count": sum(r.resolution == "unresolved"
                                                  for r in self.indexed.references),
                "graph_node_count": len(self.nodes),
                "graph_edge_count": len(self.edges),
                "error_count": sum(d.severity == "error" for d in self.indexed.diagnostics),
                "warning_count": sum(d.severity == "warning" for d in self.indexed.diagnostics),
                "grammar_validated_count": 0,
                "semantic_verified_count": 0,
            },
        }


def _json_safe(value: Any) -> Any:
    """Ensure the Python artifact uses JSON arrays rather than tuple internals."""
    if isinstance(value, tuple) or isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _assemble(indexed: SymbolIndexResult) -> AnalysisResult:
    parsed = indexed.extraction.parsed
    extraction = indexed.extraction
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    def link(source: str, target: str, relationship: str, evidence: str) -> None:
        edges.append(GraphEdge(f"edge-{len(edges)+1:06d}", source, target,
                               relationship, evidence))

    for i, statement in enumerate(parsed.statements, 1):
        sid = f"stmt-{i:06d}"
        nodes.append(GraphNode(sid, "statement", sid, statement.head_candidate,
                               asdict(statement.span)))
    for operation in extraction.candidates:
        oid = f"op-{operation.statement_id.removeprefix('stmt-')}"
        nodes.append(GraphNode(oid, "operation_candidate", operation.statement_id,
                               operation.family, asdict(operation.span)))
        link(operation.statement_id, oid, "candidate_operation_annotation",
             "heuristic_exact_statement_head")
    for symbol in indexed.symbols:
        nodes.append(GraphNode(symbol.symbol_id, "symbol_candidate", symbol.statement_id,
                               symbol.name, asdict(symbol.span)))
        link(symbol.statement_id, symbol.symbol_id, "candidate_declaration",
             "opt_in_declaration_head")
    for reference in indexed.references:
        nodes.append(GraphNode(reference.reference_id, "reference_candidate",
                               reference.statement_id, reference.name, asdict(reference.span)))
        link(reference.statement_id, reference.reference_id, "candidate_reference_occurrence",
             reference.recognition)
        # Only lexical unique matches become links. Ambiguous alternatives
        # remain in references[].target_symbol_ids; don't choose an arbitrary one.
        if reference.resolution == "unique_candidate":
            link(reference.reference_id, reference.target_symbol_ids[0],
                 "candidate_unique_name_match", reference.recognition)
    for sid, tid in extraction.source_order_links:
        link(sid, tid, "adjacent_in_source", "source_statement_order_only")

    known = {node.id for node in nodes}
    if len(known) != len(nodes) or any(edge.source not in known or edge.target not in known
                                     for edge in edges):
        raise ValueError("analysis graph has duplicate IDs or dangling relationships")
    return AnalysisResult(indexed, tuple(nodes), tuple(edges))


def analyze_source(source: str, *, source_name: str = "<memory>",
                   config: AnalysisConfig | None = None) -> AnalysisResult:
    options = config or AnalysisConfig()
    extraction = extract_source(
        source, source_name=source_name, lexer_config=options.lexer,
        parse_config=options.parser, extraction_config=options.extraction,
    )
    return _assemble(index_symbols(extraction, config=options.symbols))


def analyze_file(path: Path, *, config: AnalysisConfig | None = None,
                 max_bytes: int = DEFAULT_MAX_BYTES) -> AnalysisResult:
    options = config or AnalysisConfig()
    extraction = extract_file(
        path, lexer_config=options.lexer, parse_config=options.parser,
        extraction_config=options.extraction, max_bytes=max_bytes,
    )
    return _assemble(index_symbols(extraction, config=options.symbols))
