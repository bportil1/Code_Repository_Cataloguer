"""Language-neutral lexical records with exact source text and source spans.

Offsets count Python Unicode code points, not UTF-8 bytes. Line/column are
one-based. Spans are half-open; end points refer to the position immediately
after a token. CRLF counts as one physical newline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

TOKEN_SCHEMA = "cps.atlas.token-stream@1"


class TokenKind(str, Enum):
    IDENTIFIER = "identifier"
    NUMBER = "number"
    STRING = "string"
    OPERATOR = "operator"
    PUNCTUATION = "punctuation"
    WHITESPACE = "whitespace"
    NEWLINE = "newline"
    COMMENT = "comment"
    UNKNOWN = "unknown"
    EOF = "eof"


@dataclass(frozen=True)
class SourcePosition:
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class SourceSpan:
    start: SourcePosition
    end: SourcePosition


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    lexeme: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "lexeme": self.lexeme, "span": asdict(self.span)}


@dataclass(frozen=True)
class LexDiagnostic:
    code: str
    severity: str
    message: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LexResult:
    source_name: str
    source_length: int
    tokens: tuple[Token, ...]
    diagnostics: tuple[LexDiagnostic, ...]
    encoding_candidate: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Export token lexemes verbatim: this output may contain private source."""
        return {
            "schema": TOKEN_SCHEMA,
            "source_name": self.source_name,
            "source_length": self.source_length,
            "encoding_candidate": self.encoding_candidate,
            "tokens": [t.to_dict() for t in self.tokens],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "summary": {
                "token_count": len(self.tokens),
                "error_count": sum(d.severity == "error" for d in self.diagnostics),
                "warning_count": sum(d.severity == "warning" for d in self.diagnostics),
                "contains_eof": bool(self.tokens and self.tokens[-1].kind == TokenKind.EOF),
            },
        }
