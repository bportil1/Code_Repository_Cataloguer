from __future__ import annotations
import ast, difflib, hashlib, json, os, stat, uuid
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
        self.journal_dir = self.state / "transactions"

    def catalog(self, refresh: bool = False):
        if refresh or self._catalog is None:
            self._catalog = self.catalog_factory()
        return self._catalog

    def _source_parent_fd(self, path: Path) -> tuple[int, str]:
        """Anchor every directory component to the project root (POSIX only).

        Do not trust Path.resolve() to detect a symlink substituted after a check.
        All returned descriptors must be closed by the caller.
        """
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise ValueError("Descriptor-safe source operations require POSIX O_NOFOLLOW")
        try:
            parts = path.relative_to(self.root).parts
        except ValueError as exc:
            raise ValueError("Refusing to access a path outside the project") from exc
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError("Refusing unsafe source path")
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in parts[:-1]:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = next_fd
            return directory, parts[-1]
        except (OSError, ValueError) as exc:
            os.close(directory)
            raise ValueError("Refusing unsafe source path or symlink") from exc

    def _read_source(self, path: Path) -> str:
        """Read a regular source file through verified descriptors only."""
        parent_fd, name = self._source_parent_fd(path)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size > 16 * 1024 * 1024:
                    raise ValueError("Source must be a regular file of at most 16 MiB")
                with os.fdopen(os.dup(fd), "rb") as handle:
                    raw = handle.read(16 * 1024 * 1024 + 1)
                after = os.fstat(fd)
                if len(raw) > 16 * 1024 * 1024 or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ValueError("Source changed during descriptor verification")
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
                    raise ValueError("Source replaced during descriptor verification")
                return raw.decode("utf-8", errors="replace")
            finally:
                os.close(fd)
        except OSError as exc:
            raise ValueError("Refusing unsafe source path or symlink") from exc
        finally:
            os.close(parent_fd)

    def _path(self, relative: str | None) -> Path:
        if not relative:
            raise ValueError("Missing project-relative path")
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Refusing to access a path outside the project")
        path = self.root / relative
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Refusing to access a path outside the project") from exc
        self._read_source(path)
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
        source_text = self._read_source(source_path)
        target_text = self._read_source(target_path)
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
        self._ensure_no_pending_transaction()
        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError("Plan is missing or expired; preview again")
        for change in plan.changes:
            current = self._read_source(change.path)
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
        record = {"backup_id": backup_id, "summary": plan.summary, "files": [c.relative_path for c in plan.changes],
                  "post_move_sha256": {c.relative_path: digest(c.updated_text) for c in plan.changes}}
        (backup_root / "metadata.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        # Do not publish history unless every source replacement succeeds.
        # A failed replacement is rolled back only when its content is still
        # exactly our own output; never overwrite a third-party concurrent edit.
        history = self._read_history()
        replacements = [(c.path, c.original_text, c.updated_text) for c in plan.changes]
        self._commit_replacements(replacements, lambda: self._write_history(history + [record]), history_after=history + [record])
        del self._plans[plan_id]
        cat = self.catalog(refresh=True)
        target_node = cat.nodes[plan.target_module_id]
        moved_id = next((cid for cid in target_node.children if cat.nodes[cid].node_type == "function" and cat.nodes[cid].name == plan.summary["function"]), None)
        return {"success": True, "message": f"Moved {plan.summary['function']} to {plan.summary['target']}", "selected_node_id": moved_id, "catalog": cat.to_dict()}

    def undo_last(self) -> dict:
        self._ensure_no_pending_transaction()
        history = self._read_history()
        if not history:
            raise ValueError("There is no applied move to undo")
        # Do not undo over edits made after the move. Older history entries that
        # lack post-move fingerprints cannot safely establish the expected state.
        record = history[-1]
        expected = record.get("post_move_sha256")
        files = record.get("files")
        if not isinstance(expected, dict) or not isinstance(files, list) or not files:
            raise ValueError("Undo history lacks post-move fingerprints; refusing to overwrite source")
        backup_root = self.backups / record["backup_id"]
        restores = []
        for rel in files:
            if not isinstance(rel, str) or rel not in expected:
                raise ValueError("Undo history has incomplete source fingerprints")
            # Reject symlink components before the existing containment check:
            # Path.resolve() itself erases the fact that a symlink was used.
            unresolved = self.root / rel
            if Path(rel).is_absolute() or ".." in Path(rel).parts or any(
                part.is_symlink() for part in (unresolved, *unresolved.parents)
                if part != self.root and self.root in part.parents
            ):
                raise ValueError(f"Refusing unsafe undo path: {rel}")
            path = self._path(rel)
            backup = backup_root / rel
            if not backup.is_file() or backup.is_symlink():
                raise ValueError(f"Backup file missing or unsafe: {rel}")
            original = backup.read_text(encoding="utf-8")
            current = self._read_source(path)
            if digest(current) != expected[rel]:
                raise ValueError(f"{rel} changed since the move; undo refused without writing files")
            restores.append((path, original))
        replacements = [(path, self._read_source(path), original)
                        for path, original in restores]
        # Recheck every source immediately before beginning the mutation.
        for path, current, _ in replacements:
            rel = path.relative_to(self.root).as_posix()
            if digest(current) != expected[rel]:
                raise ValueError(f"{rel} changed since the move; undo refused without writing files")
        self._commit_replacements(replacements, lambda: self._write_history(history[:-1]), history_after=history[:-1])
        cat = self.catalog(refresh=True)
        return {"success": True, "message": f"Undid move of {record['summary']['function']}", "catalog": cat.to_dict()}

    def _journal_path(self, transaction_id: str) -> Path:
        if not isinstance(transaction_id, str) or len(transaction_id) != 32 or any(c not in "0123456789abcdef" for c in transaction_id):
            raise ValueError("Invalid transaction identifier")
        return self.journal_dir / (transaction_id + ".json")

    def _write_journal(self, transaction_id: str, data: dict) -> None:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        path = self._journal_path(transaction_id)
        # Use exclusive creation and fsync: recovery must never confuse a
        # partial/overwritten journal with a valid pre-write record.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps(data, sort_keys=True).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            directory = os.open(self.journal_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try: os.fsync(directory)
            finally: os.close(directory)

    def _clear_journal(self, transaction_id: str) -> None:
        self._journal_path(transaction_id).unlink()
        directory = os.open(self.journal_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)

    def _pending_journal_files(self) -> list[Path]:
        if not self.journal_dir.exists():
            return []
        return sorted(self.journal_dir.iterdir())

    def pending_transactions(self) -> list[dict]:
        """Read-only reconciliation; never auto-restore a mutable source tree.

        'before' and 'after' are safe to reconcile, while anything else is a
        conflict requiring a human decision. Unknown/corrupt journals block edits.
        """
        reports = []
        for path in self._pending_journal_files():
            item = {"transaction_id": path.stem, "status": "manual_review", "files": []}
            try:
                if path.suffix != ".json" or path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
                    raise ValueError("Invalid transaction journal")
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("version") != 1 or record.get("transaction_id") != path.stem or not isinstance(record.get("changes"), list) or not record["changes"]:
                    raise ValueError("Invalid transaction journal contract")
                for change in record["changes"]:
                    rel = change["path"]
                    source = self._path(rel)
                    current = digest(self._read_source(source))
                    expected_before = digest(change["before"])
                    expected_after = change["after_sha256"]
                    if not isinstance(expected_after, str) or len(expected_after) != 64:
                        raise ValueError("Invalid expected source fingerprint")
                    state = "before" if current == expected_before else "after" if current == expected_after else "conflict"
                    item["files"].append({"path": rel, "state": state})
                states = [f["state"] for f in item["files"]]
                item["status"] = "unchanged" if all(s == "before" for s in states) else "written" if all(s == "after" for s in states) else "partial" if all(s in ("before", "after") for s in states) else "manual_review"
                history_hash = hashlib.sha256(self.history.read_bytes() if self.history.exists() else b"").hexdigest()
                item["history_state"] = "before" if history_hash == record.get("history_before_sha256") else "after" if history_hash == record.get("history_after_sha256") else "conflict"
            except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
                item["error"] = str(exc)
            reports.append(item)
        return reports

    def reconcile_transaction(self, transaction_id: str) -> str:
        """Explicit conflict-checked recovery. Never overwrite unknown edits.

        A transaction committed in history is finalized only when every file
        still equals its intended output. Otherwise, an unpublished transaction
        is rolled back only from known output bytes to known pre-write bytes.
        """
        target = next((x for x in self.pending_transactions() if x["transaction_id"] == transaction_id), None)
        if not target:
            raise ValueError("Transaction not found")
        if target.get("status") == "manual_review" or target.get("history_state") == "conflict":
            raise ValueError("Transaction requires manual recovery; sources or history changed")
        path = self._journal_path(transaction_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        if target["history_state"] == "after" and target["status"] == "written":
            self._clear_journal(transaction_id)
            return "committed"
        if target["history_state"] != "before":
            raise ValueError("Cannot roll back transaction after history publication")
        # Re-check each source immediately before restoring it, using the
        # existing descriptor-safe operations; keep the journal if any fails.
        for change in reversed(data["changes"]):
            source = self._path(change["path"])
            current = digest(self._read_source(source))
            if current == digest(change["before"]):
                continue
            if current != change["after_sha256"]:
                raise ValueError("Source changed since reconciliation; manual recovery required")
            self._atomic_write(source, change["before"])
        # Verify the complete pre-write state before journal retirement.
        if any(digest(self._read_source(self._path(c["path"]))) != digest(c["before"]) for c in data["changes"]):
            raise RuntimeError("Recovery incomplete; journal retained")
        self._clear_journal(transaction_id)
        return "rolled_back"

    def _ensure_no_pending_transaction(self) -> None:
        if self._pending_journal_files():
            raise ValueError("An unfinished source transaction requires reconciliation before another move")

    def _commit_replacements(self, replacements: list[tuple[Path, str, str]],
                             publish_history: Callable[[], None], *,
                             history_after: list[dict] | None = None) -> None:
        """Best-effort rollback with conflict protection, not an OS atomic transaction.

        The backups are already durable when called by apply(). An undo leaves
        its original backups and history intact until all restorations finish.
        """
        self._ensure_no_pending_transaction()
        transaction_id = uuid.uuid4().hex
        current_history_bytes = self.history.read_bytes() if self.history.exists() else b""
        # Empty/missing history is encoded differently from an existing history
        # file; calculate the exact output that the publisher will write.
        if history_after is None:
            raise ValueError("A planned history revision is required for durable transactions")
        intended_history = json.dumps(history_after, indent=2).encode("utf-8")
        record = {
            "version": 1, "transaction_id": transaction_id,
            "history_before_sha256": hashlib.sha256(current_history_bytes).hexdigest(),
            "history_after_sha256": hashlib.sha256(intended_history).hexdigest(),
            "changes": [{"path": path.relative_to(self.root).as_posix(), "before": before,
                         "after_sha256": digest(after)} for path, before, after in replacements],
        }
        self._write_journal(transaction_id, record)
        touched: list[tuple[Path, str, str]] = []
        try:
            for path, before, after in replacements:
                # Guard against modifications between the plan check and write.
                if digest(self._read_source(path)) != digest(before):
                    raise ValueError(f"{path.name} changed during source transaction")
                touched.append((path, before, after))
                self._atomic_write(path, after)
            publish_history()
            self._clear_journal(transaction_id)
        except Exception as exc:
            conflicts = []
            for path, before, after in reversed(touched):
                try:
                    current = self._read_source(path)
                    if digest(current) == digest(before):
                        continue  # failed before replacing this file
                    if digest(current) != digest(after):
                        conflicts.append(str(path))
                        continue  # someone else edited it; do not overwrite
                    self._atomic_write(path, before)
                except Exception as rollback_exc:
                    conflicts.append(f"{path}: {rollback_exc}")
            if conflicts:
                raise RuntimeError("Source transaction failed; rollback incomplete for: "
                                   + ", ".join(conflicts)) from exc
            # The journal must survive any uncertain history outcome.
            current_history_bytes = self.history.read_bytes() if self.history.exists() else b""
            if hashlib.sha256(current_history_bytes).hexdigest() == record["history_before_sha256"]:
                self._clear_journal(transaction_id)
            raise

    def _atomic_write(self, path: Path, text: str) -> None:
        """Replace by parent directory descriptor, never following source symlinks.

        This prevents path traversal and target symlink following. It is *not*
        a compare-and-swap primitive: uncooperative concurrent writers can
        still change a directory entry between validation and replacement.
        """
        parent_fd, name = self._source_parent_fd(path)
        temp_name = "." + name + "." + uuid.uuid4().hex + ".tmp"
        fd = None
        try:
            try:
                previous = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISREG(previous.st_mode):
                    raise ValueError("Refusing to replace nonregular file or symlink")
            except FileNotFoundError:
                previous = None
            fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                latest = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if previous is None or (latest.st_dev, latest.st_ino, latest.st_mtime_ns, latest.st_ctime_ns, latest.st_size) != (previous.st_dev, previous.st_ino, previous.st_mtime_ns, previous.st_ctime_ns, previous.st_size):
                    raise ValueError("Source replaced during write preparation")
            except FileNotFoundError:
                if previous is not None:
                    raise ValueError("Source removed during write preparation")
            os.replace(temp_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)

    def _read_history(self) -> list[dict]:
        if not self.history.exists(): return []
        try: return json.loads(self.history.read_text(encoding="utf-8"))
        except json.JSONDecodeError: return []

    def _write_history(self, value: list[dict]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.history, json.dumps(value, indent=2))
