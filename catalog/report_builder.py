from __future__ import annotations

import json
from pathlib import Path

from .catalog_builder import build_catalog


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def build_report(
    project_root: Path,
    output_path: Path,
    extra_excludes: set[str] | None = None,
    use_gitignore: bool = True,
) -> Path:
    catalog = build_catalog(
        project_root=project_root,
        extra_excludes=extra_excludes,
        use_gitignore=use_gitignore,
    )

    template = (PACKAGE_ROOT / "templates" / "report.html").read_text(
        encoding="utf-8"
    )
    css = (PACKAGE_ROOT / "static" / "catalog.css").read_text(
        encoding="utf-8"
    )
    javascript = (PACKAGE_ROOT / "static" / "catalog.js").read_text(
        encoding="utf-8"
    )
    data = json.dumps(catalog.to_dict(), ensure_ascii=False).replace(
        "</", "<\\/"
    )

    html = (
        template.replace("/*__CATALOG_CSS__*/", css)
        .replace("/*__CATALOG_DATA__*/", data)
        .replace("/*__CATALOG_JS__*/", javascript)
    )

    output = output_path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
