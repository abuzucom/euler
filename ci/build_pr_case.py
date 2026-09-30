#!/usr/bin/env python3
"""Build review envelopes for one pull request without checking out its head.

The builder reads the base-to-head diff and the head tree from git objects.
It runs the deterministic checkers on an extracted copy of the head tree and
keeps candidates on added lines. It splits large diffs by file into chunks.
Binary files and single files over the budget become unreviewed files.
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import quality_checks  # resolved through the path set above
import review_envelope  # resolved through the path set above

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")
DEFAULT_MAX_CHARS = 120_000
BINARY_NUMSTAT = "-"
# numstat rows hold added, deleted, and path fields.
NUMSTAT_SPLITS = 2
JSON_INDENT = 2
PROJECT_CHECKS = [name for name, check in quality_checks.CHECKS.items() if check.project_check is not None]
FILE_CHECKS = [name for name in quality_checks.CHECKS if name not in PROJECT_CHECKS]
PROJECT_CLASSES = {quality_checks.CHECKS[name].class_id for name in PROJECT_CHECKS}


@dataclass(frozen=True)
class BuildOptions:
    """Inputs for one envelope build."""

    repo: Path
    base: str
    head: str
    out_dir: Path
    title: str
    body: str
    pr_number: int
    exclude: list[str] = field(default_factory=list)
    max_chars: int = DEFAULT_MAX_CHARS


def run_git(repo: Path, *args: str) -> bytes:
    """Run git with an argument array and return raw stdout."""
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {detail}. Fetch both revisions before the build.")
    return result.stdout


def parse_added_lines(patch: str) -> list[int]:
    """Return head line numbers of added lines in one file patch."""
    added = []
    line_number = 0
    for line in patch.splitlines():
        header = HUNK_HEADER.match(line)
        if header:
            line_number = int(header.group("start"))
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line_number)
            line_number += 1
        elif line.startswith(" "):
            line_number += 1
    return added


def read_diff(options: BuildOptions) -> tuple[list[str], set[str], dict[str, str]]:
    """Return changed paths, binary paths, and per-file patches."""
    revisions = (options.base, options.head)
    changed = run_git(options.repo, "diff", "--name-only", "--no-renames", *revisions).decode().split()
    binary = set()
    for row in run_git(options.repo, "diff", "--numstat", "--no-renames", *revisions).decode().splitlines():
        added, _, path = row.split("\t", NUMSTAT_SPLITS)
        if added == BINARY_NUMSTAT:
            binary.add(path)
    patches = {
        path: run_git(options.repo, "diff", "--no-color", "--no-renames", *revisions, "--", path).decode(
            "utf-8", errors="replace"
        )
        for path in changed
        if path not in binary
    }
    return changed, binary, patches


def pack_chunks(patches: dict[str, str], max_chars: int) -> tuple[list[list[str]], list[str]]:
    """Group files into chunks under the budget. Return chunks and oversized files."""
    chunks: list[list[str]] = []
    oversized = []
    current: list[str] = []
    size = 0
    for path, patch in patches.items():
        if len(patch) > max_chars:
            oversized.append(path)
            continue
        if current and size + len(patch) > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(path)
        size += len(patch)
    if current:
        chunks.append(current)
    return chunks, oversized


def extract_head(options: BuildOptions, target: Path) -> None:
    """Extract the head tree into target with the tarfile data filter."""
    archive = run_git(options.repo, "archive", "--format=tar", options.head)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="data")


def is_excluded(path: str, exclude: list[str]) -> bool:
    """Return True when a glob in exclude matches the path."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in exclude)


def keep_finding(item: quality_checks.Finding, changed: set[str], added: dict[str, list[int]], exclude: list[str]) -> bool:
    """Return True for findings in changed, non-excluded files on added lines."""
    if item.path not in changed or is_excluded(item.path, exclude):
        return False
    return item.class_id in PROJECT_CLASSES or item.line in added.get(item.path, [])


def build_prescan(options: BuildOptions, changed: list[str], patches: dict[str, str]) -> list[dict]:
    """Return prescan candidates with global IDs."""
    added = {path: parse_added_lines(patch) for path, patch in patches.items()}
    with tempfile.TemporaryDirectory() as temp_dir:
        tree = Path(temp_dir)
        extract_head(options, tree)
        scanned = [path for path in changed if path in patches and not is_excluded(path, options.exclude)]
        present = [tree / path for path in scanned if (tree / path).is_file()]
        findings = quality_checks.run_checks(FILE_CHECKS, present, tree, changed=changed)
        findings += quality_checks.run_checks(PROJECT_CHECKS, [tree], tree, changed=changed)
    kept = [item for item in findings if keep_finding(item, set(changed), added, options.exclude)]
    return [
        {"id": f"P{index}", "file": item.path, "line": item.line, "class": item.class_id,
         "message": item.message, "blocking": item.blocking}
        for index, item in enumerate(kept, 1)
    ]


def write_json(path: Path, data: object) -> None:
    """Write JSON with a trailing newline."""
    path.write_text(json.dumps(data, indent=JSON_INDENT) + "\n", encoding="utf-8")


def build(options: BuildOptions) -> None:
    """Write envelopes, prescan.json, and manifest.json to the output directory."""
    for revision in (options.base, options.head):
        if not FULL_SHA.match(revision):
            raise ValueError(f"revision {revision!r} is not a full lowercase commit SHA")
    changed, binary, patches = read_diff(options)
    chunks, oversized = pack_chunks(patches, options.max_chars)
    unreviewed = sorted(binary) + oversized
    prescan = build_prescan(options, changed, patches)
    envelopes_dir = options.out_dir / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    context = f"Title: {options.title}\n\n{options.body}"
    manifest_chunks = []
    for index, files in enumerate(chunks, 1):
        metadata = {"pr_number": options.pr_number, "base_sha": options.base, "head_sha": options.head,
                    "chunk": f"{index}/{len(chunks)}", "changed_files": changed, "unreviewed": unreviewed}
        chunk_prescan = [item for item in prescan if item["file"] in files]
        text = review_envelope.build_envelope("PR", {path: patches[path] for path in files}, context, chunk_prescan, metadata)
        name = f"{index:03d}.json"
        (envelopes_dir / name).write_text(text, encoding="utf-8")
        manifest_chunks.append({"envelope": name, "files": files})
    write_json(options.out_dir / "prescan.json", prescan)
    manifest = {"base_sha": options.base, "head_sha": options.head, "pr_number": options.pr_number,
                "changed_files": changed, "unreviewed": unreviewed, "chunks": manifest_chunks}
    write_json(options.out_dir / "manifest.json", manifest)


def main() -> int:
    """Build envelopes from command line options and environment PR text."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--exclude", default="", help="whitespace-separated globs skipped by the prescan")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()
    options = BuildOptions(
        repo=args.repo, base=args.base, head=args.head, out_dir=args.out_dir,
        title=os.environ.get("PR_TITLE", ""), body=os.environ.get("PR_BODY", ""), pr_number=args.pr_number,
        exclude=args.exclude.split(), max_chars=args.max_chars,
    )
    try:
        build(options)
    except (ValueError, RuntimeError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
