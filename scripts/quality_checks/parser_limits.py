#!/usr/bin/env python3
"""Report Python and TOML files that exhaust parser recursion depth or memory.

The script reads a JSON list of paths on stdin and writes the JSON list of
paths that hit a parser limit on stdout. It runs in a short-lived child
process, so a MemoryError from deeply nested input never reaches the process
that runs the checkers. It uses the standard library only and runs with
python -I.
"""

from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path

PYTHON_SUFFIX = ".py"
TOML_SUFFIX = ".toml"
PARSER_LIMIT_ERRORS = (RecursionError, MemoryError)


def hits_parser_limit(path: Path) -> bool:
    """Return True when parsing the file raises RecursionError or MemoryError."""
    if path.suffix not in (PYTHON_SUFFIX, TOML_SUFFIX):
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # The checkers skip unreadable files with their own warning.
        return False
    try:
        if path.suffix == TOML_SUFFIX:
            tomllib.loads(text)
        else:
            ast.parse(text, filename=str(path))
    except PARSER_LIMIT_ERRORS:
        return True
    except (SyntaxError, tomllib.TOMLDecodeError):
        # Syntax errors keep the checkers' warn-and-skip behavior.
        return False
    return False


def find_limit_failures(paths: list[str]) -> list[str]:
    """Return the paths whose parse hits a parser limit."""
    return [path for path in paths if hits_parser_limit(Path(path))]


def main() -> int:
    """Read paths from stdin and write the failing paths to stdout."""
    paths = json.load(sys.stdin)
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        sys.stderr.write("error: stdin must hold a JSON list of path strings. Pass paths as a JSON array.\n")
        return 1
    json.dump(find_limit_failures(paths), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
