"""Shared types and file helpers for the deterministic checkers."""

from __future__ import annotations

import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

PYTHON_SUFFIXES = frozenset({".py"})
TOML_SUFFIX = ".toml"
# Deeply nested input exhausts the parsers with these errors instead of a syntax error.
PARSER_LIMIT_ERRORS = (RecursionError, MemoryError)
JS_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})
SOURCE_SUFFIXES = (
    PYTHON_SUFFIXES
    | JS_SUFFIXES
    | frozenset({
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".cs",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".swift",
        ".scala",
        ".sh",
    })
)
CONFIG_SUFFIXES = frozenset({".yml", ".yaml", ".toml", ".cfg", ".ini"})
SKIPPED_DIRECTORIES = frozenset({
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "vendor",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
})
TEST_DIRECTORIES = frozenset({"tests", "test", "__tests__", "spec"})


@dataclass(frozen=True)
class Finding:
    """One heuristic checker result."""

    path: str
    line: int
    class_id: str
    message: str
    blocking: bool


def is_test_path(relative: str) -> bool:
    """Return True when the path belongs to a test suite."""
    parts = Path(relative).parts
    name = parts[-1] if parts else ""
    if any(part in TEST_DIRECTORIES for part in parts[:-1]):
        return True
    stem = name.split(".")[0]
    return name.startswith("test_") or stem.endswith("_test") or ".spec." in name or ".test." in name


def relative_name(path: Path, root: Path) -> str:
    """Return the POSIX path relative to the root."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def read_text(path: Path) -> str | None:
    """Return file text, or None for unreadable or binary files."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        sys.stderr.write(f"warning: skipped {path}: {error}. Convert the file to UTF-8 to check it.\n")
        return None


def parse_python(path: Path, text: str) -> ast.Module | None:
    """Return the parsed module, or None with a warning on a syntax error or a parser limit."""
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError as error:
        sys.stderr.write(f"warning: skipped {path}: {error}. Fix the syntax error to check the file.\n")
    except PARSER_LIMIT_ERRORS as error:
        sys.stderr.write(f"warning: skipped {path}: {type(error).__name__}. Reduce the nesting to check the file.\n")
    return None


def exceeds_parser_limits(path: Path) -> bool:
    """Return True when the Python or TOML parser runs out of recursion depth or memory on the file."""
    if path.suffix not in PYTHON_SUFFIXES and path.suffix != TOML_SUFFIX:
        return False
    text = read_text(path)
    if text is None:
        return False
    try:
        if path.suffix == TOML_SUFFIX:
            tomllib.loads(text)
        else:
            ast.parse(text, filename=str(path))
    except PARSER_LIMIT_ERRORS:
        return True
    except (SyntaxError, tomllib.TOMLDecodeError):
        # Syntax errors keep the existing warn-and-skip behavior of the checkers.
        return False
    return False


def line_of_offset(text: str, offset: int) -> int:
    """Return the 1-based line number of a character offset."""
    return text.count("\n", 0, offset) + 1
