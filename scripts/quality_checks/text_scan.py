"""Line and pattern checks that work on raw text."""

from __future__ import annotations

import re
from pathlib import Path

from .common import CONFIG_SUFFIXES, JS_SUFFIXES, SOURCE_SUFFIXES, Finding, is_test_path, line_of_offset

# The marker words are assembled from fragments. A literal copy here would
# make this module report itself.
MARKER_WORDS = ("TO" + "DO", "FIX" + "ME", "X" + "XX", "HA" + "CK")
MARKER_PATTERN = re.compile(r"\b(?:" + "|".join(MARKER_WORDS) + r")\b")
SUPPRESSION_MARKERS = (
    "# no" + "qa",
    "eslint-" + "disable",
    "type: " + "ignore",
    "@ts-" + "ignore",
    "@ts-" + "nocheck",
    "pylint: " + "disable",
    "//no" + "lint",
    "// no" + "lint",
)
WEAKENED_CI_PATTERN = re.compile(r"^\s*continue-on-error:\s*true\b")
JS_EMPTY_CATCH = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}")
JS_DEBUGGER = re.compile(r"^\s*debugger\s*;?\s*$")
JS_CONSOLE_LOG = re.compile(r"\bconsole\.log\s*\(")
URL_PATTERN = re.compile(r"https?://([A-Za-z0-9.-]+)")
IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
ABSOLUTE_PATH_PATTERN = re.compile(r"""["'](?:/home/|/Users/|[A-Za-z]:\\)""")
DOCUMENTATION_HOSTS = ("example.com", "example.org", "example.net", "localhost")
DOCUMENTATION_SUFFIXES = (".example", ".test", ".invalid")


def is_code_or_config(path: Path) -> bool:
    """Return True for source and configuration files."""
    return path.suffix in SOURCE_SUFFIXES or path.suffix in CONFIG_SUFFIXES


def check_incomplete_markers(path: Path, relative: str, text: str) -> list[Finding]:
    """M12: deferred-work markers in source and configuration files."""
    if not is_code_or_config(path):
        return []
    return [
        Finding(relative, number, "M12", "deferred-work marker", True)
        for number, line in enumerate(text.splitlines(), 1)
        if MARKER_PATTERN.search(line)
    ]


def check_suppressions(path: Path, relative: str, text: str) -> list[Finding]:
    """M13: linter and type-checker suppressions and weakened CI steps."""
    if not is_code_or_config(path):
        return []
    in_workflow = ".github/workflows/" in relative or relative.startswith(".github/workflows/")
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        if any(marker in line for marker in SUPPRESSION_MARKERS):
            findings.append(Finding(relative, number, "M13", "check suppression", True))
        elif in_workflow and WEAKENED_CI_PATTERN.match(line):
            findings.append(Finding(relative, number, "M13", "CI step allowed to fail", True))
    return findings


def check_js_empty_catch(path: Path, relative: str, text: str) -> list[Finding]:
    """M1: empty catch blocks in JavaScript and TypeScript."""
    if path.suffix not in JS_SUFFIXES:
        return []
    return [
        Finding(relative, line_of_offset(text, match.start()), "M1", "empty catch block", True)
        for match in JS_EMPTY_CATCH.finditer(text)
    ]


def check_js_debug(path: Path, relative: str, text: str) -> list[Finding]:
    """M17: debugger statements and console.log calls in JavaScript and TypeScript."""
    if path.suffix not in JS_SUFFIXES:
        return []
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        if JS_DEBUGGER.match(line):
            findings.append(Finding(relative, number, "M17", "debugger statement", False))
        elif JS_CONSOLE_LOG.search(line):
            findings.append(Finding(relative, number, "M17", "console.log call left in code", False))
    return findings


def is_documentation_host(host: str) -> bool:
    """Return True for reserved documentation and loopback hosts."""
    host = host.lower()
    return host.endswith(DOCUMENTATION_SUFFIXES) or any(
        host == name or host.endswith("." + name) for name in DOCUMENTATION_HOSTS
    )


def check_hardcoded_env(path: Path, relative: str, text: str) -> list[Finding]:
    """M18: URLs, IPv4 literals, and user home paths in source files outside tests."""
    if path.suffix not in SOURCE_SUFFIXES or is_test_path(relative):
        return []
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        hosts = [match.group(1) for match in URL_PATTERN.finditer(line)]
        if any(not is_documentation_host(host) for host in hosts):
            findings.append(Finding(relative, number, "M18", "hardcoded URL", False))
        elif IPV4_PATTERN.search(line) and not URL_PATTERN.search(line):
            findings.append(Finding(relative, number, "M18", "hardcoded IPv4 address", False))
        elif ABSOLUTE_PATH_PATTERN.search(line):
            findings.append(Finding(relative, number, "M18", "hardcoded absolute user path", False))
    return findings
