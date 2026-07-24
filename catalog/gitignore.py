from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool

    def matches(self, relative_path: str, *, is_directory: bool) -> bool:
        path = relative_path.strip("/")
        if not path:
            return False

        pattern = self.pattern.strip("/")
        if not pattern:
            return False

        if self.directory_only:
            directory_candidates = _directory_candidates(path, is_directory)
            return any(self._matches_path(candidate) for candidate in directory_candidates)

        return self._matches_path(path)

    def _matches_path(self, path: str) -> bool:
        pattern = self.pattern.strip("/")

        if self.anchored:
            return PurePosixPath(path).match(pattern) or fnmatch.fnmatchcase(path, pattern)

        if "/" in pattern:
            if PurePosixPath(path).match(pattern) or fnmatch.fnmatchcase(path, pattern):
                return True
            return PurePosixPath(path).match(f"**/{pattern}")

        return any(fnmatch.fnmatchcase(part, pattern) for part in PurePosixPath(path).parts)


class GitIgnoreMatcher:
    def __init__(self, rules: list[IgnoreRule]) -> None:
        self.rules = rules

    @classmethod
    def from_lines(cls, lines: list[str]) -> "GitIgnoreMatcher":
        rules: list[IgnoreRule] = []
        for raw_line in lines:
            line = raw_line.rstrip()
            if not line or line.startswith("#"):
                continue

            negated = line.startswith("!")
            if negated:
                line = line[1:]
            elif line.startswith(r"\#"):
                line = line[1:]

            if not line:
                continue

            directory_only = line.endswith("/")
            anchored = line.startswith("/")
            rules.append(
                IgnoreRule(
                    pattern=line,
                    negated=negated,
                    directory_only=directory_only,
                    anchored=anchored,
                )
            )
        return cls(rules)

    def matches(self, relative_path: str, *, is_directory: bool) -> bool:
        ignored = False
        for rule in self.rules:
            if rule.matches(relative_path, is_directory=is_directory):
                ignored = not rule.negated
        return ignored


def _directory_candidates(path: str, is_directory: bool) -> list[str]:
    parts = list(PurePosixPath(path).parts)
    limit = len(parts) if is_directory else max(len(parts) - 1, 0)
    return ["/".join(parts[:index]) for index in range(1, limit + 1)]
