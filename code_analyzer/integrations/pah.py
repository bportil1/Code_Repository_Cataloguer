"""Dependency-free PAH runtime adapter for independent Code Analyzer processes.

The host owns child process supervision, ports, and lifecycle. Code Analyzer
owns repository selection, analysis, source-index caches and source changes.
Neither the adapter nor the core scientific code imports PAH packages.
"""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import sys
from typing import Any, Mapping


def _value(context: Any, name: str) -> Any:
    if isinstance(context, Mapping):
        return context.get(name)
    return getattr(context, name, None)


def _selected_repository(context: Any) -> Path:
    """Use the explicit repository binding, never the supervisor's cwd.

    A research workspace's repository resource is authoritative when provided;
    `project_root` is the compatibility fallback for older PAH contexts.
    """
    resources = _value(context, "resources")
    root = resources.get("repository") if isinstance(resources, Mapping) else None
    if root is None:
        root = _value(context, "project_root")
    if root is None or not str(root).strip():
        raise ValueError("Code Analyzer requires a selected repository resource or project_root")
    path = Path(root).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"Code Analyzer repository is not a directory: {path}")
    return path


class CodeAnalyzerRuntimeAdapter:
    module_id = "code_analyzer"

    def status(self, *, context: Any = None) -> dict[str, Any]:
        available = find_spec("flask") is not None
        try:
            root = _selected_repository(context)
            error = None
        except (OSError, ValueError) as exc:
            root = None
            error = str(exc)
        return {
            "module_id": self.module_id,
            "available": available,
            "running": False,  # PAH tracks independently launched children.
            "launchable": available and root is not None,
            "presentation": "module_process",
            "message": error if error else (
                "Use PAH Instances to open a separate Code Analyzer window."
                if available else "Standalone Code Analyzer UI requires Flask."
            ),
        }

    def launch(self, *, context: Any = None, detached: bool = False) -> dict[str, Any]:
        """Do not create untracked children via the obsolete module-type path.

        The standalone CLI and PAH's pre-existing hosted Analysis surface stay
        available; individually managed children launch via process_launch_spec.
        """
        return {
            "module_id": self.module_id,
            "launched": False,
            "message": "Use New Instance in PAH Instances, or the existing Analysis surface.",
        }

    def shutdown(self, *, context: Any = None) -> None:
        # PAH's supervisor stops processes by their unique instance identity.
        return None

    def process_launch_spec(self, *, context: Any = None) -> dict[str, Any]:
        if find_spec("flask") is None:
            raise RuntimeError("Independent Code Analyzer UI requires Flask (install the 'web' extra)")
        root = _selected_repository(context)
        return {
            "command": [sys.executable, "-m", "code_analyzer.process_ui"],
            "env": {"CODE_ANALYZER_INITIAL_REPOSITORY": str(root)},
            "requested_port": 0,
            "ui_path": "/",
        }
