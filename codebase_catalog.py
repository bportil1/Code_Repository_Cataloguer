from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from catalog import build_catalog, build_report, index_python_files, scan_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a self-contained interactive HTML catalog of a Python codebase."
    )
    parser.add_argument("project", type=Path, help="Project directory to catalog")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("codebase_catalog.html"),
        help="Output HTML file (default: codebase_catalog.html)",
    )
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="NAME",
        help="Additional directory or file name to exclude; may be repeated",
    )
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Do not apply rules from the project root .gitignore",
    )
    parser.add_argument("--open", action="store_true", help="Open the generated report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent

    scan = scan_project(
        args.project, set(args.exclude), use_gitignore=not args.no_gitignore
    )
    modules = index_python_files(scan)
    catalog = build_catalog(scan, modules)
    output = build_report(catalog, args.output, project_dir)

    print(f"Cataloged {catalog.summary.python_files} Python files.")
    if scan.gitignore_path is not None:
        print(f"Applied ignore rules from: {scan.gitignore_path}")
    print(f"Report written to: {output}")
    if args.open:
        webbrowser.open(output.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
