"""ATLAS-1.4: provisional, source-backed test-operation *candidates*.

This is neither an IEEE 716 grammar nor hardware semantics. Exact leading
keywords and a few lexical forms are inspected conservatively; observed
syntactic patterns are not validated instructions, resource assignments, limits,
or execution dependencies. Missing real-world dialect fixtures are intentional.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ast import GroupNode, ParseResult, StatementNode, SyntaxElement, TokenNode
from .lexer import LexerConfig
from .parser import ParseConfig, parse_file, parse_source
from .reconnaissance import DEFAULT_MAX_BYTES
from .tokens import SourceSpan, Token, TokenKind

OPERATIONS_SCHEMA = "cps.atlas.operation-candidates@1"

# An opt-in heuristic vocabulary, NOT a validated ATLAS keyword grammar.
_DEFAULT_HEADS = (
    ("measurement", "MEASURE"),
    ("stimulus", "APPLY"),
    ("evaluation", "VERIFY"),
    ("connection", "CONNECT"),
    ("connection", "DISCONNECT"),
    ("configuration", "SETUP"),
)
_KINDS = frozenset(kind for kind, _ in _DEFAULT_HEADS) | frozenset(("sequence",))
_TRIVIA = frozenset((TokenKind.WHITESPACE, TokenKind.NEWLINE, TokenKind.COMMENT))
# Only familiar unit *spellings* are collected; dimensionality is not verified.
_UNIT_SPELLINGS = frozenset({
    "V", "MV", "KV", "VOLT", "VOLTS", "A", "MA", "UA", "AMP", "AMPS",
    "AMPERE", "AMPERES", "HZ", "KHZ", "MHZ", "GHZ", "S", "MS", "US",
    "SEC", "SECOND", "SECONDS", "OHM", "OHMS", "KOHM", "MOHM",
    "W", "MW", "WATT", "WATTS", "DEG", "DEGREES", "CELSIUS", "DB",
})
_RESOURCE_INTRODUCERS = frozenset(("USING", "INSTRUMENT", "RESOURCE", "EQUIPMENT"))
_COMPARATORS = frozenset(("=", "==", "<", ">", "<=", ">=", "!=", "<>"))


@dataclass(frozen=True)
class ExtractionConfig:
    """Append explicitly opted-in dialect head mappings; not grammar claims."""

    additional_heads: tuple[tuple[str, str], ...] = ()  # (family, spelling)

    def __post_init__(self) -> None:
        mapping = {head: family for family, head in _DEFAULT_HEADS}
        for family, head in self.additional_heads:
            if family not in _KINDS:
                raise ValueError(f"unknown candidate family {family!r}; choose from {', '.join(sorted(_KINDS))}")
            if not head or not head.isidentifier() or head != head.strip():
                raise ValueError(f"candidate head must be an identifier: {head!r}")
            normalized = head.upper()
            if normalized in mapping and mapping[normalized] != family:
                raise ValueError(f"ambiguous head {head!r}: {mapping[normalized]} and {family}")
            mapping[normalized] = family

    def head_families(self) -> dict[str, str]:
        mapping = {head: family for family, head in _DEFAULT_HEADS}
        mapping.update((head.upper(), family) for family, head in self.additional_heads)
        return mapping


@dataclass(frozen=True)
class ArgumentCandidate:
    text: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantityCandidate:
    value_text: str
    unit_text: str
    span: SourceSpan
    recognition: str = "adjacent_number_and_unit_spelling"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceCandidate:
    introducer: str
    reference_text: str
    span: SourceSpan
    recognition: str = "introducer_followed_by_identifier"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComparisonCandidate:
    left_text: str
    operator: str
    right_text: str
    span: SourceSpan
    recognition: str = "lexical_comparison_not_verified_test_limit"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationCandidate:
    statement_id: str
    family: str
    head_spelling: str
    numeric_prefix_candidate: str | None
    span: SourceSpan
    raw_statement: str
    arguments: tuple[ArgumentCandidate, ...]
    quantities: tuple[QuantityCandidate, ...]
    resources: tuple[ResourceCandidate, ...]
    comparisons: tuple[ComparisonCandidate, ...]
    has_source_diagnostics: bool
    terminated: bool
    recognition: str = "exact_leading_head_heuristic"
    semantic_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationExtractionResult:
    parsed: ParseResult
    candidates: tuple[OperationCandidate, ...]
    unclassified_statement_ids: tuple[str, ...]
    source_order_links: tuple[tuple[str, str], ...]
    configured_heads: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        """Source fragments/identifiers are private; output is for local use."""
        return {
            "schema": OPERATIONS_SCHEMA,
            "source_name": self.parsed.source_name,
            "encoding_candidate": self.parsed.encoding_candidate,
            "configuration": {
                "terminators": list(self.parsed.terminators),
                "strict": self.parsed.strict,
                "candidate_head_map": [
                    {"head": head, "family": kind} for head, kind in self.configured_heads
                ],
            },
            "candidates": [c.to_dict() for c in self.candidates],
            "unclassified_statement_ids": list(self.unclassified_statement_ids),
            "source_order_links": [
                {"source_statement_id": a, "target_statement_id": b,
                 "relationship": "adjacent_in_source", "execution_semantics": "unknown"}
                for a, b in self.source_order_links
            ],
            "diagnostics": [d.to_dict() for d in self.parsed.diagnostics],
            "summary": {
                "statement_count": len(self.parsed.statements),
                "candidate_count": len(self.candidates),
                "unclassified_count": len(self.unclassified_statement_ids),
                "grammar_validated_count": 0,
                "semantic_verified_count": 0,
                "candidate_with_diagnostics_count": sum(c.has_source_diagnostics for c in self.candidates),
                "error_count": sum(d.severity == "error" for d in self.parsed.diagnostics),
                "warning_count": sum(d.severity == "warning" for d in self.parsed.diagnostics),
            },
        }


def _flatten(items: tuple[SyntaxElement, ...]) -> tuple[Token, ...]:
    result: list[Token] = []
    for item in items:
        if isinstance(item, TokenNode):
            result.append(item.token)
        elif isinstance(item, GroupNode):
            result.append(item.opener)
            result.extend(_flatten(item.children))
            if item.closer is not None:
                result.append(item.closer)
    return tuple(result)


def _significant(tokens: tuple[Token, ...] | list[Token]) -> list[Token]:
    return [token for token in tokens if token.kind not in _TRIVIA]


def _arguments(tokens: tuple[Token, ...]) -> tuple[ArgumentCandidate, ...]:
    """Split comma-separated fields at depth zero after the statement head."""
    pieces: list[list[Token]] = [[]]
    opens = {"(": ")", "[": "]", "{": "}"}
    depth: list[str] = []
    for tok in tokens:
        if tok.kind == TokenKind.PUNCTUATION:
            if tok.lexeme in opens:
                depth.append(opens[tok.lexeme])
            elif depth and tok.lexeme == depth[-1]:
                depth.pop()
            if tok.lexeme == "," and not depth:
                pieces.append([])
                continue
        pieces[-1].append(tok)
    result = []
    for piece in pieces:
        meaningful = _significant(piece)
        if meaningful:
            start, end = meaningful[0].span.start, meaningful[-1].span.end
            # Original offsets are code-point indexes; trivia within the segment
            # is faithfully retained without including separators.
            all_tokens = [x for x in piece if x.span.start.offset >= start.offset and x.span.end.offset <= end.offset]
            result.append(ArgumentCandidate("".join(x.lexeme for x in all_tokens), SourceSpan(start, end)))
    return tuple(result)


def _hints(tokens: tuple[Token, ...]) -> tuple[tuple[QuantityCandidate, ...], tuple[ResourceCandidate, ...], tuple[ComparisonCandidate, ...]]:
    significant = _significant(tokens)
    quantities: list[QuantityCandidate] = []
    resources: list[ResourceCandidate] = []
    comparisons: list[ComparisonCandidate] = []
    for index, token in enumerate(significant):
        next_token = significant[index + 1] if index + 1 < len(significant) else None
        if (token.kind == TokenKind.NUMBER and next_token is not None
                and next_token.kind == TokenKind.IDENTIFIER
                and next_token.lexeme.upper() in _UNIT_SPELLINGS):
            quantities.append(QuantityCandidate(
                token.lexeme, next_token.lexeme,
                SourceSpan(token.span.start, next_token.span.end),
            ))
        if (token.kind == TokenKind.IDENTIFIER
                and token.lexeme.upper() in _RESOURCE_INTRODUCERS):
            following = index + 1
            # Permits `USING, DMM1` as well as `USING DMM1`. Neither is validated.
            if (following < len(significant) and significant[following].lexeme == ","):
                following += 1
            if following < len(significant) and significant[following].kind == TokenKind.IDENTIFIER:
                target = significant[following]
                resources.append(ResourceCandidate(
                    token.lexeme, target.lexeme, SourceSpan(token.span.start, target.span.end)
                ))
        if (token.kind == TokenKind.OPERATOR and token.lexeme in _COMPARATORS
                and 0 < index < len(significant) - 1):
            left, right = significant[index - 1], significant[index + 1]
            if (left.kind in (TokenKind.IDENTIFIER, TokenKind.NUMBER)
                    and right.kind in (TokenKind.IDENTIFIER, TokenKind.NUMBER)):
                comparisons.append(ComparisonCandidate(
                    left.lexeme, token.lexeme, right.lexeme,
                    SourceSpan(left.span.start, right.span.end),
                ))
    return tuple(quantities), tuple(resources), tuple(comparisons)


def _has_diagnostics(statement: StatementNode, parsed: ParseResult) -> bool:
    return any(
        d.span.start.offset < statement.span.end.offset
        and d.span.end.offset > statement.span.start.offset
        for d in parsed.diagnostics
    )


def extract_operations(
    parsed: ParseResult, *, config: ExtractionConfig | None = None,
) -> OperationExtractionResult:
    """Classify exact leading-head spelling only; no ATLAS semantics verified."""
    mapping = (config or ExtractionConfig()).head_families()
    candidates: list[OperationCandidate] = []
    unclassified: list[str] = []
    all_ids = [f"stmt-{n:06d}" for n in range(1, len(parsed.statements) + 1)]
    for stmt_id, stmt in zip(all_ids, parsed.statements):
        head = stmt.head_candidate
        if head is None or head.upper() not in mapping:
            unclassified.append(stmt_id)
            continue
        tokens = _flatten(stmt.elements)
        significant = _significant(tokens)
        head_index = 1 if stmt.numeric_prefix_candidate else 0
        if (head_index >= len(significant)
                or significant[head_index].kind != TokenKind.IDENTIFIER
                or significant[head_index].lexeme.upper() != head.upper()):
            # Structural candidate disagrees with its tokens; never guess.
            unclassified.append(stmt_id)
            continue
        head_token = significant[head_index]
        remaining = tuple(t for t in tokens if t.span.start.offset >= head_token.span.end.offset)
        # A leading comma after the head separates the keyword from its arguments.
        index = next((i for i, t in enumerate(remaining) if t.kind not in _TRIVIA), None)
        if index is not None and remaining[index].lexeme == ",":
            remaining = remaining[index + 1:]
        quantities, resources, comparisons = _hints(remaining)
        candidates.append(OperationCandidate(
            statement_id=stmt_id, family=mapping[head.upper()],
            head_spelling=head_token.lexeme,
            numeric_prefix_candidate=stmt.numeric_prefix_candidate,
            span=stmt.span, raw_statement=stmt.text,
            arguments=_arguments(remaining), quantities=quantities,
            resources=resources, comparisons=comparisons,
            has_source_diagnostics=_has_diagnostics(stmt, parsed),
            terminated=stmt.terminator is not None,
        ))
    return OperationExtractionResult(
        parsed=parsed, candidates=tuple(candidates),
        unclassified_statement_ids=tuple(unclassified),
        source_order_links=tuple(zip(all_ids, all_ids[1:])),
        configured_heads=tuple(sorted(mapping.items())),
    )


def extract_source(
    source: str, *, source_name: str = "<memory>",
    extraction_config: ExtractionConfig | None = None,
    parse_config: ParseConfig | None = None,
    lexer_config: LexerConfig | None = None,
) -> OperationExtractionResult:
    return extract_operations(
        parse_source(source, source_name=source_name, config=parse_config, lexer_config=lexer_config),
        config=extraction_config,
    )


def extract_file(
    path: Path, *, extraction_config: ExtractionConfig | None = None,
    parse_config: ParseConfig | None = None, lexer_config: LexerConfig | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> OperationExtractionResult:
    return extract_operations(
        parse_file(path, config=parse_config, lexer_config=lexer_config, max_bytes=max_bytes),
        config=extraction_config,
    )
