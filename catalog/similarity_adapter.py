from __future__ import annotations

import ast
import keyword
from dataclasses import asdict
from typing import Any

from similarity_engine import (
    CallEdge,
    FunctionGraph,
    FunctionNode,
    SimilarityConfig,
    compare_functions,
)

FUNCTION_TYPES = {"function", "method"}


class _DescriptorVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.parameters: set[str] = set()
        self.variables: set[str] = set()
        self.keywords: set[str] = set()
        self.objects: set[str] = set()

    def visit_arguments(self, node: ast.arguments) -> None:
        args = [*node.posonlyargs, *node.args, *node.kwonlyargs]
        if node.vararg:
            args.append(node.vararg)
        if node.kwarg:
            args.append(node.kwarg)
        self.parameters.update(arg.arg for arg in args)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.variables.add(node.id)
        else:
            self.objects.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.objects.add(node.attr)
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        node_name = type(node).__name__.lower()
        if keyword.iskeyword(node_name):
            self.keywords.add(node_name)
        super().generic_visit(node)


def _source_descriptors(source: str) -> dict[str, tuple[str, ...]]:
    if not source.strip():
        return {"parameters": (), "variables": (), "keywords": (), "objects": ()}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"parameters": (), "variables": (), "keywords": (), "objects": ()}

    visitor = _DescriptorVisitor()
    visitor.visit(tree)
    keyword_names = {
        type(node).__name__.lower()
        for node in ast.walk(tree)
        if isinstance(
            node,
            (
                ast.Return,
                ast.If,
                ast.For,
                ast.While,
                ast.Try,
                ast.With,
                ast.Raise,
                ast.Assert,
                ast.Yield,
                ast.Await,
                ast.Lambda,
            ),
        )
    }
    return {
        "parameters": tuple(sorted(visitor.parameters)),
        "variables": tuple(sorted(visitor.variables - visitor.parameters)),
        "keywords": tuple(sorted(keyword_names)),
        "objects": tuple(sorted(visitor.objects - visitor.parameters)),
    }


def _module_ancestor(nodes: dict[str, Any], node_id: str) -> Any | None:
    current = nodes.get(node_id)
    while current is not None:
        if current.node_type == "module":
            return current
        current = nodes.get(current.parent_id) if current.parent_id else None
    return None


def graph_from_catalog(catalog: Any) -> FunctionGraph:
    nodes = catalog.nodes
    function_nodes: list[FunctionNode] = []

    for node_id, item in nodes.items():
        if item.node_type not in FUNCTION_TYPES:
            continue
        metadata = item.metadata or {}
        descriptors = _source_descriptors(str(metadata.get("source_code", "")))
        module = _module_ancestor(nodes, node_id)
        external_imports: list[str] = []
        if module is not None:
            for import_entry in module.metadata.get("imports", []):
                package = str(import_entry.get("module", "")).split(".")[0]
                if package:
                    external_imports.append(package)

        function_nodes.append(
            FunctionNode(
                qualified_name=node_id,
                name=item.name,
                parameters=descriptors["parameters"],
                variables=descriptors["variables"],
                keywords=descriptors["keywords"],
                objects=tuple(
                    sorted(
                        set(descriptors["objects"])
                        | set(metadata.get("mentions", []))
                    )
                ),
                calls=tuple(metadata.get("calls", [])),
                external_imports=tuple(sorted(set(external_imports))),
            )
        )

    function_ids = {node.qualified_name for node in function_nodes}
    edges: list[CallEdge] = []
    for relation in catalog.relationships:
        if relation.relationship_type != "calls":
            continue
        if relation.source_id in function_ids and relation.target_id in function_ids:
            edges.append(CallEdge(relation.source_id, relation.target_id))

    # Module imports are represented as low-weight evidence on each function in
    # that module. They are not traversable call-graph nodes.
    for function_node in function_nodes:
        for package in function_node.external_imports:
            edges.append(CallEdge(function_node.qualified_name, package, is_external=True))

    return FunctionGraph(function_nodes, edges)


def compare_catalog_functions(
    catalog: Any,
    left_id: str,
    right_id: str,
    *,
    context_depth: int = 1,
    distance_decay: float = 0.5,
    external_import_weight: float = 0.20,
) -> dict[str, Any]:
    if left_id == right_id:
        raise ValueError("Choose two different functions or methods.")

    graph = graph_from_catalog(catalog)
    missing = [node_id for node_id in (left_id, right_id) if node_id not in graph.nodes]
    if missing:
        raise ValueError(f"Unknown function node: {missing[0]}")

    config = SimilarityConfig(
        context_depth=context_depth,
        distance_decay=distance_decay,
        internal_edge_weight=1.0,
        external_import_weight=external_import_weight,
        node_weight=1.0,
    )
    result = compare_functions(graph, left_id, right_id, config)
    return {
        "left_root": result.left_root,
        "right_root": result.right_root,
        "score": result.score,
        "config": asdict(config),
        "layers": [asdict(layer) for layer in result.layers],
        # ``matched_nodes`` is retained for compatibility with the existing UI,
        # but now contains the complete Cartesian set of pairwise comparisons.
        "matched_nodes": [
            {
                "left_id": left,
                "right_id": right,
                "score": score,
                "distance": distance,
            }
            for left, right, score, distance in result.pairwise_comparisons
        ],
    }
