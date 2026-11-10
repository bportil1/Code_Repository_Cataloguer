"""Source-preserving structural AST for conservative ATLAS inspection.

These nodes describe lexical structure, NOT validated IEEE 716 productions.
No node in this module asserts hardware/test semantics or a known ATLAS dialect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Union

from .tokens import LexDiagnostic, SourceSpan, Token

PARSE_SCHEMA = "cps.atlas.structural-ast@1"


@dataclass(frozen=True)
class TokenNode:
    token: Token

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "token", **self.token.to_dict()}


@dataclass(frozen=True)
class GroupNode:
    """A punctuation-delimited lexical group; no expression meaning implied."""

    opener: Token
    children: tuple[SyntaxElement, ...]
    closer: Token | None
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "group", "opener": self.opener.to_dict(),
            "closer": self.closer.to_dict() if self.closer else None,
            "complete": self.closer is not None,
            "span": asdict(self.span),
            "children": [item.to_dict() for item in self.children],
        }


SyntaxElement = Union[TokenNode, GroupNode]


@dataclass(frozen=True)
class StatementNode:
    """Delimited source envelope; always unclassified until a grammar exists."""

    text: str
    span: SourceSpan
    elements: tuple[SyntaxElement, ...]
    terminator: Token | None
    head_candidate: str | None
    numeric_prefix_candidate: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "unclassified_statement", "recognition": "structural_only",
            "text": self.text, "span": asdict(self.span),
            "terminated": self.terminator is not None,
            "terminator": self.terminator.to_dict() if self.terminator else None,
            "head_candidate": self.head_candidate,
            "numeric_prefix_candidate": self.numeric_prefix_candidate,
            "elements": [item.to_dict() for item in self.elements],
        }


@dataclass(frozen=True)
class ParseDiagnostic:
    code: str
    severity: str
    message: str
    span: SourceSpan
    phase: str = "structure"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParseResult:
    source_name: str
    source_length: int
    encoding_candidate: str | None
    statements: tuple[StatementNode, ...]
    trailing_text: str
    diagnostics: tuple[ParseDiagnostic, ...]
    terminators: tuple[str, ...]
    strict: bool
    token_count: int

    def to_source(self) -> str:
        """Reconstruct decoded source exactly, including all trivia and line endings."""
        return "".join(s.text for s in self.statements) + self.trailing_text

    def to_dict(self) -> dict[str, Any]:
        """JSON includes original source fragments; keep exports private."""
        errors = sum(d.severity == "error" for d in self.diagnostics)
        warnings = sum(d.severity == "warning" for d in self.diagnostics)
        return {
            "schema": PARSE_SCHEMA, "source_name": self.source_name,
            "source_length": self.source_length,
            "encoding_candidate": self.encoding_candidate,
            "configuration": {"terminators": list(self.terminators), "strict": self.strict},
            "statements": [s.to_dict() for s in self.statements],
            "trailing_text": self.trailing_text,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "summary": {
                "token_count": self.token_count,
                "statement_count": len(self.statements),
                "terminated_count": sum(s.terminator is not None for s in self.statements),
                "unterminated_count": sum(s.terminator is None for s in self.statements),
                "unclassified_count": len(self.statements),
                "grammar_recognized_count": 0,
                "error_count": errors, "warning_count": warnings,
                "source_roundtrip_complete": len(self.to_source()) == self.source_length,
            },
        }


def lexical_diagnostic(d: LexDiagnostic) -> ParseDiagnostic:
    return ParseDiagnostic(d.code, d.severity, d.message, d.span, "lexical")
