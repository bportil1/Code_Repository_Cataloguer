from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class FileChange:
    path: Path
    relative_path: str
    original_text: str
    updated_text: str
    original_hash: str
    diff: str

@dataclass
class ChangePlan:
    id: str
    function_id: str
    target_module_id: str
    summary: dict
    changes: list[FileChange]
    warnings: list[str] = field(default_factory=list)

    def public_dict(self) -> dict:
        return {
            "plan_id": self.id,
            "valid": True,
            "function_id": self.function_id,
            "target_module_id": self.target_module_id,
            "summary": self.summary,
            "warnings": self.warnings,
            "changes": [
                {"path": c.relative_path, "diff": c.diff, "original_hash": c.original_hash}
                for c in self.changes
            ],
        }
