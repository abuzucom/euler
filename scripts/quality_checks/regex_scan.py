"""Q3 detection of catastrophic backtracking shapes in regex literals."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import JS_SUFFIXES, PYTHON_SUFFIXES, Finding, line_of_offset, parse_python

RE_FUNCTIONS = frozenset({"compile", "match", "search", "fullmatch", "findall", "finditer", "sub", "subn", "split"})
GROUP_PREFIX = re.compile(r"\?(?:P?<[A-Za-z_]\w*>|<=|<!|[:=!>])")
BOUNDED_REPEAT = re.compile(r"\{(?P<low>\d*)(?P<comma>,(?P<high>\d*))?\}")
ESCAPE_LENGTH = 2
JS_LITERAL_START = re.compile(r"(?:^|[=(,:!&|?{};])[ \t]*/(?![/*])", re.MULTILINE)
JS_REGEXP_CALL = re.compile(r"new\s+RegExp\(\s*(?P<quote>['\"])(?P<body>(?:\\.|(?!(?P=quote))[^\\\n])*)(?P=quote)")


@dataclass
class GroupFrame:
    """Scanner state for one open group."""

    has_quantifier: bool = False
    first_tokens: list[str] = field(default_factory=list)
    current_first: str | None = None

    def add_atom(self, token: str) -> None:
        """Record the atom as the first token of the current alternative."""
        if self.current_first is None:
            self.current_first = token

    def close_alternative(self) -> None:
        """Finish the current alternative."""
        self.first_tokens.append(self.current_first or "")
        self.current_first = None


def parse_repeat(pattern: str, index: int) -> tuple[bool, bool, int]:
    """Return (repeats more than once, unbounded, length) for a quantifier at index."""
    if index >= len(pattern):
        return False, False, 0
    if pattern[index] in "*+":
        return True, True, 1
    match = BOUNDED_REPEAT.match(pattern, index)
    if not match:
        return False, False, 0
    length = len(match.group(0))
    if match.group("comma") and not match.group("high"):
        return True, True, length
    upper = int(match.group("high") or match.group("low") or "0")
    return upper > 1, False, length


def skip_class(pattern: str, index: int) -> int:
    """Return the index just past a character class starting at index."""
    position = index + 1
    if position < len(pattern) and pattern[position] == "]":
        position += 1
    while position < len(pattern) and pattern[position] != "]":
        position += ESCAPE_LENGTH if pattern[position] == "\\" else 1
    return position + 1


def close_group(stack: list[GroupFrame], pattern: str, index: int) -> str | None:
    """Pop a group at index and return a finding reason, if any."""
    frame = stack.pop() if len(stack) > 1 else GroupFrame()
    frame.close_alternative()
    repeated, unbounded, _ = parse_repeat(pattern, index + 1)
    tokens = [token for token in frame.first_tokens if token]
    if unbounded and frame.has_quantifier:
        return "nested quantifier"
    if unbounded and len(tokens) != len(set(tokens)):
        return "overlapping alternation under a quantifier"
    stack[-1].has_quantifier = stack[-1].has_quantifier or frame.has_quantifier or repeated
    stack[-1].add_atom("(group)")
    return None


def analyze_pattern(pattern: str) -> str | None:
    """Return the backtracking hazard in a pattern, or None."""
    stack = [GroupFrame()]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            stack[-1].add_atom(pattern[index : index + ESCAPE_LENGTH])
            index += ESCAPE_LENGTH
            continue
        if char == "[":
            end = skip_class(pattern, index)
            stack[-1].add_atom(pattern[index:end])
            index = end
            continue
        if char == "(":
            stack.append(GroupFrame())
            prefix = GROUP_PREFIX.match(pattern, index + 1)
            index = prefix.end() if prefix else index + 1
            continue
        if char == ")":
            reason = close_group(stack, pattern, index)
            if reason:
                return reason
        elif char == "|":
            stack[-1].close_alternative()
        elif char in "*+{" and parse_repeat(pattern, index)[0]:
            _, _, length = parse_repeat(pattern, index)
            stack[-1].has_quantifier = True
            index += length
            continue
        elif char not in "?^$":
            stack[-1].add_atom(char)
        index += 1
    return None


def python_patterns(path: Path, text: str) -> list[tuple[int, str]]:
    """Return (line, pattern) pairs for string patterns passed to re functions."""
    tree = parse_python(path, text)
    if tree is None:
        return []
    patterns = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        func = node.func
        is_re_call = isinstance(func.value, ast.Name) and func.value.id == "re" and func.attr in RE_FUNCTIONS
        first = node.args[0] if node.args else None
        if is_re_call and isinstance(first, ast.Constant) and isinstance(first.value, str):
            patterns.append((node.lineno, first.value))
    return patterns


def scan_js_literal(text: str, start: int) -> str | None:
    """Return the body of a JS regex literal opening at start, or None."""
    position = start
    in_class = False
    while position < len(text) and text[position] != "\n":
        char = text[position]
        if char == "\\":
            position += ESCAPE_LENGTH
            continue
        if char == "/" and not in_class:
            return text[start:position] or None
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        position += 1
    return None


def js_patterns(text: str) -> list[tuple[int, str]]:
    """Return (line, pattern) pairs for JS regex literals and RegExp strings."""
    patterns = []
    for match in JS_LITERAL_START.finditer(text):
        body = scan_js_literal(text, match.end())
        if body:
            patterns.append((line_of_offset(text, match.end()), body))
    for match in JS_REGEXP_CALL.finditer(text):
        body = match.group("body").replace("\\\\", "\\")
        patterns.append((line_of_offset(text, match.start("body")), body))
    return patterns


def check_regex(path: Path, relative: str, text: str) -> list[Finding]:
    """Q3: flag nested quantifiers and overlapping quantified alternations."""
    if path.suffix in PYTHON_SUFFIXES:
        patterns = python_patterns(path, text)
    elif path.suffix in JS_SUFFIXES:
        patterns = js_patterns(text)
    else:
        return []
    findings = []
    for line, pattern in patterns:
        reason = analyze_pattern(pattern)
        if reason:
            findings.append(Finding(relative, line, "Q3", f"regex {reason}: {pattern}", False))
    return findings
