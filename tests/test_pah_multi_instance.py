"""MI-01 tests for the public, host-neutral process launch contract."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_analyzer.integrations.pah import CodeAnalyzerRuntimeAdapter
from code_analyzer.process_ui import configuration_from_environment, main


def test_adapter_uses_repository_resource_and_keeps_process_creation_with_host(tmp_path, monkeypatch):
    import code_analyzer.integrations.pah as integration
    monkeypatch.setattr(integration, "find_spec", lambda name: object())
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    adapter = CodeAnalyzerRuntimeAdapter()
    first = adapter.process_launch_spec(context=SimpleNamespace(project_root=repo_b, resources={"repository": repo_a}))
    second = adapter.process_launch_spec(context={"project_root": repo_b, "resources": {}})
    assert first == {
        "command": [sys.executable, "-m", "code_analyzer.process_ui"],
        "env": {"CODE_ANALYZER_INITIAL_REPOSITORY": str(repo_a.resolve())},
        "requested_port": 0, "ui_path": "/",
    }
    assert second["env"]["CODE_ANALYZER_INITIAL_REPOSITORY"] == str(repo_b.resolve())
    assert "PAH_MODULE_INSTANCE_ID" not in first["env"]
    assert "PAH_MODULE_PORT" not in first["env"]
    assert adapter.launch()["launched"] is False


def test_adapter_fails_closed_without_explicit_root_or_flask(monkeypatch, tmp_path):
    import code_analyzer.integrations.pah as integration
    monkeypatch.setattr(integration, "find_spec", lambda name: object())
    adapter = CodeAnalyzerRuntimeAdapter()
    with pytest.raises(ValueError, match="selected repository"):
        adapter.process_launch_spec(context={})
    with pytest.raises(FileNotFoundError):
        adapter.process_launch_spec(context={"project_root": tmp_path / "missing"})
    monkeypatch.setattr(integration, "find_spec", lambda name: None)
    with pytest.raises(RuntimeError, match="Flask"):
        adapter.process_launch_spec(context={"project_root": tmp_path})
    assert adapter.status(context={"project_root": tmp_path})["available"] is False


def _environment(tmp_path: Path, project_root: Path) -> dict[str, str]:
    return {
        "PAH_MODULE_INSTANCE_ID": "host:code_analyzer:one",
        "PAH_MODULE_RUNTIME_DIR": str(tmp_path),
        "PAH_MODULE_PORT": "39281",
        "CODE_ANALYZER_INITIAL_REPOSITORY": str(project_root),
    }


def test_process_environment_is_strictly_bound_and_loopback_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    values = _environment(tmp_path, repo)
    first = configuration_from_environment(values)
    assert first["host"] == "127.0.0.1"
    assert first["port"] == 39281
    assert first["project_root"] == repo.resolve()
    for key in values:
        invalid = dict(values)
        invalid.pop(key)
        with pytest.raises(RuntimeError):
            configuration_from_environment(invalid)
    for invalid_port in ["0", "65536", "garbage", "-1"]:
        with pytest.raises(RuntimeError, match="PORT"):
            configuration_from_environment({**values, "PAH_MODULE_PORT": invalid_port})
    linked = tmp_path / "linked_runtime"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="non-symlink"):
        configuration_from_environment({**values, "PAH_MODULE_RUNTIME_DIR": str(linked)})


def test_process_entry_calls_public_web_factory_no_debug_or_reloader(tmp_path, monkeypatch):
    import code_analyzer.process_ui as process_ui
    import types
    import sys

    repo = tmp_path / "repo"
    repo.mkdir()
    for key, value in _environment(tmp_path, repo).items():
        monkeypatch.setenv(key, value)
    recorded = []

    class FakeApp:
        def run(self, **kwargs):
            recorded.append(kwargs)

    fake_module = types.ModuleType("code_analyzer.web.app")
    fake_module.create_app = lambda root: (recorded.append(root), FakeApp())[1]
    monkeypatch.setitem(sys.modules, "code_analyzer.web.app", fake_module)
    assert process_ui.main() == 0
    assert recorded == [repo.resolve(), {"host": "127.0.0.1", "port": 39281,
                                        "debug": False, "use_reloader": False}]


def test_packaged_entrypoint_declared_and_runtime_outputs_ignored():
    import tomllib
    root = Path(__file__).parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["entry-points"]["pah.runtimes"]["code_analyzer"] == "code_analyzer.integrations.pah:CodeAnalyzerRuntimeAdapter"
    ignores = (root / ".gitignore").read_text()
    for pattern in ("/analysis/", "/.pah/", "/runtime/", "/scratch/", "*.db-wal"):
        assert pattern in ignores


def test_two_real_processes_keep_separate_repository_bindings(tmp_path):
    """Separate Python processes can bind to different source repositories."""
    import json
    import os
    import subprocess

    roots = [tmp_path / "repo_a", tmp_path / "repo_b"]
    runtimes = [tmp_path / "runtime_a", tmp_path / "runtime_b"]
    for root, runtime in zip(roots, runtimes):
        root.mkdir()
        runtime.mkdir()
        (root / "module.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    script = (
        "import json, os, time\n"
        "from code_analyzer.process_ui import configuration_from_environment\n"
        "from code_analyzer.api import CodeAnalyzer\n"
        "config = configuration_from_environment()\n"
        "analyzer = CodeAnalyzer(config['project_root'])\n"
        "print(json.dumps({'pid': os.getpid(), 'root': str(analyzer.project_root), "
        "'instance': config['instance_id']}), flush=True)\n"
        "time.sleep(4)\n"
    )
    children = []
    try:
        for index, (root, runtime) in enumerate(zip(roots, runtimes)):
            env = os.environ.copy()
            env.update(_environment(runtime, root))
            env["PAH_MODULE_INSTANCE_ID"] = f"host:code_analyzer:{index}"
            env["PAH_MODULE_PORT"] = str(39001 + index)
            children.append(subprocess.Popen(
                [sys.executable, "-c", script], cwd=Path(__file__).parents[1],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        snapshots = [json.loads(child.stdout.readline()) for child in children]
        assert len({entry["pid"] for entry in snapshots}) == 2
        assert {entry["root"] for entry in snapshots} == {str(root.resolve()) for root in roots}
        assert len({entry["instance"] for entry in snapshots}) == 2
        children[0].terminate()
        children[0].wait(timeout=5)
        assert children[1].poll() is None
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
