from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterable

from code_analyzer.catalog.catalog_builder import build_catalog
from code_analyzer.catalog.refactor.function_mover import FunctionMoveService


@dataclass
class RepositorySession:
    root: Path
    service: FunctionMoveService
    opened_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def public_dict(self) -> dict:
        return {
            "project_root": str(self.root),
            "project_name": self.root.name,
            "opened_at": self.opened_at,
        }


class RepositorySessionManager:
    """Own the currently analyzed repository and its repository-scoped services."""

    def __init__(
        self,
        initial_root: Path,
        extra_excludes: Iterable[str] | None = None,
        use_gitignore: bool = True,
        recent_limit: int = 8,
    ) -> None:
        self.extra_excludes = set(extra_excludes or ())
        self.use_gitignore = use_gitignore
        self.recent_limit = max(1, int(recent_limit))
        self._lock = RLock()
        self._session: RepositorySession | None = None
        self._recent: list[Path] = []
        self.load(initial_root)

    @staticmethod
    def _validated_root(value: str | Path) -> Path:
        raw = str(value).strip()
        if not raw:
            raise ValueError("Repository path is required.")
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            raise ValueError(f"Repository path does not exist: {root}")
        if not root.is_dir():
            raise ValueError(f"Repository path is not a directory: {root}")
        return root

    def _new_session(self, root: Path) -> RepositorySession:
        service = FunctionMoveService(
            root,
            lambda: build_catalog(root, self.extra_excludes, self.use_gitignore),
        )
        # Analyze before replacing the current session, so a failed load leaves
        # the existing repository usable.
        service.catalog(refresh=True)
        return RepositorySession(root=root, service=service)

    def load(self, value: str | Path) -> RepositorySession:
        root = self._validated_root(value)
        new_session = self._new_session(root)
        with self._lock:
            self._session = new_session
            self._recent = [path for path in self._recent if path != root]
            self._recent.insert(0, root)
            del self._recent[self.recent_limit :]
            return new_session

    def current(self) -> RepositorySession:
        with self._lock:
            if self._session is None:
                raise RuntimeError("No repository session is active.")
            return self._session

    def reload(self) -> RepositorySession:
        root = self.current().root
        return self.load(root)

    def recent(self) -> list[str]:
        with self._lock:
            return [str(path) for path in self._recent]

    def status(self) -> dict:
        session = self.current()
        result = session.public_dict()
        result["recent"] = self.recent()
        return result
