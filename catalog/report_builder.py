from __future__ import annotations

import json
from pathlib import Path

from .models import Catalog


def build_report(catalog: Catalog, output_path: Path, project_dir: Path) -> Path:
    template = (project_dir / "templates" / "catalog.html").read_text(encoding="utf-8")
    css = (project_dir / "static" / "catalog.css").read_text(encoding="utf-8")
    javascript = (project_dir / "static" / "catalog.js").read_text(encoding="utf-8")
    data = json.dumps(catalog.to_dict(), ensure_ascii=False).replace("</", "<\\/")

    rendered = (
        template.replace("/*__CATALOG_CSS__*/", css)
        .replace("//__CATALOG_DATA__", f"window.CODEBASE_CATALOG = {data};")
        .replace("//__CATALOG_JS__", javascript)
        .replace("__PROJECT_NAME__", catalog.project_name)
    )

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path
