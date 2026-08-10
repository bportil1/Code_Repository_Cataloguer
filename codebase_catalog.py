#!/usr/bin/env python3
"""Backward-compatible standalone HTML-report command."""

from code_analyzer.cli import main, parse_args

__all__ = ["main", "parse_args"]


if __name__ == "__main__":
    main()
