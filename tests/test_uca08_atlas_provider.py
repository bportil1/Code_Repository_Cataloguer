"""UCA-08 structural adapter preservation tests."""
import json
import pytest

from code_analyzer.language_providers.atlas_provider import AtlasLanguageProvider
from code_analyzer.language_providers.atlas_registry import atlas_enabled_registry
from code_analyzer.language_providers.registry import default_registry
from code_analyzer.language_providers._atlas_engine.analysis import analyze_file


def _fixture(tmp_path):
    source = tmp_path / "sample.atl"
    source.write_text("TEST ALPHA;\nMEASURE VOLTAGE;\nEND;\n", encoding="utf-8")
    return source


def test_opt_in_provider(tmp_path):
    file = _fixture(tmp_path)
    assert default_registry().provider_for(file) is None
    reg = atlas_enabled_registry()
    assert reg.provider_for(file).descriptor.language == "atlas"
    assert reg.provider_for(tmp_path / "legacy.as").descriptor.language == "atlas"
    assert reg.provider_for(tmp_path / "other.py").descriptor.language == "python"


def test_capabilities_and_structural_items(tmp_path):
    file = _fixture(tmp_path)
    provider = AtlasLanguageProvider()
    assert provider.descriptor.capabilities.structural
    assert not provider.descriptor.capabilities.semantic
    assert not provider.descriptor.capabilities.similarity
    result = atlas_enabled_registry().analyze(file, tmp_path)
    assert result.language == "atlas"
    assert result.provider_artifact["schema"] == "cps.atlas.analysis@1"
    assert result.provider_artifact["summary"]["semantic_verified_count"] == 0
    assert result.items
    assert {item.confidence for item in result.items} == {"unverified"}
    assert all(item.relative_path == "sample.atl" for item in result.items)
    json.dumps(result.provider_artifact)


def test_original_engine_artifact_parity(tmp_path):
    file = _fixture(tmp_path)
    original = analyze_file(file).to_dict()
    converted = atlas_enabled_registry().analyze(file, tmp_path)
    assert converted.provider_artifact == original
    assert [(x.item_id, x.kind) for x in converted.items] == [
        (n["id"], n["kind"]) for n in original["graph"]["nodes"]
    ]


def test_reject_symlink_source(tmp_path):
    file = _fixture(tmp_path)
    (tmp_path / "alias.atl").symlink_to(file)
    with pytest.raises(ValueError, match="Symlinked"):
        atlas_enabled_registry().analyze("alias.atl", tmp_path)


def test_parser_diagnostics_preserved(tmp_path):
    file = tmp_path / "bad.atl"
    file.write_text("TEST (\n", encoding="utf-8")
    result = atlas_enabled_registry().analyze(file, tmp_path)
    assert result.diagnostics == tuple(
        f"{d['code']}: {d['message']}" for d in result.provider_artifact["diagnostics"]
    )
