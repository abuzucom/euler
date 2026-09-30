#!/usr/bin/env python3
"""Summarize class and tier changes between two QUALITY.md revisions.

The report goes to stdout as markdown. The exit status is 1 when a class is
added, removed, retiered, or gains or loses script coverage and no file
under eval/cases/ changes in the same diff.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_quality_policy  # resolved through the path set above

EVAL_CASES_PREFIX = "eval/cases/"
RENAME_MARKER = " renamed: "


def compare_policies(base_text: str, head_text: str) -> list[str]:
    """Return one line per class difference between two policy texts."""
    base = check_quality_policy.parse_classes(base_text)
    head = check_quality_policy.parse_classes(head_text)
    changes = []
    for class_id in sorted(base.keys() - head.keys()):
        changes.append(f"{class_id} removed ({base[class_id].tier})")
    for class_id in sorted(head.keys() - base.keys()):
        changes.append(f"{class_id} added ({head[class_id].tier})")
    for class_id in sorted(base.keys() & head.keys()):
        old, new = base[class_id], head[class_id]
        if old.tier != new.tier:
            changes.append(f"{class_id} tier: {old.tier} -> {new.tier}")
        if old.has_script != new.has_script:
            changes.append(f"{class_id} script coverage: {old.has_script} -> {new.has_script}")
        if old.name != new.name:
            changes.append(f"{class_id}{RENAME_MARKER}{old.name} -> {new.name}")
    return changes


def requires_eval_case(changes: list[str]) -> bool:
    """Return True when any change affects verdicts or tiers."""
    return any(RENAME_MARKER not in change for change in changes)


def has_eval_change(changed_files: list[str]) -> bool:
    """Return True when the diff touches the eval corpus."""
    return any(path.startswith(EVAL_CASES_PREFIX) for path in changed_files)


def main() -> int:
    """Print the policy diff and enforce the eval-case rule."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_policy", type=Path)
    parser.add_argument("head_policy", type=Path)
    parser.add_argument("--changed-files", type=Path, required=True, help="file listing changed paths")
    args = parser.parse_args()
    base_text = args.base_policy.read_text(encoding="ascii") if args.base_policy.is_file() else ""
    changes = compare_policies(base_text, args.head_policy.read_text(encoding="ascii"))
    changed_files = args.changed_files.read_text(encoding="utf-8").split()
    lines = ["## QUALITY.md class changes", ""]
    lines += [f"- {change}" for change in changes] or ["- none"]
    sys.stdout.write("\n".join(lines) + "\n")
    if requires_eval_case(changes) and not has_eval_change(changed_files):
        sys.stderr.write("error: class or tier changes need a new or updated eval/cases/ case in the same diff\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
