"""UCA-09 provider navigation compatibility and source safety."""
import hashlib
import json
import pytest

from code_analyzer.language_providers.navigation import (
    build_navigation_snapshot, SourceChangedError,
)


def test_atlas_navigation_preserves_candidate_confidence(tmp_path):
    path=tmp_path/'case.atl'; path.write_text('TEST ALPHA;\nMEASURE VOLTAGE;\nEND;\n')
    snap=build_navigation_snapshot('case.atl',tmp_path)
    assert snap['schema']=='code-analyzer.provider-navigation@1'
    assert snap['provider_id']=='cps.atlas.structural'
    assert snap['capabilities']['structural'] is True
    assert snap['capabilities']['semantic'] is False
    assert snap['semantics_verified'] is False
    assert snap['source_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert snap['items'] and all(i['confidence']=='unverified' for i in snap['items'])
    assert 'provider_artifact' not in snap
    json.dumps(snap)


def test_python_navigation_remains_supported(tmp_path):
    (tmp_path/'module.py').write_text('def work():\n    return 1\n')
    snap=build_navigation_snapshot('module.py',tmp_path)
    assert snap['language']=='python'
    assert snap['provider_id']=='python.ast'
    assert any(i['name']=='work' for i in snap['items'])


def test_unsupported_and_escape_paths_fail_closed(tmp_path):
    (tmp_path/'x.txt').write_text('plain')
    with pytest.raises(ValueError):build_navigation_snapshot('../outside.atl',tmp_path)
    with pytest.raises(ValueError):build_navigation_snapshot('x.txt',tmp_path)
    with pytest.raises(ValueError):build_navigation_snapshot('/etc/passwd',tmp_path)


def test_symlinks_rejected(tmp_path):
    (tmp_path/'real.atl').write_text('TEST A;')
    (tmp_path/'alias.atl').symlink_to(tmp_path/'real.atl')
    with pytest.raises((OSError,ValueError)):
        build_navigation_snapshot('alias.atl',tmp_path)
    (tmp_path/'sub').mkdir()
    (tmp_path/'link').symlink_to(tmp_path/'sub',target_is_directory=True)
    (tmp_path/'sub'/'nested.atl').write_text('TEST A;')
    with pytest.raises((OSError,ValueError)):
        build_navigation_snapshot('link/nested.atl',tmp_path)


def test_revisions_checked_before_and_after(tmp_path, monkeypatch):
    import code_analyzer.language_providers.navigation as nav
    (tmp_path/'a.atl').write_text('TEST A;')
    original=nav._verified_source_digest
    count=0
    def changed(*args):
        nonlocal count
        count+=1
        return '0'*64 if count == 2 else original(*args)
    monkeypatch.setattr(nav,'_verified_source_digest',changed)
    with pytest.raises(SourceChangedError):nav.build_navigation_snapshot('a.atl',tmp_path)
