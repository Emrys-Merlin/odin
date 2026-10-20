"""Split the code into the units the audit asks about (epic #133).

A unit is a function or method. Jev sees the unit's source as the target and its module as
context. A module over the long-context limit is sent as an outline instead: every other
function keeps its signature and docstring, its body becomes `...`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from jev import LONG_CONTEXT_BYTES


@dataclass(frozen=True)
class Unit:
    path: str  # relative to the root, e.g. src/odin/engine.py
    qualname: str  # e.g. Engine.tick
    lineno: int
    source: str

    @property
    def is_test(self) -> bool:
        return self.path.startswith("tests/")

    @property
    def key(self) -> str:
        return f"{self.path}::{self.qualname}"


def _functions(tree: ast.Module) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Top-level functions and methods of top-level classes, with their qualified names."""
    found = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    found.append((f"{node.name}.{item.name}", item))
    return found


def _start(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """First line of a function including its decorators (1-based)."""
    return min([node.lineno, *(d.lineno for d in node.decorator_list)])


def units(root: Path, paths: list[str]) -> list[Unit]:
    """All units in the given Python files below `root`."""
    found = []
    for path in paths:
        source = (root / path).read_text()
        lines = source.splitlines(keepends=True)
        for qualname, node in _functions(ast.parse(source)):
            text = "".join(lines[_start(node) - 1 : node.end_lineno])
            found.append(Unit(path, qualname, node.lineno, text))
    return found


def module_context(root: Path, path: str, target: str) -> str:
    """The module source, outlined around `target` if it is too long for the default mode."""
    source = (root / path).read_text()
    if len(source.encode()) <= LONG_CONTEXT_BYTES * 3 // 4:
        return source
    lines = source.splitlines(keepends=True)
    # Replace bodies bottom-up so earlier line numbers stay valid.
    for qualname, node in sorted(_functions(ast.parse(source)), key=lambda f: -f[1].lineno):
        if qualname == target:
            continue
        body = node.body
        keep = 1 if ast.get_docstring(node) is not None else 0
        if len(body) <= keep:
            continue
        first = body[keep].lineno - 1
        indent = " " * body[keep].col_offset
        lines[first : node.end_lineno] = [f"{indent}...\n"]
    return "".join(lines)


def python_files(root: Path, *dirs: str) -> list[str]:
    return sorted(str(p.relative_to(root)) for d in dirs for p in (root / d).rglob("*.py"))
