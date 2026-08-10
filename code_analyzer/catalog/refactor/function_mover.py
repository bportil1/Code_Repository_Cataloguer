from __future__ import annotations
import ast, difflib, hashlib, json, os, tempfile, uuid
from datetime import datetime
from pathlib import Path
from typing import Callable
from .change_plan import ChangePlan, FileChange


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_ok(text: str, filename: str) -> None:
    try:
        ast.parse(text, filename=filename)
    except SyntaxError as exc:
        raise ValueError(f"{filename} would be invalid Python: {exc.msg} at line {exc.lineno}") from exc


class FunctionMoveService:
    def __init__(self, project_root: Path, catalog_factory: Callable):
        self.root = project_root.resolve()
        self.catalog_factory = catalog_factory
        self._catalog = None
        self._plans: dict[str, ChangePlan] = {}
        self.state = self.root / ".codebase_catalog"
        self.backups = self.state / "backups"
        self.history = self.state / "history.json"

    def catalog(self, refresh: bool = False):
        if refresh or self._catalog is None:
            self._catalog = self.catalog_factory()
        return self._catalog

    def _path(self, relative: str | None) -> Path:
        if not relative:
            raise ValueError("Missing project-relative path")
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Refusing to access a path outside the project") from exc
        if not path.is_file():
            raise ValueError(f"File not found: {relative}")
        return path

    def preview(self, function_id: str, target_module_id: str) -> ChangePlan:
        cat = self.catalog(refresh=True)
        fn = cat.nodes.get(function_id)
        target = cat.nodes.get(target_module_id)
        if not fn or fn.node_type != "function":
            raise ValueError("Only indexed top-level functions can be moved")
        if not target or target.node_type != "module":
            raise ValueError("Target must be an existing Python module")
        source = cat.nodes.get(fn.parent_id or "")
        if not source or source.node_type != "module":
            raise ValueError("Selected function has no valid source module")
        if source.id == target.id:
            raise ValueError("Function is already in the selected target module")

        source_path, target_path = self._path(fn.path), self._path(target.path)
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        target_text = target_path.read_text(encoding="utf-8", errors="replace")
        meta = fn.metadata or {}
        start, end = int(meta.get("line_start", 0)), int(meta.get("line_end", 0))
        block = str(meta.get("source_code", "")).rstrip()
        if start < 1 or end < start or not block:
            raise ValueError("Function source range is unavailable or stale")

        target_tree = ast.parse(target_text, filename=str(target_path))
        names = {n.name for n in target_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        if fn.name in names:
            raise ValueError(f"{target.path} already contains a top-level definition named {fn.name}")

        lines = source_text.splitlines(keepends=True)
        if end > len(lines):
            raise ValueError("Indexed source range is stale; reload and try again")
        left = start - 1
        while left > 0 and not lines[left - 1].strip():
            left -= 1
            break
        right = end
        while right < len(lines) and not lines[right].strip():
            right += 1
        new_source = "".join(lines[:left] + lines[right:]).rstrip()
        new_source = (new_source + "\n") if new_source else ""
        new_target = target_text.rstrip() + ("\n\n\n" if target_text.strip() else "") + block + "\n"
        parse_ok(new_source, str(source_path))
        parse_ok(new_target, str(target_path))

        warnings = []
        importers = []
        for module in cat.modules:
            for imp in module.imports:
                if imp.module == (source.qualified_name or "") and fn.name in imp.names:
                    importers.append(module.path)
        if importers:
            warnings.append("Direct imports still need updating in: " + ", ".join(sorted(set(importers))))

        changes = [
            self._change(source_path, source_text, new_source),
            self._change(target_path, target_text, new_target),
        ]
        plan = ChangePlan(
            id="move-" + uuid.uuid4().hex,
            function_id=function_id,
            target_module_id=target_module_id,
            summary={"function": fn.name, "source": source.path, "target": target.path, "files_changed": 2},
            changes=changes,
            warnings=warnings,
        )
        self._plans[plan.id] = plan
        return plan

    def _change(self, path: Path, before: str, after: str) -> FileChange:
        rel = path.relative_to(self.root).as_posix()
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile="a/"+rel, tofile="b/"+rel))
        return FileChange(path, rel, before, after, digest(before), diff)

    def apply(self, plan_id: str) -> dict:
        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError("Plan is missing or expired; preview again")
        for change in plan.changes:
            current = change.path.read_text(encoding="utf-8", errors="replace")
            if digest(current) != change.original_hash:
                raise ValueError(f"{change.relative_path} changed after preview; no files were written")
            parse_ok(change.updated_text, str(change.path))

        backup_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_root = self.backups / backup_id
        backup_root.mkdir(parents=True)
        for change in plan.changes:
            b = backup_root / change.relative_path
            b.parent.mkdir(parents=True, exist_ok=True)
            b.write_text(change.original_text, encoding="utf-8")
        record = {"backup_id": backup_id, "summary": plan.summary, "files": [c.relative_path for c in plan.changes]}
        (backup_root / "metadata.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        for change in plan.changes:
            self._atomic_write(change.path, change.updated_text)
        history = self._read_history(); history.append(record); self._write_history(history)
        del self._plans[plan_id]
        cat = self.catalog(refresh=True)
        target_node = cat.nodes[plan.target_module_id]
        moved_id = next((cid for cid in target_node.children if cat.nodes[cid].node_type == "function" and cat.nodes[cid].name == plan.summary["function"]), None)
        return {"success": True, "message": f"Moved {plan.summary['function']} to {plan.summary['target']}", "selected_node_id": moved_id, "catalog": cat.to_dict()}

    def undo_last(self) -> dict:
        history = self._read_history()
        if not history:
            raise ValueError("There is no applied move to undo")
        record = history.pop(); backup_root = self.backups / record["backup_id"]
        for rel in record["files"]:
            backup = backup_root / rel
            if not backup.exists():
                raise ValueError(f"Backup file missing: {rel}")
            self._atomic_write((self.root / rel).resolve(), backup.read_text(encoding="utf-8"))
        self._write_history(history)
        cat = self.catalog(refresh=True)
        return {"success": True, "message": f"Undid move of {record['summary']['function']}", "catalog": cat.to_dict()}

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        fd, temp = tempfile.mkstemp(prefix="."+path.name+".", suffix=".tmp", dir=path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, path)
        except Exception:
            try: os.unlink(temp)
            except FileNotFoundError: pass
            raise

    def _read_history(self) -> list[dict]:
        if not self.history.exists(): return []
        try: return json.loads(self.history.read_text(encoding="utf-8"))
        except json.JSONDecodeError: return []

    def _write_history(self, value: list[dict]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        self.history.write_text(json.dumps(value, indent=2), encoding="utf-8")
