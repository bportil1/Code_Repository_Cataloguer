"""Standalone Code Analyzer process under a generic local supervisor.

This entry point does not import PAH. The supervisor provides an opaque
instance ID, writable runtime directory and loopback port through environment
variables; the repository and its analysis state stay owned by Code Analyzer.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def configuration_from_environment(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environment is None else environment
    instance_id = str(values.get("PAH_MODULE_INSTANCE_ID", "")).strip()
    if not instance_id or any(char in instance_id for char in "\r\n\0"):
        raise RuntimeError("PAH_MODULE_INSTANCE_ID must be a nonempty opaque ID")

    raw_runtime = str(values.get("PAH_MODULE_RUNTIME_DIR", "")).strip()
    if not raw_runtime:
        raise RuntimeError("PAH_MODULE_RUNTIME_DIR is required")
    raw_runtime_path = Path(raw_runtime).expanduser()
    if raw_runtime_path.is_symlink() or not raw_runtime_path.is_dir():
        raise RuntimeError("PAH_MODULE_RUNTIME_DIR must be an existing, non-symlink directory")
    runtime_dir = raw_runtime_path.resolve(strict=True)

    raw_port = str(values.get("PAH_MODULE_PORT", "")).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError("PAH_MODULE_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PAH_MODULE_PORT must be between 1 and 65535")

    raw_root = str(values.get("CODE_ANALYZER_INITIAL_REPOSITORY", "")).strip()
    if not raw_root:
        raise RuntimeError("CODE_ANALYZER_INITIAL_REPOSITORY is required")
    try:
        project_root = Path(raw_root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("CODE_ANALYZER_INITIAL_REPOSITORY does not exist") from exc
    if not project_root.is_dir():
        raise RuntimeError("CODE_ANALYZER_INITIAL_REPOSITORY must be a directory")

    return {
        "instance_id": instance_id,
        "runtime_dir": runtime_dir,
        "project_root": project_root,
        "port": port,
        "host": "127.0.0.1",  # never expose a source-editing UI on the LAN
    }


def main() -> int:
    config = configuration_from_environment()
    from code_analyzer.web.app import create_app

    app = create_app(config["project_root"])
    app.run(host=config["host"], port=config["port"], debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
