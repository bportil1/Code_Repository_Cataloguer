from __future__ import annotations

import ast
from pathlib import Path

from .models import ClassEntry, FunctionEntry, ImportEntry, ModuleEntry


def module_name_for_path(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else root.name


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _source_slice(lines: list[str], node: ast.AST) -> str:
    line_start = getattr(node, "lineno", 1)
    decorators = getattr(node, "decorator_list", [])
    if decorators:
        line_start = min(
            line_start,
            *(getattr(decorator, "lineno", line_start) for decorator in decorators),
        )
    line_end = getattr(node, "end_lineno", line_start)
    return "".join(lines[line_start - 1 : line_end]).rstrip()


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return ""


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    arguments = _unparse(node.args)
    returns = f" -> {_unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{node.name}({arguments}){returns}"


class DefinitionFacts(ast.NodeVisitor):
    def __init__(self) -> None:
        self.mentions: set[str] = set()
        self.calls: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.mentions.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        dotted = _dotted_name(node)
        if dotted:
            self.mentions.add(dotted)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted_name(node.func)
        if dotted:
            self.calls.add(dotted)
        self.generic_visit(node)


def _function_entry(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module_name: str,
    lines: list[str],
    parent: str | None,
) -> FunctionEntry:
    facts = DefinitionFacts()
    facts.visit(node)

    qualified = (
        f"{module_name}.{parent}.{node.name}"
        if parent
        else f"{module_name}.{node.name}"
    )

    return FunctionEntry(
        name=node.name,
        qualified_name=qualified,
        signature=_signature(node),
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno),
        docstring=ast.get_docstring(node, clean=True),
        decorators=[_unparse(value) for value in node.decorator_list],
        mentions=sorted(facts.mentions),
        calls=sorted(facts.calls),
        parent=parent,
        kind="method" if parent else "function",
        source_code=_source_slice(lines, node),
    )


def index_python_file(path: Path, root: Path) -> ModuleEntry:
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines(keepends=True)
    module_name = module_name_for_path(path, root)

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return ModuleEntry(
            path=path.relative_to(root).as_posix(),
            module_name=module_name,
            line_count=len(lines),
            docstring=None,
            parse_error=f"{exc.msg} at line {exc.lineno}",
        )

    imports: list[ImportEntry] = []
    classes: list[ClassEntry] = []
    functions: list[FunctionEntry] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    ImportEntry(
                        module=alias.name,
                        names=[],
                        alias=alias.asname,
                        level=0,
                        line=node.lineno,
                    )
                )

        elif isinstance(node, ast.ImportFrom):
            imports.append(
                ImportEntry(
                    module=node.module or "",
                    names=[alias.name for alias in node.names],
                    alias=None,
                    level=node.level,
                    line=node.lineno,
                )
            )

        elif isinstance(node, ast.ClassDef):
            methods = [
                _function_entry(child, module_name, lines, node.name)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append(
                ClassEntry(
                    name=node.name,
                    qualified_name=f"{module_name}.{node.name}",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    docstring=ast.get_docstring(node, clean=True),
                    bases=[_unparse(base) for base in node.bases],
                    decorators=[_unparse(value) for value in node.decorator_list],
                    methods=methods,
                    source_code=_source_slice(lines, node),
                )
            )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                _function_entry(node, module_name, lines, parent=None)
            )

    return ModuleEntry(
        path=path.relative_to(root).as_posix(),
        module_name=module_name,
        line_count=len(lines),
        docstring=ast.get_docstring(tree, clean=True),
        imports=imports,
        classes=classes,
        functions=functions,
    )
