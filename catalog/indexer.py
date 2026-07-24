from __future__ import annotations

import ast
from pathlib import Path

from .models import ClassEntry, FunctionEntry, ImportEntry, PythonModule
from .scanner import ProjectScan


def _expression_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts: list[str] = []

    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for argument, default in zip(positional, defaults):
        text = argument.arg
        if argument.annotation:
            text += f": {_expression_text(argument.annotation)}"
        if default is not None:
            text += f" = {_expression_text(default)}"
        parts.append(text)

    if args.vararg:
        text = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            text += f": {_expression_text(args.vararg.annotation)}"
        parts.append(text)
    elif args.kwonlyargs:
        parts.append("*")

    for argument, default in zip(args.kwonlyargs, args.kw_defaults):
        text = argument.arg
        if argument.annotation:
            text += f": {_expression_text(argument.annotation)}"
        if default is not None:
            text += f" = {_expression_text(default)}"
        parts.append(text)

    if args.kwarg:
        text = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            text += f": {_expression_text(args.kwarg.annotation)}"
        parts.append(text)

    result = f"{node.name}({', '.join(parts)})"
    if node.returns:
        result += f" -> {_expression_text(node.returns)}"
    return result


class MentionCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.mentions: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.mentions.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.mentions.add(_expression_text(node))
        self.generic_visit(node)


def _function_entry(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module_name: str,
    parent: str | None = None,
) -> FunctionEntry:
    collector = MentionCollector()
    for statement in node.body:
        collector.visit(statement)

    qualified = f"{module_name}.{node.name}" if parent is None else f"{module_name}.{parent}.{node.name}"
    return FunctionEntry(
        name=node.name,
        qualified_name=qualified,
        signature=_signature(node),
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno),
        docstring=ast.get_docstring(node),
        decorators=[_expression_text(item) for item in node.decorator_list],
        mentions=sorted(collector.mentions),
        parent=parent,
        kind="method" if parent else "function",
    )


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or root.name


def index_python_files(scan: ProjectScan) -> list[PythonModule]:
    modules: list[PythonModule] = []

    for path in sorted(scan.python_files):
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
        module_name = _module_name(path, scan.root)
        imports: list[ImportEntry] = []
        classes: list[ClassEntry] = []
        functions: list[FunctionEntry] = []

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportEntry(
                            module=alias.name,
                            alias=alias.asname,
                            line=node.lineno,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                imports.append(
                    ImportEntry(
                        module=node.module or "",
                        names=[alias.name for alias in node.names],
                        alias=", ".join(alias.asname for alias in node.names if alias.asname) or None,
                        level=node.level,
                        line=node.lineno,
                    )
                )
            elif isinstance(node, ast.ClassDef):
                methods = [
                    _function_entry(child, module_name, node.name)
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append(
                    ClassEntry(
                        name=node.name,
                        qualified_name=f"{module_name}.{node.name}",
                        line_start=node.lineno,
                        line_end=getattr(node, "end_lineno", node.lineno),
                        docstring=ast.get_docstring(node),
                        bases=[_expression_text(base) for base in node.bases],
                        decorators=[_expression_text(item) for item in node.decorator_list],
                        methods=methods,
                    )
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(_function_entry(node, module_name))

        modules.append(
            PythonModule(
                path=path.relative_to(scan.root).as_posix(),
                module_name=module_name,
                line_count=len(source.splitlines()),
                docstring=ast.get_docstring(tree),
                imports=imports,
                classes=classes,
                functions=functions,
            )
        )

    return modules
