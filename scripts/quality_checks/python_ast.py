"""AST-based checks for Python sources."""

from __future__ import annotations

import ast
import itertools
from collections.abc import Iterator
from typing import TypeGuard

from .common import Finding

TERMINAL_STATEMENTS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
MUTATING_METHODS = frozenset(
    {"remove", "pop", "append", "clear", "insert", "extend", "add", "discard", "update", "popitem", "setdefault"}
)
VIEW_METHODS = frozenset({"items", "keys", "values"})
DEPTH_PARAMETER_HINTS = ("depth", "level")
DEPTH_PARAMETER_NAMES = frozenset({"limit", "max_depth", "remaining"})
FILE_OPENERS = frozenset({"gzip", "bz2", "lzma", "tarfile", "io"})
DB_MODULES = frozenset({"sqlite3", "psycopg2", "psycopg", "pymysql", "MySQLdb", "oracledb", "pyodbc", "duckdb"})
RELEASE_METHODS = frozenset({"close", "release"})
MUTABLE_FACTORIES = frozenset({"list", "dict", "set", "defaultdict", "OrderedDict", "deque"})
BROAD_EXCEPTIONS = frozenset({"Exception", "BaseException"})
DEBUGGER_MODULES = frozenset({"pdb", "ipdb", "pudb"})
ABSTRACT_DECORATORS = frozenset({"abstractmethod", "overload", "abstractproperty"})
TRIVIAL_NUMBERS = frozenset({0, 1})


def iter_blocks(tree: ast.AST) -> Iterator[list[ast.stmt]]:
    """Yield every statement list in the tree."""
    for node in ast.walk(tree):
        for field_name in ("body", "orelse", "finalbody"):
            block = getattr(node, field_name, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def is_placeholder_body(body: list[ast.stmt]) -> bool:
    """Return True when a body holds only pass, ellipsis, or a docstring."""
    for statement in body:
        if isinstance(statement, ast.Pass):
            continue
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and (statement.value.value is Ellipsis or isinstance(statement.value.value, str))
        ):
            continue
        return False
    return True


def check_dead_code(relative: str, tree: ast.Module) -> list[Finding]:
    """Q5: statements after a terminal statement and constant-false branches."""
    findings = []
    for block in iter_blocks(tree):
        for previous, statement in itertools.pairwise(block):
            if isinstance(previous, TERMINAL_STATEMENTS):
                findings.append(Finding(relative, statement.lineno, "Q5", "unreachable statement", False))
                break
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Constant) and node.test.value is False:
            findings.append(Finding(relative, node.lineno, "Q5", "branch with a constant false condition", False))
    return findings


def iterated_name(loop: ast.For) -> str | None:
    """Return the collection name a for loop iterates over directly."""
    source = loop.iter
    if isinstance(source, ast.Call) and isinstance(source.func, ast.Attribute) and source.func.attr in VIEW_METHODS:
        source = source.func.value
    return source.id if isinstance(source, ast.Name) else None


def mutates_name(node: ast.AST, name: str) -> bool:
    """Return True when the node mutates the named collection."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        target = node.func.value
        return isinstance(target, ast.Name) and target.id == name and node.func.attr in MUTATING_METHODS
    if isinstance(node, ast.Delete):
        for target in node.targets:
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == name:
                return True
    return False


def check_iteration_mutation(relative: str, tree: ast.Module) -> list[Finding]:
    """Q8: mutation of a collection inside a loop over the same collection."""
    findings = []
    for loop in ast.walk(tree):
        if not isinstance(loop, ast.For):
            continue
        name = iterated_name(loop)
        if name is None:
            continue
        for statement in loop.body:
            for node in ast.walk(statement):
                if isinstance(node, (ast.Call, ast.Delete)) and mutates_name(node, name):
                    message = f"'{name}' mutated while iterating over it"
                    findings.append(Finding(relative, node.lineno, "Q8", message, False))
    return findings


def calls_itself(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True when the function body calls the function by name."""
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == function.name:
            return True
        if (
            isinstance(func, ast.Attribute)
            and func.attr == function.name
            and isinstance(func.value, ast.Name)
            and func.value.id in ("self", "cls")
        ):
            return True
    return False


