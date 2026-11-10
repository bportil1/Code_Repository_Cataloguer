"""Read-only Code Analyzer P5-18 contract tests (no server needed)."""
import hashlib
from pathlib import Path

import pytest

from code_analyzer.source_evidence_navigation import (
    EvidenceNavigationError, inspect_verified_finding,
)


def locator(data: bytes, **changes):
    value = dict(producer_module="pypique", finding_id="f-1", project_id="a",
                 relative_path="pkg/target.py", start_line=2, end_line=3,
                 source_sha256=hashlib.sha256(data).hexdigest())
    value.update(changes)
    return value


def repo(tmp_path):
    root = tmp_path / "a"
    (root / "pkg").mkdir(parents=True)
    data = b"first = 1\nsecond = 2\nthird = 3\n"
    (root / "pkg/target.py").write_bytes(data)
    return root, data


def test_exact_verified_read_only_excerpt(tmp_path):
    root, data = repo(tmp_path)
    before = (root / "pkg/target.py").read_bytes()
    view = inspect_verified_finding(locator(data), repository_root=root, active_project_id="a")
    assert view["schema"] == "pah.source-evidence@1"
    assert view["mode"] == "read_only"
    assert view["excerpt"] == "second = 2\nthird = 3"
    assert view["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert (root / "pkg/target.py").read_bytes() == before


@pytest.mark.parametrize("change", [
    {"project_id": "b"}, {"relative_path": "../secret.py"},
    {"relative_path": "/etc/passwd"}, {"relative_path": "pkg//target.py"},
    {"relative_path": "pkg/./target.py"}, {"relative_path": "pkg\\target.py"},
    {"source_sha256": "0" * 64}, {"start_line": True},
    {"start_line": 0}, {"end_line": 200}, {"producer_module": "other"},
])
def test_untrusted_evidence_rejected(tmp_path, change):
    root, data = repo(tmp_path)
    with pytest.raises(EvidenceNavigationError):
        inspect_verified_finding(locator(data, **change), repository_root=root, active_project_id="a")


def test_project_selection_mismatch(tmp_path):
    root, data = repo(tmp_path)
    with pytest.raises(EvidenceNavigationError, match="different project"):
        inspect_verified_finding(locator(data), repository_root=root, active_project_id="other")


def test_symlink_escape_rejected(tmp_path):
    root, data = repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_bytes(data)
    (root / "pkg/link.py").symlink_to(outside)
    with pytest.raises(EvidenceNavigationError, match="escapes"):
        inspect_verified_finding(locator(data, relative_path="pkg/link.py"), repository_root=root, active_project_id="a")


def test_changed_source_fails_closed(tmp_path):
    root, data = repo(tmp_path)
    (root / "pkg/target.py").write_text("changed\n")
    with pytest.raises(EvidenceNavigationError, match="fingerprint mismatch"):
        inspect_verified_finding(locator(data), repository_root=root, active_project_id="a")


def test_binary_and_invalid_utf8_rejected(tmp_path):
    root, _ = repo(tmp_path)
    for data in (b"one\x00two", b"\xff"):
        (root / "pkg/target.py").write_bytes(data)
        with pytest.raises(EvidenceNavigationError):
            inspect_verified_finding(locator(data, start_line=1, end_line=1), repository_root=root, active_project_id="a")
