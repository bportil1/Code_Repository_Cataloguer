"""ATLAS-1.3 structural envelopes and punctuation groups, not ATLAS grammar.

Source spans and raw statement text are preserved. A terminator is an explicit
user-selected SINGLE lexer punctuation/operator token, '$' by default. The
parser does not infer declarations, procedures, hardware meaning, or dialect.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ast import (
    GroupNode, ParseDiagnostic, ParseResult, StatementNode, SyntaxElement,
    TokenNode, lexical_diagnostic,
)
from .lexer import LexerConfig, lex_file, lex_source
from .reconnaissance import DEFAULT_MAX_BYTES
from .tokens import LexResult, SourceSpan, Token, TokenKind

_TRIVIA = frozenset((TokenKind.WHITESPACE, TokenKind.NEWLINE, TokenKind.COMMENT))
_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = frozenset(_OPEN.values())


@dataclass(frozen=True)
class ParseConfig:
    """Configurable statement delimiter; NOT a claim about standard ATLAS."""

    terminators: tuple[str, ...] = ("$",)
    strict: bool = False

    def __post_init__(self) -> None:
        if not self.terminators or len(set(self.terminators)) != len(self.terminators):
            raise ValueError("terminators must be a nonempty tuple of distinct tokens")
        for terminator in self.terminators:
            if not isinstance(terminator, str) or not terminator:
                raise ValueError("terminators must be nonempty strings")
            result = lex_source(terminator)
            found = result.tokens[:-1]
            if (len(found) != 1 or found[0].lexeme != terminator
                    or found[0].kind not in (TokenKind.OPERATOR, TokenKind.PUNCTUATION)):
                raise ValueError(f"terminator must be one lexer punctuation/operator token: {terminator!r}")


def _head_candidates(body: tuple[Token, ...]) -> tuple[str | None, str | None]:
    significant = [t for t in body if t.kind not in _TRIVIA]
    if not significant:
        return None, None
    first = significant[0]
    if first.kind == TokenKind.IDENTIFIER:
        return first.lexeme, None
    if (first.kind == TokenKind.NUMBER and len(significant) > 1
            and significant[1].kind == TokenKind.IDENTIFIER):
        # Mere candidate, not a confirmed ATLAS statement number.
        return significant[1].lexeme, first.lexeme
    return None, None


def _groups(
    body: tuple[Token, ...], *, strict: bool,
) -> tuple[tuple[SyntaxElement, ...], list[ParseDiagnostic]]:
    """Build a balanced punctuation tree, recovering within each statement."""
    root: list[SyntaxElement] = []
    # Each frame: opener, children, expected closing symbol.
    stack: list[tuple[Token, list[SyntaxElement], str]] = []
    diagnostics: list[ParseDiagnostic] = []
    severity = "error" if strict else "warning"

    def current() -> list[SyntaxElement]:
        return stack[-1][1] if stack else root

    for token in body:
        if token.kind == TokenKind.PUNCTUATION and token.lexeme in _OPEN:
            stack.append((token, [], _OPEN[token.lexeme]))
        elif token.kind == TokenKind.PUNCTUATION and token.lexeme in _CLOSE:
            if stack and stack[-1][2] == token.lexeme:
                opener, children, _ = stack.pop()
                current().append(GroupNode(opener, tuple(children), token,
                                           SourceSpan(opener.span.start, token.span.end)))
            else:
                diagnostics.append(ParseDiagnostic(
                    "PARSE_UNMATCHED_CLOSER", severity,
                    f"unexpected closing delimiter {token.lexeme!r}", token.span,
                ))
                current().append(TokenNode(token))
        else:
            current().append(TokenNode(token))

    end = body[-1].span.end if body else None
    while stack:
        opener, children, expected = stack.pop()
        diagnostics.append(ParseDiagnostic(
            "PARSE_UNCLOSED_GROUP", severity,
            f"opening delimiter {opener.lexeme!r} has no matching {expected!r}",
            opener.span,
        ))
        current().append(GroupNode(opener, tuple(children), None,
                                   SourceSpan(opener.span.start, end or opener.span.end)))
    return tuple(root), diagnostics


def parse_tokens(tokens: LexResult, *, config: ParseConfig | None = None) -> ParseResult:
    """Parse a lossless LexResult; filtered token streams are intentionally rejected."""
    options = config or ParseConfig()
    if not tokens.tokens or tokens.tokens[-1].kind != TokenKind.EOF:
        raise ValueError("parser needs one final EOF token")
    cursor = 0
    for token in tokens.tokens[:-1]:
        if token.kind == TokenKind.EOF or token.span.start.offset != cursor:
            raise ValueError("parser requires a complete contiguous token stream (include_trivia=True)")
        cursor = token.span.end.offset
    eof = tokens.tokens[-1]
    if (cursor != tokens.source_length or eof.span.start.offset != cursor
            or eof.span.end.offset != cursor):
        raise ValueError("token offsets do not span the complete decoded source")

    statements: list[StatementNode] = []
    diagnostics = [lexical_diagnostic(d) for d in tokens.diagnostics]
    pending: list[Token] = []
    # All source text comes from the full token stream, including comments.
    terminators = frozenset(options.terminators)

    def add_statement(items: list[Token], terminator: Token | None) -> None:
        body = tuple(items[:-1] if terminator else items)
        elements, problems = _groups(body, strict=options.strict)
        diagnostics.extend(problems)
        head, numeric = _head_candidates(body)
        statements.append(StatementNode(
            text="".join(t.lexeme for t in items),
            span=SourceSpan(items[0].span.start, items[-1].span.end),
            elements=elements, terminator=terminator,
            head_candidate=head, numeric_prefix_candidate=numeric,
        ))

    for token in tokens.tokens[:-1]:
        pending.append(token)
        if token.kind in (TokenKind.PUNCTUATION, TokenKind.OPERATOR) and token.lexeme in terminators:
            # A terminator wins even after a malformed group: this recovers
            # the next statement. A '$' in a quoted/comment token never splits.
            add_statement(pending, token)
            pending = []

    if pending:
        if any(t.kind not in _TRIVIA for t in pending):
            add_statement(pending, None)
            start = next(t for t in pending if t.kind not in _TRIVIA)
            diagnostics.append(ParseDiagnostic(
                "PARSE_UNTERMINATED_STATEMENT", "error" if options.strict else "warning",
                "source ended before a configured statement terminator", start.span,
            ))
            trailing_text = ""
        else:
            trailing_text = "".join(t.lexeme for t in pending)
    else:
        trailing_text = ""

    result = ParseResult(
        source_name=tokens.source_name, source_length=tokens.source_length,
        encoding_candidate=tokens.encoding_candidate,
        statements=tuple(statements), trailing_text=trailing_text,
        diagnostics=tuple(diagnostics), terminators=options.terminators,
        strict=options.strict, token_count=len(tokens.tokens),
    )
    if len(result.to_source()) != tokens.source_length:
        raise ValueError("source reconstruction failed: incomplete input token stream")
    return result


def parse_source(
    source: str, *, source_name: str = "<memory>",
    config: ParseConfig | None = None, lexer_config: LexerConfig | None = None,
) -> ParseResult:
    return parse_tokens(lex_source(source, source_name=source_name,
                                   config=lexer_config, include_trivia=True), config=config)


def parse_file(
    path: Path, *, config: ParseConfig | None = None,
    lexer_config: LexerConfig | None = None, max_bytes: int = DEFAULT_MAX_BYTES,
) -> ParseResult:
    return parse_tokens(lex_file(path, config=lexer_config,
                                  include_trivia=True, max_bytes=max_bytes), config=config)
