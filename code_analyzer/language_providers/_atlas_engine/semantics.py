"""ATLAS-1.5: candidate-only, file-local symbol and reference index.

No ATLAS declaration, lexical name match, or resource reference in this
module is grammar validated. No link denotes execution, causality, equipment
wiring or a confirmed program dependency. Declarations require an explicitly
configured heading: without a dialect profile, the symbol table is empty.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ast import ParseDiagnostic, StatementNode
from .lexer import LexerConfig
from .operations import (
    ExtractionConfig, OperationExtractionResult, _flatten, _has_diagnostics,
    _significant, extract_file, extract_source,
)
from .parser import ParseConfig
from .reconnaissance import DEFAULT_MAX_BYTES
from .tokens import SourceSpan, Token, TokenKind

SYMBOL_SCHEMA = "cps.atlas.symbol-candidates@1"
_SYMBOL_KINDS = frozenset({"variable", "resource", "procedure", "test", "label"})
_TRIVIA = frozenset({TokenKind.WHITESPACE, TokenKind.NEWLINE, TokenKind.COMMENT})


def _validate_rules(rules: tuple[tuple[str, str], ...], label: str) -> None:
    mapping: dict[str, str] = {}
    for kind, spelling in rules:
        if kind not in _SYMBOL_KINDS:
            raise ValueError(f"{label} kind must be one of {', '.join(sorted(_SYMBOL_KINDS))}: {kind!r}")
        if not spelling or not spelling.isidentifier() or spelling != spelling.strip():
            raise ValueError(f"{label} head must be a single identifier: {spelling!r}")
        folded = spelling.casefold()
        if folded in mapping and mapping[folded] != kind:
            raise ValueError(f"conflicting {label} head {spelling!r}")
        mapping[folded] = kind


@dataclass(frozen=True)
class SymbolConfig:
    """Opt-in lexical conventions, not an inferred ATLAS dialect.

    declaration_heads: (kind, head) means 'HEAD, IDENTIFIER' is considered
    a *candidate* declaration. reference_introducers: (kind, introducer)
    means 'INTRODUCER IDENTIFIER' is a *candidate* reference. Names from
    declarations can also be matched lexically in subsequent statements.
    """

    declaration_heads: tuple[tuple[str, str], ...] = ()
    reference_introducers: tuple[tuple[str, str], ...] = ()
    resource_hints: bool = True
    lexical_name_matches: bool = True
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        _validate_rules(self.declaration_heads, "declaration")
        _validate_rules(self.reference_introducers, "reference")
        decls = {spelling.casefold() for _, spelling in self.declaration_heads}
        refs = {spelling.casefold() for _, spelling in self.reference_introducers}
        if decls & refs:
            raise ValueError("a head cannot be both a declaration and reference introducer")

    def normalized(self, name: str) -> str:
        return name if self.case_sensitive else name.casefold()

    def declarations(self) -> dict[str, str]:
        return {head.casefold(): kind for kind, head in self.declaration_heads}

    def references(self) -> dict[str, str]:
        return {head.casefold(): kind for kind, head in self.reference_introducers}


@dataclass(frozen=True)
class SymbolCandidate:
    symbol_id: str
    statement_id: str
    kind: str
    name: str
    span: SourceSpan
    declaration_head: str
    has_source_diagnostics: bool
    recognition: str = "opt_in_declaration_head_followed_by_identifier"
    semantic_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReferenceCandidate:
    reference_id: str
    statement_id: str
    name: str
    kind_hint: str | None
    span: SourceSpan
    recognition: str
    resolution: str
    target_symbol_ids: tuple[str, ...]
    semantic_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateRelationship:
    reference_id: str
    source_statement_id: str
    target_symbol_id: str
    relationship: str = "candidate_lexical_reference"
    semantic_status: str = "unverified"
    execution_semantics: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SymbolIndexResult:
    extraction: OperationExtractionResult
    config: SymbolConfig
    symbols: tuple[SymbolCandidate, ...]
    references: tuple[ReferenceCandidate, ...]
    relationships: tuple[CandidateRelationship, ...]
    diagnostics: tuple[ParseDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        parsed = self.extraction.parsed
        return {
            "schema": SYMBOL_SCHEMA,
            "source_name": parsed.source_name,
            "encoding_candidate": parsed.encoding_candidate,
            "configuration": {
                "declaration_heads": [
                    {"kind": kind, "head": head} for kind, head in self.config.declaration_heads
                ],
                "reference_introducers": [
                    {"kind": kind, "head": head} for kind, head in self.config.reference_introducers
                ],
                "resource_hints": self.config.resource_hints,
                "lexical_name_matches": self.config.lexical_name_matches,
                "case_sensitive": self.config.case_sensitive,
            },
            "symbols": [s.to_dict() for s in self.symbols],
            "references": [r.to_dict() for r in self.references],
            "relationships": [r.to_dict() for r in self.relationships],
            "unclassified_statement_ids": list(self.extraction.unclassified_statement_ids),
            "source_order_links": self.extraction.to_dict()["source_order_links"],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "summary": {
                "statement_count": len(parsed.statements),
                "symbol_candidate_count": len(self.symbols),
                "reference_candidate_count": len(self.references),
                "unique_name_match_count": sum(r.resolution == "unique_candidate" for r in self.references),
                "unresolved_reference_count": sum(r.resolution == "unresolved" for r in self.references),
                "ambiguous_reference_count": sum(r.resolution == "ambiguous" for r in self.references),
                "candidate_relationship_count": len(self.relationships),
                "grammar_validated_count": 0,
                "semantic_verified_count": 0,
                "error_count": sum(d.severity == "error" for d in self.diagnostics),
                "warning_count": sum(d.severity == "warning" for d in self.diagnostics),
            },
        }


def _head_and_body(statement: StatementNode) -> tuple[Token | None, list[Token]]:
    """Identify leading head and following tokens, without semantic assumptions."""
    tokens = _significant(_flatten(statement.elements))
    ix = 1 if statement.numeric_prefix_candidate is not None else 0
    if ix >= len(tokens) or tokens[ix].kind != TokenKind.IDENTIFIER:
        return None, []
    return tokens[ix], tokens[ix + 1:]


def _identifier_after(tokens: list[Token], index: int) -> Token | None:
    # A single optional comma is permitted; do not search farther and guess.
    pos = index + 1
    if pos < len(tokens) and tokens[pos].lexeme == ",":
        pos += 1
    if pos < len(tokens) and tokens[pos].kind == TokenKind.IDENTIFIER:
        return tokens[pos]
    return None


def index_symbols(
    extraction: OperationExtractionResult, *, config: SymbolConfig | None = None,
) -> SymbolIndexResult:
    """Build tentative, file-local symbols and links without changing source AST."""
    options = config or SymbolConfig()
    decl_heads = options.declarations()
    ref_heads = options.references()
    parsed = extraction.parsed
    statement_tokens: list[list[Token]] = []
    symbols: list[SymbolCandidate] = []
    diagnostics = list(parsed.diagnostics)
    # Declaration name offsets must not become self-references.
    definitions_by_location: dict[tuple[int, int], Token] = {}

    for i, statement in enumerate(parsed.statements, 1):
        tokens = _significant(_flatten(statement.elements))
        statement_tokens.append(tokens)
        head, tail = _head_and_body(statement)
        if head is None or head.lexeme.casefold() not in decl_heads:
            continue
        named = _identifier_after([head] + tail, 0)
        if named is None:
            diagnostics.append(ParseDiagnostic(
                "SYMBOL_MISSING_IDENTIFIER", "warning",
                "configured candidate declaration has no immediate identifier", head.span,
                "symbol_index",
            ))
            continue
        definitions_by_location[(i, named.span.start.offset)] = named
        symbols.append(SymbolCandidate(
            symbol_id=f"sym-{len(symbols)+1:06d}",
            statement_id=f"stmt-{i:06d}", kind=decl_heads[head.lexeme.casefold()],
            name=named.lexeme, span=named.span, declaration_head=head.lexeme,
            has_source_diagnostics=_has_diagnostics(statement, parsed),
        ))

    # This is candidate name matching, *not* an ATLAS scope/type resolution.
    by_name: dict[str, list[SymbolCandidate]] = {}
    for symbol in symbols:
        by_name.setdefault(options.normalized(symbol.name), []).append(symbol)
    for key, group in by_name.items():
        if len(group) > 1:
            diagnostics.append(ParseDiagnostic(
                "SYMBOL_DUPLICATE_CANDIDATES", "warning",
                f"{len(group)} candidate declarations share name {group[0].name!r}; "
                "scope and actual identity are unknown", group[-1].span, "symbol_index",
            ))

    # Resource hints from ATLAS-1.4 are retained as typed *candidate* refs.
    resource_spans: dict[tuple[int, int], Token] = {}
    if options.resource_hints:
        operations = {op.statement_id: op for op in extraction.candidates}
        for i, tokens in enumerate(statement_tokens, 1):
            op = operations.get(f"stmt-{i:06d}")
            if not op:
                continue
            for res in op.resources:
                for t in tokens:
                    if (t.kind == TokenKind.IDENTIFIER and t.lexeme == res.reference_text
                            and t.span.end.offset == res.span.end.offset):
                        resource_spans[(i, t.span.start.offset)] = t
                        break

    references: list[ReferenceCandidate] = []
    links: list[CandidateRelationship] = []
    for i, statement in enumerate(parsed.statements, 1):
        tokens = statement_tokens[i - 1]
        head, _ = _head_and_body(statement)
        reserved_offsets = {(i, head.span.start.offset)} if head else set()
        # The only positions excluded are the structural header and actual
        # declaration name. Quoted literals and comments have no identifier tokens.
        for j, token in enumerate(tokens):
            if token.kind != TokenKind.IDENTIFIER:
                continue
            location = (i, token.span.start.offset)
            if location in reserved_offsets or location in definitions_by_location:
                continue
            kind: str | None = None
            recognition: str | None = None
            # The preceding token must be the configured introducer; optional
            # comma is accepted. Resource hints remain lower-priority.
            prior_ix = j - 1 if j == 0 or tokens[j - 1].lexeme != "," else j - 2
            prior = tokens[prior_ix] if prior_ix >= 0 else None
            if (prior is not None and prior.kind == TokenKind.IDENTIFIER
                    and prior.lexeme.casefold() in ref_heads):
                kind = ref_heads[prior.lexeme.casefold()]
                recognition = "opt_in_reference_introducer"
            elif location in resource_spans:
                kind = "resource"
                recognition = "operation_resource_hint"
            elif options.lexical_name_matches and options.normalized(token.lexeme) in by_name:
                recognition = "lexical_match_to_candidate_declaration"
            if recognition is None:
                continue
            matches = [s for s in by_name.get(options.normalized(token.lexeme), [])
                       if kind is None or s.kind == kind]
            resolution = ("unresolved" if not matches else
                          "unique_candidate" if len(matches) == 1 else "ambiguous")
            refs = tuple(s.symbol_id for s in matches)
            ref = ReferenceCandidate(
                reference_id=f"ref-{len(references)+1:06d}",
                statement_id=f"stmt-{i:06d}", name=token.lexeme,
                kind_hint=kind, span=token.span, recognition=recognition,
                resolution=resolution, target_symbol_ids=refs,
            )
            references.append(ref)
            if resolution == "unique_candidate":
                links.append(CandidateRelationship(ref.reference_id, ref.statement_id, refs[0]))

    return SymbolIndexResult(
        extraction=extraction, config=options, symbols=tuple(symbols),
        references=tuple(references), relationships=tuple(links),
        diagnostics=tuple(diagnostics),
    )


def index_source(
    source: str, *, source_name: str = "<memory>",
    symbol_config: SymbolConfig | None = None,
    extraction_config: ExtractionConfig | None = None,
    parse_config: ParseConfig | None = None, lexer_config: LexerConfig | None = None,
) -> SymbolIndexResult:
    return index_symbols(
        extract_source(source, source_name=source_name, extraction_config=extraction_config,
                       parse_config=parse_config, lexer_config=lexer_config),
        config=symbol_config,
    )


def index_file(
    path: Path, *, symbol_config: SymbolConfig | None = None,
    extraction_config: ExtractionConfig | None = None,
    parse_config: ParseConfig | None = None, lexer_config: LexerConfig | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> SymbolIndexResult:
    return index_symbols(
        extract_file(path, extraction_config=extraction_config, parse_config=parse_config,
                     lexer_config=lexer_config, max_bytes=max_bytes), config=symbol_config,
    )
