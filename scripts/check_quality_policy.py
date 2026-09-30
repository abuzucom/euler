#!/usr/bin/env python3
"""Validate QUALITY.md structure, class tiers, encoding, width, and size.

With --prose-only the checker validates ASCII, LF line endings, prose
dashes, and width only. AGENTS.md uses that mode.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 32 * 1024
MAX_PROSE_WIDTH = 120
VALID_TIERS = ("Blocking", "Escalate", "Graded", "Advisory")
REQUIRED_CLASS_IDS = frozenset(
    [f"Q{number}" for number in range(1, 15)]
    + [f"M{number}" for number in range(1, 19)]
    + [f"C{number}" for number in range(1, 4)]
    + [f"D{number}" for number in range(1, 7)]
)
REQUIRED_TEXT = (
    "VERDICT: APPROVE | BLOCK | NEEDS-HUMAN",
    "RISK:",
    "RISK (partial):",
    "VERDICT_JSON:",
    '"schema_version"',
)
LONG_LINE_PREFIXES = ("|", "VERDICT_JSON:")
CLASS_HEADING = re.compile(r"^### ([QMCD]\d+) ")
TIERED_HEADING = re.compile(r"^### (?P<id>[QMCD]\d+) (?P<name>[^()]+) \((?P<tier>[A-Za-z]+)(?P<script> \+script)?\)$")
HEADING = re.compile(r"^#{2,3} .+$", re.MULTILINE)
CODE_SPAN = re.compile(r"`[^`]*`")
BULLET_PREFIX = "- "
PROSE_DASH = re.compile(r"\s--?-?\s|\s--?-?$")


@dataclass(frozen=True)
class PolicyClass:
    """One review class parsed from a QUALITY.md heading."""

    class_id: str
    name: str
    tier: str
    has_script: bool


def parse_classes(text: str) -> dict[str, PolicyClass]:
    """Return every well-formed class heading keyed by class ID."""
    classes: dict[str, PolicyClass] = {}
    for line in text.splitlines():
        match = TIERED_HEADING.match(line)
        if match and match.group("tier") in VALID_TIERS:
            classes[match.group("id")] = PolicyClass(
                match.group("id"),
                match.group("name").strip(),
                match.group("tier"),
                bool(match.group("script")),
            )
    return classes


def find_class_violations(text: str) -> list[str]:
    """Return missing, duplicate, and malformed class headings."""
    violations: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        heading = CLASS_HEADING.match(line)
        if not heading:
            continue
        class_id = heading.group(1)
        if class_id in seen:
            violations.append(f"duplicate class: {class_id}")
        seen.add(class_id)
        match = TIERED_HEADING.match(line)
        if not match or match.group("tier") not in VALID_TIERS:
            violations.append(f"class heading without a valid tier: {line}")
    for class_id in sorted(REQUIRED_CLASS_IDS - seen):
        violations.append(f"missing class: {class_id}")
    return violations


def find_structure_violations(text: str) -> list[str]:
    """Return missing verdict tokens and duplicate headings."""
    violations = [f"missing required text: {item}" for item in REQUIRED_TEXT if item not in text]
    headings = HEADING.findall(text)
    seen: set[str] = set()
    for heading in headings:
        if heading in seen:
            violations.append(f"duplicate heading: {heading}")
        seen.add(heading)
    return violations


def is_exempt_line(line: str) -> bool:
    """Return True for table rows and HTML comment lines."""
    stripped = line.strip()
    return stripped.startswith(("|", "<!--")) or stripped.endswith("-->")


def find_line_violations(text: str) -> list[str]:
    """Return prose width and prose dash violations outside fences."""
    violations: list[str] = []
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or is_exempt_line(line):
            continue
        if len(line) > MAX_PROSE_WIDTH and not line.startswith(LONG_LINE_PREFIXES):
            violations.append(f"line {line_number} exceeds {MAX_PROSE_WIDTH} characters")
        prose = CODE_SPAN.sub("", line.lstrip())
        prose = prose.removeprefix(BULLET_PREFIX)
        if PROSE_DASH.search(prose):
            violations.append(f"line {line_number} uses a prose dash")
    return violations


def decode_policy(raw: bytes) -> tuple[str, list[str]]:
    """Return the decoded text and any encoding violations."""
    violations: list[str] = []
    if len(raw) > MAX_BYTES:
        violations.append(f"policy exceeds {MAX_BYTES} bytes")
    if b"\r" in raw:
        violations.append("policy must use LF line endings")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        violations.append("policy must contain ASCII text only")
        text = raw.decode("ascii", errors="replace")
    return text, violations


def find_violations(path: Path, prose_only: bool = False) -> list[str]:
    """Return every violation for one policy file."""
    if not path.is_file():
        return [f"missing policy: {path}"]
    text, violations = decode_policy(path.read_bytes())
    violations.extend(find_line_violations(text))
    if not prose_only:
        violations.extend(find_structure_violations(text))
        violations.extend(find_class_violations(text))
    return violations


def main() -> int:
    """Print violations and return a blocking exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="QUALITY.md", type=Path)
    parser.add_argument("--prose-only", action="store_true", help="check encoding, dashes, and width only")
    args = parser.parse_args()
    violations = find_violations(args.path, prose_only=args.prose_only)
    for violation in violations:
        print(f"error: {args.path}: {violation}", file=sys.stderr)
    if violations:
        return 1
    print(f"ok       {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
