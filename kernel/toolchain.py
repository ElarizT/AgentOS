"""Tiny Python AST to WebAssembly compiler for sandbox-bound agent code.

This module intentionally supports a small, predictable subset of Python. It is
not a CPython compatibility layer; it emits lightweight standalone WebAssembly
for arithmetic kernels that can run inside ``agent_os_core.WasmSandboxManager``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Iterable


class CompilationError(Exception):
    """Raised when agent Python cannot be lowered into the micro-WASM runtime."""


@dataclass
class FunctionContext:
    name: str
    params: list[str]
    locals: set[str] = field(default_factory=set)


class AgentCodeCompiler(ast.NodeVisitor):
    """Emit WAT S-expressions from a restricted Python AST."""

    def __init__(self) -> None:
        self._functions: list[str] = []
        self._context: FunctionContext | None = None

    def compile(self, python_code_str: str) -> str:
        try:
            module = ast.parse(python_code_str)
        except SyntaxError as exc:
            raise CompilationError(f"invalid Python syntax: {exc}") from exc

        self.visit(module)
        if not self._functions:
            raise CompilationError("expected at least one function definition")

        body = "\n\n".join(indent(function, 2) for function in self._functions)
        return f"(module\n{body}\n)"

    def visit_Module(self, node: ast.Module) -> None:
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef):
                self.visit(statement)
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._raise_import_error(statement)
            else:
                self._unsupported(statement, "only function definitions are supported at module scope")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._context is not None:
            self._unsupported(node, "nested functions are not supported")
        if node.decorator_list:
            self._unsupported(node, "decorators are not supported")
        if node.returns is not None:
            self._unsupported(node, "return annotations are not supported")
        if node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
            self._unsupported(node, "varargs, kwargs, and keyword-only args are not supported")
        if node.args.defaults:
            self._unsupported(node, "default argument values are not supported")

        params = [arg.arg for arg in node.args.args]
        for arg in node.args.args:
            if arg.annotation is not None:
                self._unsupported(arg, "argument annotations are not supported")

        self._context = FunctionContext(name=node.name, params=params)
        local_names = self._collect_local_names(node.body, params)
        self._context.locals = local_names

        lines: list[str] = [f'(func (export "{node.name}")']
        lines.extend(f"  (param ${param} f32)" for param in params)
        lines.append("  (result f32)")
        lines.extend(f"  (local ${name} f32)" for name in sorted(local_names))
        lines.extend(self._compile_statement(statement, is_tail=index == len(node.body) - 1) for index, statement in enumerate(node.body))
        lines.append(")")

        self._functions.append("\n".join(lines))
        self._context = None

    def _compile_statement(self, node: ast.stmt, *, is_tail: bool) -> str:
        if isinstance(node, ast.Assign):
            return self._compile_assign(node)
        if isinstance(node, ast.AnnAssign):
            return self._compile_annotated_assign(node)
        if isinstance(node, ast.Return):
            return self._compile_return(node)
        if isinstance(node, ast.If):
            return self._compile_if(node)
        if isinstance(node, ast.While):
            return self._compile_while(node)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and node.value.value is None:
            return "  f32.const 0"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._raise_import_error(node)
        if is_tail and isinstance(node, ast.Expr):
            return indent(self._compile_expr(node.value), 2)

        self._unsupported(node)

    def _compile_while(self, node: ast.While) -> str:
        if node.orelse:
            self._unsupported(node, "while/else blocks are not supported")
        if not node.body:
            self._unsupported(node, "empty while loops are not supported")

        body_lines: list[str] = []
        for statement in node.body:
            if isinstance(statement, (ast.Return, ast.If)):
                self._unsupported(
                    statement,
                    "early returns and nested if statements inside while loops are not supported",
                )
            body_lines.append(self._compile_statement(statement, is_tail=False))

        return "\n".join(
            [
                "  block",
                "    loop",
                indent(self._compile_compare(node.test), 6),
                "      i32.eqz",
                "      br_if 1",
                indent("\n".join(body_lines), 6),
                "      br 0",
                "    end",
                "  end",
            ]
        )

    def _compile_assign(self, node: ast.Assign) -> str:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            self._unsupported(node, "only simple variable assignments are supported")

        target = node.targets[0].id
        self._ensure_local(target, node)
        return f"{indent(self._compile_expr(node.value), 2)}\n  local.set ${target}"

    def _compile_annotated_assign(self, node: ast.AnnAssign) -> str:
        if node.value is None or not isinstance(node.target, ast.Name):
            self._unsupported(node, "only simple annotated assignments with values are supported")

        target = node.target.id
        self._ensure_local(target, node)
        return f"{indent(self._compile_expr(node.value), 2)}\n  local.set ${target}"

    def _compile_return(self, node: ast.Return) -> str:
        if node.value is None:
            self._unsupported(node, "empty returns are not supported")
        return indent(self._compile_expr(node.value), 2)

    def _compile_if(self, node: ast.If) -> str:
        if not node.body or not node.orelse:
            self._unsupported(node, "if expressions must have both true and false branches")
        if len(node.body) != 1 or len(node.orelse) != 1:
            self._unsupported(node, "if branches must contain exactly one statement")

        condition = self._compile_compare(node.test)
        true_branch = self._compile_branch_statement(node.body[0])
        false_branch = self._compile_branch_statement(node.orelse[0])

        return "\n".join(
            [
                indent(condition, 2),
                "  if (result f32)",
                indent(true_branch, 4),
                "  else",
                indent(false_branch, 4),
                "  end",
            ]
        )

    def _compile_branch_statement(self, node: ast.stmt) -> str:
        if isinstance(node, ast.Return):
            if node.value is None:
                self._unsupported(node, "empty returns are not supported")
            return self._compile_expr(node.value)
        if isinstance(node, ast.Expr):
            return self._compile_expr(node.value)
        self._unsupported(node, "if branches currently support return or expression statements only")

    def _compile_expr(self, node: ast.AST) -> str:
        if isinstance(node, ast.BinOp):
            op = {
                ast.Add: "f32.add",
                ast.Sub: "f32.sub",
                ast.Mult: "f32.mul",
                ast.Div: "f32.div",
            }.get(type(node.op))
            if op is None:
                self._unsupported(node, f"unsupported binary operator {type(node.op).__name__}")
            return "\n".join([self._compile_expr(node.left), self._compile_expr(node.right), op])

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return "\n".join(["f32.const -1", self._compile_expr(node.operand), "f32.mul"])

        if isinstance(node, ast.Name):
            self._ensure_known_name(node.id, node)
            return f"local.get ${node.id}"

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return f"f32.const {1.0 if node.value else 0.0}"
            if isinstance(node.value, (int, float)):
                return f"f32.const {float(node.value)!r}"
            self._unsupported(node, f"unsupported constant type {type(node.value).__name__}")

        if isinstance(node, ast.IfExp):
            condition = self._compile_compare(node.test)
            return "\n".join(
                [
                    condition,
                    "if (result f32)",
                    indent(self._compile_expr(node.body), 2),
                    "else",
                    indent(self._compile_expr(node.orelse), 2),
                    "end",
                ]
            )

        if isinstance(node, ast.Compare):
            return self._compile_compare(node)

        if isinstance(node, ast.Call):
            self._unsupported(node, "function calls are not supported in the sandboxed micro-runtime")

        self._unsupported(node)

    def _compile_compare(self, node: ast.AST) -> str:
        if not isinstance(node, ast.Compare):
            self._unsupported(node, "if conditions must be comparisons")
        if len(node.ops) != 1 or len(node.comparators) != 1:
            self._unsupported(node, "chained comparisons are not supported")

        op = {
            ast.Gt: "f32.gt",
            ast.GtE: "f32.ge",
            ast.Lt: "f32.lt",
            ast.LtE: "f32.le",
            ast.Eq: "f32.eq",
            ast.NotEq: "f32.ne",
        }.get(type(node.ops[0]))
        if op is None:
            self._unsupported(node, f"unsupported comparison operator {type(node.ops[0]).__name__}")

        return "\n".join([self._compile_expr(node.left), self._compile_expr(node.comparators[0]), op])

    def _collect_local_names(self, statements: Iterable[ast.stmt], params: list[str]) -> set[str]:
        locals_: set[str] = set()
        param_set = set(params)

        for statement in statements:
            for child in ast.walk(statement):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if not isinstance(target, ast.Name):
                            self._unsupported(target, "only simple variable assignments are supported")
                        if target.id not in param_set:
                            locals_.add(target.id)
                elif isinstance(child, ast.AnnAssign):
                    if not isinstance(child.target, ast.Name):
                        self._unsupported(child.target, "only simple annotated assignments are supported")
                    if child.target.id not in param_set:
                        locals_.add(child.target.id)
                elif isinstance(child, ast.For):
                    self._unsupported(child, "for loops are not supported by this first-pass micro-compiler")

        return locals_

    def _ensure_local(self, name: str, node: ast.AST) -> None:
        context = self._require_context()
        if name not in context.params and name not in context.locals:
            self._unsupported(node, f"local '{name}' was not registered during analysis")

    def _ensure_known_name(self, name: str, node: ast.AST) -> None:
        context = self._require_context()
        if name not in context.params and name not in context.locals:
            raise CompilationError(f"unknown variable '{name}' at line {getattr(node, 'lineno', '?')}")

    def _require_context(self) -> FunctionContext:
        if self._context is None:
            raise CompilationError("internal compiler error: missing function context")
        return self._context

    def _raise_import_error(self, node: ast.AST) -> None:
        if isinstance(node, ast.Import):
            names = ", ".join(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = node.module or "<relative import>"
        else:
            names = type(node).__name__
        raise CompilationError(f"unsupported import '{names}': libraries are not available in the sandboxed micro-runtime")

    def _unsupported(self, node: ast.AST, message: str | None = None) -> None:
        detail = message or f"unsupported AST node {type(node).__name__}"
        raise CompilationError(f"{detail} at line {getattr(node, 'lineno', '?')}")


def compile_agent_script(python_code_str: str) -> bytes:
    """Compile restricted agent Python source into raw standalone WASM bytes."""

    compiler = AgentCodeCompiler()
    wat = compiler.compile(python_code_str)

    try:
        from wasmtime import wat2wasm
    except ImportError as exc:
        raise CompilationError(
            "wasmtime Python package is required to assemble WAT into WASM bytes"
        ) from exc

    try:
        return wat2wasm(wat)
    except Exception as exc:  # wasmtime raises WasmtimeError from native bindings.
        raise CompilationError(f"failed to assemble generated WAT: {exc}\n\n{wat}") from exc


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else line for line in text.splitlines())


if __name__ == "__main__":
    sample = """
def calculate_metrics(x, y):
    z = x + y * 2
    if z > 10:
        return z
    else:
        return z / 2
"""

    wasm = compile_agent_script(sample)
    print(f"compiled {len(wasm)} bytes")
