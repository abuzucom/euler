"""Deterministic heuristic checkers for the QUALITY.md +script classes.

Each check reports candidates. The model reviewer confirms or dismisses
every candidate. Blocking checks fail the command line run on their own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import dependencies, python_ast, regex_scan, text_scan
from .common import (
    PYTHON_SUFFIXES,
    SKIPPED_DIRECTORIES,
    Finding,
    exceeds_parser_limits,
    find_parser_limit_files,
    parse_python_status,
    read_text,
    relative_name,
)

__all__ = ["CHECKS", "Finding", "collect_files", "exceeds_parser_limits", "find_parser_limit_files", "run_checks"]

TextCheck = Callable[[Path, str, str], list[Finding]]
AstCheck = Callable[[str, "python_ast.ast.Module"], list[Finding]]
ProjectCheck = Callable[[Path, list[str], "list[str] | None"], list[Finding]]


@dataclass(frozen=True)
class Check:
    """One named check and the functions that implement it."""

    class_id: str
    blocking: bool
    text_checks: tuple[TextCheck, ...] = ()
    ast_checks: tuple[AstCheck, ...] = ()
    project_check: ProjectCheck | None = None


CHECKS: dict[str, Check] = {
    "regex": Check("Q3", False, text_checks=(regex_scan.check_regex,)),
    "dead-code": Check("Q5", False, ast_checks=(python_ast.check_dead_code,)),
    "iteration-mutation": Check("Q8", False, ast_checks=(python_ast.check_iteration_mutation,)),
    "recursion": Check("Q9", False, ast_checks=(python_ast.check_recursion,)),
    "resource-leak": Check("Q11", True, ast_checks=(python_ast.check_resource_leaks,)),
    "mutable-default": Check("Q13", False, ast_checks=(python_ast.check_mutable_defaults,)),
    "empty-catch": Check(
        "M1", True, text_checks=(text_scan.check_js_empty_catch,), ast_checks=(python_ast.check_empty_catch,)
    ),
    "magic-number": Check("M11", False, ast_checks=(python_ast.check_magic_numbers,)),
    "incomplete-work": Check(
        "M12", True, text_checks=(text_scan.check_incomplete_markers,), ast_checks=(python_ast.check_stubs,)
    ),
    "suppressed-checks": Check("M13", True, text_checks=(text_scan.check_suppressions,)),
    "broad-catch": Check("M16", False, ast_checks=(python_ast.check_broad_catch,)),
    "debug-leftovers": Check(
        "M17", False, text_checks=(text_scan.check_js_debug,), ast_checks=(python_ast.check_debug_leftovers,)
    ),
    "hardcoded-env": Check("M18", False, text_checks=(text_scan.check_hardcoded_env,)),
    "untested-changes": Check("C3", False, project_check=dependencies.check_untested_changes),
    "unpinned": Check("D1", False, text_checks=(dependencies.check_unpinned,)),
    "lockfile-drift": Check("D2", False, project_check=dependencies.check_lockfile_drift),
    "unused-deps": Check("D5", False, project_check=dependencies.check_unused_deps),
}


def collect_files(paths: list[Path], root: Path) -> list[Path]:
    """Expand directories into files. Skip vendored and generated directories."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            for candidate in sorted(path.rglob("*")):
                parts = candidate.relative_to(path).parts
                if candidate.is_file() and not SKIPPED_DIRECTORIES.intersection(parts):
                    files.append(candidate)
        elif path.is_file():
            files.append(path)
    return files


def run_file_checks(
    checks: list[Check], path: Path, relative: str, parse_failures: list[str] | None = None
) -> list[Finding]:
    """Run the text and AST checks for one file. Append the path to parse_failures on a parser limit."""
    if not any(check.text_checks or check.ast_checks for check in checks):
        return []
    text = read_text(path)
    if text is None:
        return []
    findings: list[Finding] = []
    for check in checks:
        for text_check in check.text_checks:
            findings.extend(text_check(path, relative, text))
    ast_checks = [ast_check for check in checks for ast_check in check.ast_checks]
    if ast_checks and path.suffix in PYTHON_SUFFIXES:
        tree, hit_limit = parse_python_status(path, text)
        if hit_limit and parse_failures is not None:
            parse_failures.append(relative)
        if tree is not None:
            for ast_check in ast_checks:
                findings.extend(ast_check(relative, tree))
    return findings


def run_checks(
    names: list[str],
    paths: list[Path],
    root: Path,
    changed: list[str] | None = None,
    parse_failures: list[str] | None = None,
) -> list[Finding]:
    """Run the named checks over the given paths and return sorted findings.

    A caller-supplied parse_failures list receives the relative paths whose parse hit a parser limit.
    """
    checks = [CHECKS[name] for name in names]
    files = collect_files(paths, root)
    relatives = [relative_name(path, root) for path in files]
    findings: list[Finding] = []
    for path, relative in zip(files, relatives):
        findings.extend(run_file_checks(checks, path, relative, parse_failures))
    for check in checks:
        if check.project_check is not None:
            findings.extend(check.project_check(root, relatives, changed))
    return sorted(set(findings), key=lambda item: (item.path, item.line, item.class_id, item.message))