def has_checked_depth(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True when a depth-like parameter appears in a comparison."""
    arguments = function.args.args + function.args.kwonlyargs + function.args.posonlyargs
    names = {
        argument.arg
        for argument in arguments
        if argument.arg in DEPTH_PARAMETER_NAMES or any(hint in argument.arg for hint in DEPTH_PARAMETER_HINTS)
    }
    for node in ast.walk(function):
        if isinstance(node, ast.Compare):
            compared = [node.left, *node.comparators]
            if any(isinstance(item, ast.Name) and item.id in names for item in compared):
                return True
    return False


def check_recursion(relative: str, tree: ast.Module) -> list[Finding]:
    """Q9: self-recursive functions without a compared depth parameter."""
    findings = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and calls_itself(node)
            and not has_checked_depth(node)
        ):
            message = f"'{node.name}' recurses without an enforced depth limit"
            findings.append(Finding(relative, node.lineno, "Q9", message, False))
    return findings


def check_mutable_defaults(relative: str, tree: ast.Module) -> list[Finding]:
    """Q13: mutable default argument values."""
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is None:
                continue
            is_literal = isinstance(default, (ast.List, ast.Dict, ast.Set))
            is_factory = (
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id in MUTABLE_FACTORIES
            )
            if is_literal or is_factory:
                findings.append(Finding(relative, default.lineno, "Q13", "mutable default argument", False))
    return findings


def check_empty_catch(relative: str, tree: ast.Module) -> list[Finding]:
    """M1: exception handlers whose body swallows the error."""
    return [
        Finding(relative, node.lineno, "M1", "exception handler swallows the error", True)
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and is_placeholder_body(node.body)
    ]


def is_broad_handler(handler: ast.ExceptHandler) -> bool:
    """Return True for bare handlers and handlers catching Exception or BaseException."""
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(item, ast.Name) and item.id in BROAD_EXCEPTIONS for item in types)


def check_broad_catch(relative: str, tree: ast.Module) -> list[Finding]:
    """M16: broad handlers without a re-raise. M1 owns swallowing handlers."""
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not is_broad_handler(node):
            continue
        if is_placeholder_body(node.body):
            continue
        if not any(isinstance(child, ast.Raise) for statement in node.body for child in ast.walk(statement)):
            findings.append(Finding(relative, node.lineno, "M16", "broad exception handler without re-raise", False))
    return findings


def build_parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Return a child-to-parent map for the tree."""
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def is_resource_call(node: ast.Call) -> bool:
    """Return True for calls that acquire a resource needing release."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "open"
    if not isinstance(func, ast.Attribute):
        return False
    owner = func.value.id if isinstance(func.value, ast.Name) else None
    return (
        (func.attr == "open" and owner in FILE_OPENERS)
        or (func.attr == "socket" and owner == "socket")
        or (func.attr == "connect" and owner in DB_MODULES)
        or func.attr == "acquire"
    )


def enclosing_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    """Return the nearest enclosing function or module."""
    current = parents.get(node)
    while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
        current = parents.get(current)
    return current if current is not None else node


def inside_with_item(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Return True when the node sits inside a with statement's context expression."""
    current = parents.get(node)
    while current is not None and not isinstance(current, ast.stmt):
        if isinstance(current, ast.withitem):
            return True
        current = parents.get(current)
    return False


def released_in_finally(scope: ast.AST, resource: str) -> bool:
    """Return True when a finally block closes or releases the named resource."""
    for node in ast.walk(scope):
        if not isinstance(node, ast.Try):
            continue
        for statement in node.finalbody:
            for call in ast.walk(statement):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in RELEASE_METHODS
                    and ast.unparse(call.func.value) == resource
                ):
                    return True
    return False


def resource_name(node: ast.Call, parent: ast.AST | None) -> str | None:
    """Return the expression that owns the acquired resource."""
    if isinstance(node.func, ast.Attribute) and node.func.attr == "acquire":
        return ast.unparse(node.func.value)
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
        return ast.unparse(parent.targets[0])
    return None


def ownership_moves(parent: ast.AST | None) -> bool:
    """Return True when the resource returns to the caller or into an object."""
    if isinstance(parent, (ast.Return, ast.Yield, ast.YieldFrom)):
        return True
    if isinstance(parent, ast.Assign):
        return all(isinstance(target, ast.Attribute) for target in parent.targets)
    return False


