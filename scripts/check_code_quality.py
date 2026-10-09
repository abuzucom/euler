#!/usr/bin/env python3
"""Run the deterministic QUALITY.md checkers over files or directories.

Every check is heuristic. Findings are candidates for the model reviewer.
The exit status is 1 when a blocking check (Q11, M1, M12, M13) reports a
finding, 2 on invalid input, and 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quality_checks import CHECKS, Finding, run_checks  # resolved through the path set above

EXIT_BLOCKING = 1
EXIT_INVALID_INPUT = 2
JSON_INDENT = 2
# Project-level classes report at line 1 and ignore the added-lines filter.
PROJECT_CLASSES = frozenset({"C3", "D2", "D5"})


def parse_arguments() -> argparse.Namespace:
    """Return the parsed command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=["all", *CHECKS], help="check name, or all")
    parser.add_argument("paths", nargs="*", type=Path, help="files or directories to scan")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--json", action="store_true", help="emit a JSON array")
    parser.add_argument("--added-lines", type=Path, help="JSON map of path to added line numbers")
    parser.add_argument("--changed-files", type=Path, help="file listing changed paths, one per line")
    return parser.parse_args()


def resolve_paths(paths: list[Path], root: Path) -> list[Path]:
    """Return resolved paths. Raise ValueError for paths outside the root."""
    resolved_root = root.resolve()
    resolved = []
    for path in paths or [root]:
        candidate = path.resolve()
        if candidate != resolved_root and resolved_root not in candidate.parents:
            raise ValueError(f"{path} resolves outside the repository root {root}")
        resolved.append(candidate)
    return resolved


def filter_added(findings: list[Finding], added_path: Path) -> list[Finding]:
    """Keep findings on added lines. Keep project-level findings unconditionally."""
    added = {path: set(lines) for path, lines in json.loads(added_path.read_text(encoding="utf-8")).items()}
    return [
        finding
        for finding in findings
        if finding.class_id in PROJECT_CLASSES or finding.line in added.get(finding.path, set())
    ]


def emit(findings: list[Finding], as_json: bool) -> None:
    """Write findings as text lines or a JSON array."""
    if as_json:
        payload = [
            {
                "id": f"P{index}",
                "file": item.path,
                "line": item.line,
                "class": item.class_id,
                "message": item.message,
                "blocking": item.blocking,
            }
            for index, item in enumerate(findings, 1)
        ]
        sys.stdout.write(json.dumps(payload, indent=JSON_INDENT) + "\n")
        return
    for item in findings:
        level = "error" if item.blocking else "warning"
        sys.stdout.write(f"{item.path}:{item.line}: {item.class_id} {level}: {item.message}\n")


def main() -> int:
    """Run the requested checks and return the exit status."""
    args = parse_arguments()
    try:
        paths = resolve_paths(args.paths, args.root)
    except ValueError as error:
        sys.stderr.write(f"error: {error}. Pass paths inside --root.\n")
        return EXIT_INVALID_INPUT
    changed = None
    if args.changed_files:
        changed = [line.strip() for line in args.changed_files.read_text(encoding="utf-8").splitlines() if line.strip()]
    names = list(CHECKS) if args.check == "all" else [args.check]
    findings = run_checks(names, paths, args.root, changed=changed)
    if args.added_lines:
        findings = filter_added(findings, args.added_lines)
    emit(findings, args.json)
    return EXIT_BLOCKING if any(item.blocking for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
