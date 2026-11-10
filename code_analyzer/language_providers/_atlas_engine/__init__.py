"""ATLAS frontend: inventory, lexer and conservative structural parser."""

from .analysis import AnalysisConfig, AnalysisResult, GraphNode, GraphEdge, analyze_file, analyze_source
from .ast import GroupNode, ParseDiagnostic, ParseResult, StatementNode, TokenNode
from .lexer import LexerConfig, lex_file, lex_source
from .operations import (
    ExtractionConfig, OperationExtractionResult, OperationCandidate,
    ArgumentCandidate, QuantityCandidate, ResourceCandidate, ComparisonCandidate,
    extract_operations, extract_source, extract_file,
)
from .parser import ParseConfig, parse_file, parse_source, parse_tokens
from .semantics import (
    SymbolConfig, SymbolCandidate, ReferenceCandidate, CandidateRelationship,
    SymbolIndexResult, index_symbols, index_source, index_file,
)
from .validation import validate_source, validate_file, validate_corpus, VALIDATION_SCHEMA, CORPUS_SCHEMA
from .tokens import LexDiagnostic, LexResult, SourcePosition, SourceSpan, Token, TokenKind

__all__ = [
    "AnalysisConfig", "AnalysisResult", "GraphNode", "GraphEdge", "analyze_file", "analyze_source",
    "validate_source", "validate_file", "validate_corpus", "VALIDATION_SCHEMA", "CORPUS_SCHEMA",
    "LexerConfig", "lex_file", "lex_source", "LexDiagnostic", "LexResult",
    "SourcePosition", "SourceSpan", "Token", "TokenKind", "ParseConfig",
    "parse_file", "parse_source", "parse_tokens", "ParseResult", "ParseDiagnostic",
    "StatementNode", "GroupNode", "TokenNode",
    "ExtractionConfig", "OperationExtractionResult", "OperationCandidate",
    "ArgumentCandidate", "QuantityCandidate", "ResourceCandidate", "ComparisonCandidate",
    "extract_operations", "extract_source", "extract_file",
    "SymbolConfig", "SymbolCandidate", "ReferenceCandidate", "CandidateRelationship",
    "SymbolIndexResult", "index_symbols", "index_source", "index_file",
]
