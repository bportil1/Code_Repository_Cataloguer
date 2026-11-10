"""ATLAS-1.2: conservative source-preserving lexical analysis.

This is a scanner, **not an IEEE 716 grammar**. Identifier spelling,
termination rules and comment markers are dialect-dependent; the scanner
makes no semantic interpretation or claim of language conformance. Comments
are recognized ONLY when the caller explicitly supplies their delimiters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from .reconnaissance import DEFAULT_MAX_BYTES, _decode_source
from .tokens import (
    LexDiagnostic,
    LexResult,
    SourcePosition,
    SourceSpan,
    Token,
    TokenKind,
)

_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_TWO_CHAR_OPS = frozenset({"<=", ">=", "==", "!=", "<>", ":=", "->", "=>", "**", "&&", "||", "::", "..", "+=", "-=", "*=", "/="})
_OPERATORS = frozenset("+-*/=<>!&|^~%")
_PUNCTUATION = frozenset(".,:;()[]{}$#@?\\")
_TRIVIA = frozenset({TokenKind.NEWLINE, TokenKind.WHITESPACE, TokenKind.COMMENT})


@dataclass(frozen=True)
class LexerConfig:
    """Optional, user-specified comment/quoting rules, NOT a dialect claim."""

    line_comments: tuple[str, ...] = ()
    block_comments: tuple[tuple[str, str], ...] = ()
    doubled_quote_escape: bool = True
    backslash_quote_escape: bool = False

    def __post_init__(self) -> None:
        for value in self.line_comments:
            self._check_marker(value)
        for pair in self.block_comments:
            if len(pair) != 2:
                raise ValueError("block comment requires (start, end) markers")
            self._check_marker(pair[0])
            self._check_marker(pair[1])
        starts = list(self.line_comments) + [x[0] for x in self.block_comments]
        if len(starts) != len(set(starts)):
            raise ValueError("comment start markers must be distinct")

    @staticmethod
    def _check_marker(value: str) -> None:
        if not value or any(ch in "\r\n" for ch in value):
            raise ValueError("comment markers must be nonempty and single-line")
        if value[0] in ("'", '"'):
            raise ValueError("comment start/end must not begin with a quote")


class _Scanner:
    def __init__(self, source: str, config: LexerConfig):
        self.source = source
        self.config = config
        self.index = 0
        self.line = 1
        self.column = 1
        self.tokens: list[Token] = []
        self.diagnostics: list[LexDiagnostic] = []
        # Prefer longest marker, so overlaps like '/' and '/*' are predictable.
        markers = [(x, None) for x in config.line_comments]
        markers += [(a, b) for a, b in config.block_comments]
        self.markers = sorted(markers, key=lambda x: (-len(x[0]), x[0]))

    def pos(self) -> SourcePosition:
        return SourcePosition(self.index, self.line, self.column)

    def take(self, target: int) -> None:
        """Advance to an absolute code-point offset, respecting CRLF."""
        if target <= self.index or target > len(self.source):
            raise ValueError("invalid scanner advance")
        while self.index < target:
            ch = self.source[self.index]
            if ch == "\r" and self.index + 1 < target and self.source[self.index + 1] == "\n":
                self.index += 2
                self.line += 1
                self.column = 1
            elif ch in "\r\n":
                self.index += 1
                self.line += 1
                self.column = 1
            else:
                self.index += 1
                self.column += 1

    def emit(self, kind: TokenKind, end: int, *, code: str = "", message: str = "", severity: str = "error") -> None:
        start = self.pos()
        lexeme = self.source[self.index:end]
        self.take(end)
        span = SourceSpan(start, self.pos())
        self.tokens.append(Token(kind, lexeme, span))
        if code:
            self.diagnostics.append(LexDiagnostic(code, severity, message, span))

    def scan(self) -> None:
        text = self.source
        size = len(text)
        while self.index < size:
            i = self.index
            ch = text[i]
            matched = next(((a, b) for a, b in self.markers if text.startswith(a, i)), None)
            if matched:
                opener, closer = matched
                if closer is None:
                    end = i + len(opener)
                    while end < size and text[end] not in "\r\n":
                        end += 1
                    self.emit(TokenKind.COMMENT, end)
                else:
                    close_at = text.find(closer, i + len(opener))
                    if close_at == -1:
                        self.emit(TokenKind.COMMENT, size, code="LEX_UNTERMINATED_BLOCK_COMMENT",
                                  message=f"block comment is missing closing {closer!r}")
                    else:
                        self.emit(TokenKind.COMMENT, close_at + len(closer))
                continue
            if ch in "\r\n":
                self.emit(TokenKind.NEWLINE, i + (2 if ch == "\r" and text[i:i+2] == "\r\n" else 1))
                continue
            if ch.isspace():
                end = i + 1
                while end < size and text[end].isspace() and text[end] not in "\r\n":
                    end += 1
                self.emit(TokenKind.WHITESPACE, end)
                continue
            if ch in ("'", '"'):
                end = i + 1
                closed = False
                while end < size:
                    if text[end] in "\r\n":
                        break  # recover on next source line
                    if (self.config.backslash_quote_escape and text[end] == "\\"
                            and end + 1 < size and text[end + 1] == ch):
                        end += 2
                        continue
                    if text[end] == ch:
                        if (self.config.doubled_quote_escape and end + 1 < size
                                and text[end + 1] == ch):
                            end += 2
                        else:
                            end += 1
                            closed = True
                            break
                    else:
                        end += 1
                if closed:
                    self.emit(TokenKind.STRING, end)
                else:
                    self.emit(TokenKind.STRING, end, code="LEX_UNTERMINATED_STRING",
                              message="quoted literal was not terminated before end of line")
                continue
            number = _NUMBER.match(text, i) if (ch.isascii() and ch.isdigit()) or (ch == "." and i + 1 < size and text[i+1].isascii() and text[i+1].isdigit()) else None
            if number:
                self.emit(TokenKind.NUMBER, number.end())
                continue
            if ch.isalpha() or ch == "_":
                end = i + 1
                while end < size and (text[end].isalnum() or text[end] == "_"):
                    end += 1
                self.emit(TokenKind.IDENTIFIER, end)
                continue
            pair = text[i:i+2]
            if pair in _TWO_CHAR_OPS:
                self.emit(TokenKind.OPERATOR, i + 2)
                continue
            if ch in _OPERATORS:
                self.emit(TokenKind.OPERATOR, i + 1)
                continue
            if ch in _PUNCTUATION:
                self.emit(TokenKind.PUNCTUATION, i + 1)
                continue
            self.emit(TokenKind.UNKNOWN, i + 1, code="LEX_UNKNOWN_CHARACTER",
                      severity="warning", message=f"unclassified code point U+{ord(ch):04X}")
        at_end = self.pos()
        self.tokens.append(Token(TokenKind.EOF, "", SourceSpan(at_end, at_end)))


def lex_source(
    source: str, *, source_name: str = "<memory>", config: LexerConfig | None = None,
    include_trivia: bool = True,
) -> LexResult:
    """Lex in-memory text without I/O, execution, or ATLAS grammar assumptions."""
    lexer = _Scanner(source, config or LexerConfig())
    lexer.scan()
    tokens = tuple(lexer.tokens if include_trivia else (t for t in lexer.tokens if t.kind not in _TRIVIA))
    return LexResult(source_name, len(source), tokens, tuple(lexer.diagnostics))


def lex_file(
    path: Path, *, config: LexerConfig | None = None,
    include_trivia: bool = True, max_bytes: int = DEFAULT_MAX_BYTES,
) -> LexResult:
    """Read a regular source file locally, with a bounded binary read."""
    path = Path(path).expanduser()
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"source is not a regular non-symlink file: {path}")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"source exceeds max_bytes={max_bytes}: {path}")
    decoded, encoding = _decode_source(raw)
    return replace(lex_source(decoded, source_name=str(path), config=config,
                              include_trivia=include_trivia), encoding_candidate=encoding)
