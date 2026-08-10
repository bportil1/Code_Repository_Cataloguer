from pathlib import Path

from code_analyzer import CodeAnalyzer


def _project(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text(
        "def alpha(x):\n"
        "    return beta(x)\n\n"
        "def beta(x):\n"
        "    return x + 1\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "def gamma(y):\n"
        "    return y + 1\n",
        encoding="utf-8",
    )
    return tmp_path


def test_public_api_analysis(tmp_path):
    analyzer = CodeAnalyzer(_project(tmp_path), use_gitignore=False)
    catalog = analyzer.catalog()
    function_ids = sorted(
        node_id
        for node_id, node in catalog.nodes.items()
        if node.node_type in {"function", "method"}
    )

    assert len(function_ids) == 3
    assert 0.0 <= analyzer.compare(function_ids[0], function_ids[1])["score"] <= 1.0
    assert analyzer.similarity_matrix().summary.function_count == 3
    assert analyzer.duplicate_candidates(threshold=0.0)["summary"]["compared_pair_count"] == 3
    assert len(analyzer.clusters(k=2)["clusters"]) == 2


def test_public_api_preserves_move_apply_undo(tmp_path):
    analyzer = CodeAnalyzer(_project(tmp_path), use_gitignore=False)
    catalog = analyzer.catalog()
    alpha_id = next(
        node_id for node_id, node in catalog.nodes.items()
        if node.node_type == "function" and node.name == "alpha"
    )
    target_id = next(
        node_id for node_id, node in catalog.nodes.items()
        if node.node_type == "module" and node.path == "b.py"
    )

    plan = analyzer.preview_function_move(alpha_id, target_id)
    assert plan["valid"] is True
    assert analyzer.apply_function_move(plan["plan_id"])["success"] is True
    assert analyzer.undo_last_move()["success"] is True