def check_resource_leaks(relative: str, tree: ast.Module) -> list[Finding]:
    """Q11: resources acquired without with, finally release, or ownership transfer."""
    parents = build_parents(tree)
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_resource_call(node):
            continue
        parent = parents.get(node)
        if inside_with_item(node, parents) or ownership_moves(parent):
            continue
        name = resource_name(node, parent)
        if name and released_in_finally(enclosing_scope(node, parents), name):
            continue
        call_text = ast.unparse(node.func)
        message = f"'{call_text}' result has no guaranteed release"
        findings.append(Finding(relative, node.lineno, "Q11", message, True))
    return findings


def is_constant_assignment(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Return True when the node sits inside an UPPER_CASE constant assignment."""
    current = parents.get(node)
    while current is not None and not isinstance(current, ast.stmt):
        current = parents.get(current)
    if isinstance(current, ast.Assign):
        targets = current.targets
    elif isinstance(current, ast.AnnAssign):
        targets = [current.target]
    else:
        return False
    return all(isinstance(target, ast.Name) and target.id.isupper() for target in targets)


def check_magic_numbers(relative: str, tree: ast.Module) -> list[Finding]:
    """M11: numeric literals outside constant assignments. Candidates only."""
    parents = build_parents(tree)
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
            continue
        if not isinstance(node.value, (int, float)) or abs(node.value) in TRIVIAL_NUMBERS:
            continue
        if is_constant_assignment(node, parents):
            continue
        message = f"unnamed numeric literal {node.value!r}"
        findings.append(Finding(relative, node.lineno, "M11", message, False))
    return findings


def decorator_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the bare names of a function's decorators."""
    names = set()
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)
    return names


def is_protocol_member(function: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Return True for methods of classes deriving from Protocol."""
    owner = parents.get(function)
    if not isinstance(owner, ast.ClassDef):
        return False
    return any(ast.unparse(base).split(".")[-1].startswith("Protocol") for base in owner.bases)


def is_stub_body(body: list[ast.stmt]) -> bool:
    """Return True for bodies holding pass or ellipsis and nothing else of substance."""
    has_placeholder = any(
        isinstance(item, ast.Pass)
        or (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and item.value.value is Ellipsis)
        for item in body
    )
    return has_placeholder and is_placeholder_body(body)


def is_bare_not_implemented(node: ast.AST) -> TypeGuard[ast.Raise]:
    """Return True for raise NotImplementedError without a message."""
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    exc = node.exc
    if isinstance(exc, ast.Name):
        return exc.id == "NotImplementedError"
    return isinstance(exc, ast.Call) and ast.unparse(exc.func) == "NotImplementedError" and not exc.args


def check_stubs(relative: str, tree: ast.Module) -> list[Finding]:
    """M12: stub function bodies and NotImplementedError without a message."""
    parents = build_parents(tree)
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if decorator_names(node) & ABSTRACT_DECORATORS or is_protocol_member(node, parents):
            continue
        if is_stub_body(node.body):
            findings.append(Finding(relative, node.lineno, "M12", f"'{node.name}' has a stub body", True))
        for child in ast.walk(node):
            if is_bare_not_implemented(child):
                findings.append(Finding(relative, child.lineno, "M12", "NotImplementedError without a message", True))
    return findings


def has_main_guard(tree: ast.Module) -> bool:
    """Return True when the module runs code under a __main__ guard."""
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            compared = [node.test.left, *node.test.comparators]
            if any(isinstance(item, ast.Constant) and item.value == "__main__" for item in compared):
                return True
    return False


def is_debugger_import(node: ast.AST) -> TypeGuard[ast.Import | ast.ImportFrom]:
    """Return True for imports of pdb, ipdb, or pudb."""
    if isinstance(node, ast.Import):
        return any(alias.name in DEBUGGER_MODULES for alias in node.names)
    return isinstance(node, ast.ImportFrom) and node.module in DEBUGGER_MODULES


def check_debug_leftovers(relative: str, tree: ast.Module) -> list[Finding]:
    """M17: breakpoints, debugger imports, and print calls in library modules."""
    flag_prints = not has_main_guard(tree)
    findings = []
    for node in ast.walk(tree):
        if is_debugger_import(node):
            findings.append(Finding(relative, node.lineno, "M17", "debugger import", False))
            continue
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and (node.func.id == "breakpoint" or (flag_prints and node.func.id == "print"))
        ):
            message = f"{node.func.id}() call left in code"
            findings.append(Finding(relative, node.lineno, "M17", message, False))
    return findings
