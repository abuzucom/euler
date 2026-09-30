#!/usr/bin/env python3
"""Build review envelopes for one pull request without checking out its head.

The builder reads the base-to-head diff and the head tree from git objects.
It runs the deterministic checkers on an extracted copy of the head tree and
keeps candidates on added lines. It splits large diffs by file into chunks.
Binary files, single files over the budget, and files past the chunk limit
become unreviewed files.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
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
# Each chunk costs up to two model calls. Files in chunks past the limit become unreviewed.
DEFAULT_MAX_CHUNKS = 20
BINARY_NUMSTAT = b"-"
# numstat rows hold added, deleted, and path fields.
NUMSTAT_SPLITS = 2
# ls-tree metadata holds mode, type, and object ID fields.
LS_TREE_FIELDS = 3
# cat-file --batch headers hold object ID, type, and size fields.
CAT_FILE_HEADER_FIELDS = 3
REGULAR_FILE_MODES = frozenset({b"100644", b"100755"})
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
    max_chunks: int = DEFAULT_MAX_CHUNKS


def git_executable() -> str:
    """Return the absolute path of git on PATH."""
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git not found on PATH. Install git before the build.")
    return executable


def run_git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Run git with an argument array and return raw stdout.

    GIT_LITERAL_PATHSPECS stops a pull request path such as '*' or ':(glob)x' from acting as a pattern.
    """
    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1"}
    command = [git_executable(), "-C", str(repo), *args]
    result = subprocess.run(command, input=stdin, capture_output=True, check=False, env=env)
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


def decode_paths(raw: bytes) -> tuple[list[str], list[str]]:
    """Split NUL-terminated git paths into UTF-8 names and replacement-decoded undecodable names."""
    paths: list[str] = []
    undecodable: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            paths.append(item.decode("utf-8"))
        except UnicodeDecodeError:
            undecodable.append(item.decode("utf-8", errors="replace"))
    return paths, undecodable


def read_binary_paths(options: BuildOptions) -> set[str]:
    """Return the changed paths that git reports as binary."""
    raw = run_git(options.repo, "diff", "-z", "--numstat", "--no-renames", options.base, options.head)
    binary = set()
    for record in raw.split(b"\0"):
        fields = record.split(b"\t", NUMSTAT_SPLITS)
        if len(fields) == NUMSTAT_SPLITS + 1 and fields[0] == BINARY_NUMSTAT:
            binary.add(fields[NUMSTAT_SPLITS].decode("utf-8", errors="replace"))
    return binary


def read_diff(options: BuildOptions) -> tuple[list[str], set[str], dict[str, str], list[str]]:
    """Return changed paths, binary paths, per-file patches, and undecodable paths.

    NUL-separated output keeps paths with spaces, quotes, or non-ASCII bytes whole. Git cannot take an
    undecodable name back as an argument here, so such a path gets no patch.
    """
    revisions = (options.base, options.head)
    raw = run_git(options.repo, "diff", "-z", "--name-only", "--no-renames", *revisions)
    paths, undecodable = decode_paths(raw)
    binary = read_binary_paths(options)
    patches = {
        path: run_git(options.repo, "diff", "--no-color", "--no-renames", *revisions, "--", path).decode(
            "utf-8", errors="replace"
        )
        for path in paths
        if path not in binary
    }
    return paths + undecodable, binary, patches, undecodable


