#!/usr/bin/env python3
"""Verify API routes in backend/src/api/routes.py declare expected auth.

This keeps the check aligned with the FastAPI code instead of relying on a
fixed-size text window after each decorator.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
ROUTES_FILE = ROOT / "backend/src/api/routes.py"
PUBLIC_ROUTES = {
    ("post", "/validate/demo"),
}
AUTH_DEPENDENCIES = {"require_api_key", "require_role"}


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def route_decorators(fn: ast.AsyncFunctionDef) -> Iterable[tuple[str, str]]:
    for decorator in fn.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Attribute):
            continue
        if not isinstance(decorator.func.value, ast.Name):
            continue
        if decorator.func.value.id != "router":
            continue
        method = decorator.func.attr
        if method not in {"get", "post", "put", "patch", "delete"}:
            continue
        if not decorator.args:
            continue
        path_arg = decorator.args[0]
        if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
            yield method, path_arg.value


def depends_on_auth(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or call_name(node.func) != "Depends":
        return False
    if not node.args:
        return False
    dependency = node.args[0]
    name = call_name(dependency)
    if name in AUTH_DEPENDENCIES:
        return True
    if isinstance(dependency, ast.Call):
        return call_name(dependency.func) in AUTH_DEPENDENCIES
    return False


def function_declares_auth(fn: ast.AsyncFunctionDef) -> bool:
    return any(depends_on_auth(node) for node in ast.walk(fn))


def main() -> int:
    tree = ast.parse(ROUTES_FILE.read_text(encoding="utf-8"), filename=str(ROUTES_FILE))
    failures: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for method, path in route_decorators(node):
            if (method, path) in PUBLIC_ROUTES:
                continue
            if not function_declares_auth(node):
                failures.append(f"{method.upper()} {path} -> {node.name}")

    if failures:
        print("Route auth coverage failed:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("route-auth-coverage OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
