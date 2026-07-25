#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from catalog.report_builder import build_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a navigable HTML catalog for a Python repository."
    )
    parser.add_argument("project_root", type=Path)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("codebase_catalog_report.html"),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional file or directory name to exclude.",
    )
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Do not read ignore rules from the project root .gitignore.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = build_report(
        project_root=args.project_root,
        output_path=args.output,
        extra_excludes=set(args.exclude),
        use_gitignore=not args.no_gitignore,
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
