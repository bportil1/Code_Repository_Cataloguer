#!/usr/bin/env python3
"""Backward-compatible launcher for the standalone Flask analyzer UI."""

from code_analyzer.web.app import create_app, main

__all__ = ["create_app", "main"]


if __name__ == "__main__":
    main()