def split_empty_patches(patches: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Return non-empty patches and the paths whose patch came back empty.

    Every real text change carries at least a diff header, so an empty patch means git never saw the path.
    """
    kept = {path: patch for path, patch in patches.items() if patch}
    return kept, [path for path in patches if not patches[path]]


def limit_chunks(chunks: list[list[str]], max_chunks: int) -> tuple[list[list[str]], list[str]]:
    """Return the first max_chunks chunks and the files of the chunks past the limit."""
    return chunks[:max_chunks], [path for chunk in chunks[max_chunks:] for path in chunk]


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


def list_head_blobs(options: BuildOptions) -> list[tuple[str, str]]:
    """Return object ID and path pairs for the regular files in the head tree."""
    raw = run_git(options.repo, "ls-tree", "-r", "-z", "--full-tree", options.head)
    blobs = []
    for record in raw.split(b"\0"):
        meta, _, raw_path = record.partition(b"\t")
        fields = meta.split(b" ")
        if len(fields) != LS_TREE_FIELDS or fields[0] not in REGULAR_FILE_MODES:
            continue
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            # read_diff already lists an undecodable changed path as unreviewed.
            continue
        blobs.append((fields[2].decode("ascii"), path))
    return blobs


def read_blobs(object_ids: list[str], repo: Path) -> list[bytes]:
    """Return blob bodies in request order from one git cat-file --batch call.

    Each object arrives as an '<id> <type> <size>' header line, exactly size body bytes, and one newline.
    The size field locates the next header, so newlines inside a body never shift the parse.
    """
    request = "".join(f"{object_id}\n" for object_id in object_ids).encode("ascii")
    output = run_git(repo, "cat-file", "--batch", stdin=request)
    bodies = []
    offset = 0
    for object_id in object_ids:
        header_end = output.index(b"\n", offset)
        header = output[offset:header_end].split(b" ")
        if len(header) != CAT_FILE_HEADER_FIELDS or header[1] != b"blob":
            raise RuntimeError(f"git cat-file returned no blob for {object_id}. Fetch the head revision.")
        start = header_end + len(b"\n")
        end = start + int(header[2])
        bodies.append(output[start:end])
        offset = end + len(b"\n")
    return bodies


def extract_head(options: BuildOptions, target: Path) -> None:
    """Write the head tree's regular files into target straight from git objects.

    git archive would apply the head commit's export-ignore and export-subst attributes, which lets a pull
    request hide or rewrite files before the prescan reads them. Symlinks and submodules stay unwritten.
    """
    blobs = list_head_blobs(options)
    root = target.resolve()
    # Check every destination before the first write.
    destinations = [(root / path).resolve() for _, path in blobs]
    for (_, path), destination in zip(blobs, destinations):
        if not destination.is_relative_to(root):
            raise RuntimeError(f"head tree path {path!r} escapes the extraction directory. Review it by hand.")
    bodies = read_blobs([object_id for object_id, _ in blobs], options.repo)
    for destination, body in zip(destinations, bodies):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)


def is_excluded(path: str, exclude: list[str]) -> bool:
    """Return True when a glob in exclude matches the path."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in exclude)


def keep_finding(
    item: quality_checks.Finding, changed: set[str], added: dict[str, list[int]], exclude: list[str]
) -> bool:
    """Return True for findings in changed, non-excluded files on added lines."""
    if item.path not in changed or is_excluded(item.path, exclude):
        return False
    return item.class_id in PROJECT_CLASSES or item.line in added.get(item.path, [])


def present_paths(tree: Path, paths: list[str]) -> list[str]:
    """Return the paths that exist as regular files in the extracted tree."""
    return [path for path in paths if (tree / path).is_file()]


def build_prescan(options: BuildOptions, changed: list[str], patches: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Return prescan candidates with global IDs and the scanned files that exhaust the parsers."""
    added = {path: parse_added_lines(patch) for path, patch in patches.items()}
    with tempfile.TemporaryDirectory() as temp_dir:
        tree = Path(temp_dir)
        extract_head(options, tree)
        scanned = [path for path in changed if path in patches and not is_excluded(path, options.exclude)]
        present = [tree / path for path in present_paths(tree, scanned)]
        findings = quality_checks.run_checks(FILE_CHECKS, present, tree, changed=changed)
        findings += quality_checks.run_checks(PROJECT_CHECKS, [tree], tree, changed=changed)
        unparsed = [path for path in present_paths(tree, scanned) if quality_checks.exceeds_parser_limits(tree / path)]
    kept = [item for item in findings if keep_finding(item, set(changed), added, options.exclude)]
    prescan = [
        {
            "id": f"P{index}",
            "file": item.path,
            "line": item.line,
            "class": item.class_id,
            "message": item.message,
            "blocking": item.blocking,
        }
        for index, item in enumerate(kept, 1)
    ]
    return prescan, unparsed


def write_json(path: Path, data: object) -> None:
    """Write JSON with a trailing newline."""
    path.write_text(json.dumps(data, indent=JSON_INDENT) + "\n", encoding="utf-8")


def build(options: BuildOptions) -> None:
    """Write envelopes, prescan.json, and manifest.json to the output directory."""
    for revision in (options.base, options.head):
        if not FULL_SHA.match(revision):
            raise ValueError(f"revision {revision!r} is not a full lowercase commit SHA")
    if options.max_chunks < 1:
        raise ValueError(f"max_chunks {options.max_chunks} is below 1. Pass a positive chunk limit.")
    changed, binary, patches, undecodable = read_diff(options)
    patches, empty = split_empty_patches(patches)
    chunks, oversized = pack_chunks(patches, options.max_chars)
    chunks, overflow = limit_chunks(chunks, options.max_chunks)
    prescan, unparsed = build_prescan(options, changed, patches)
    undecodable_text = [path for path in undecodable if path not in binary]
    unreviewed = sorted(binary) + undecodable_text + empty + oversized + overflow + unparsed
    envelopes_dir = options.out_dir / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    context = f"Title: {options.title}\n\n{options.body}"
    manifest_chunks = []
    for index, files in enumerate(chunks, 1):
        metadata = {
            "pr_number": options.pr_number,
            "base_sha": options.base,
            "head_sha": options.head,
            "chunk": f"{index}/{len(chunks)}",
            "changed_files": changed,
            "unreviewed": unreviewed,
        }
        chunk_prescan = [item for item in prescan if item["file"] in files]
        text = review_envelope.build_envelope(
            "PR", {path: patches[path] for path in files}, context, chunk_prescan, metadata
        )
        name = f"{index:03d}.json"
        (envelopes_dir / name).write_text(text, encoding="utf-8")
        manifest_chunks.append({"envelope": name, "files": files})
    write_json(options.out_dir / "prescan.json", prescan)
    manifest = {
        "base_sha": options.base,
        "head_sha": options.head,
        "pr_number": options.pr_number,
        "changed_files": changed,
        "unreviewed": unreviewed,
        "chunks": manifest_chunks,
    }
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
    parser.add_argument("--max-chunks", type=int, default=DEFAULT_MAX_CHUNKS)
    args = parser.parse_args()
    options = BuildOptions(
        repo=args.repo,
        base=args.base,
        head=args.head,
        out_dir=args.out_dir,
        title=os.environ.get("PR_TITLE", ""),
        body=os.environ.get("PR_BODY", ""),
        pr_number=args.pr_number,
        exclude=args.exclude.split(),
        max_chars=args.max_chars,
        max_chunks=args.max_chunks,
    )
    try:
        build(options)
    except (ValueError, RuntimeError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
