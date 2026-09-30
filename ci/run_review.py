#!/usr/bin/env python3
"""Run the model review over built envelopes, then write the report and result.

Subcommands:
- review: call the model per envelope, validate, retry once, and merge.
- gate: exit 1 when the result blocks and fail_on_block is true.

The worst chunk verdict wins. A blocking prescan finding forces BLOCK.
Unreviewed files, model errors, and twice-invalid reports force at least
NEEDS-HUMAN.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import review_report  # resolved through the path set above

from ci import check_review_response  # resolved through the path set above
from ci.call_model import ModelCallError  # resolved through the path set above

DEFAULT_MODEL_CALL = "ci.call_model:call_model"
VERDICT_RANK = check_review_response.VERDICT_RANK
BLOCKING_VERDICTS = frozenset({"BLOCK", "NEEDS-HUMAN"})
FENCE_RUN = re.compile(r"`{3,}")
MIN_FENCE = 3
JSON_INDENT = 2
# One first attempt plus one retry after a validation failure.
MAX_ATTEMPTS = 2
REPORT_MARKER = "<!-- euler-quality-review -->"
# Caps keep the comment under GitHub's 65536-character body limit.
MAX_LISTED_ITEMS = 50
MAX_ITEM_CHARS = 300

ModelCall = Callable[[str, str, str], str]


@dataclass
class ChunkResult:
    """Outcome of one envelope review."""

    envelope: str
    verdict: str
    report: str
    problems: list[str]


def worst(verdicts: list[str]) -> str:
    """Return the highest-ranked verdict."""
    return max(verdicts, key=VERDICT_RANK.__getitem__, default="APPROVE")


def with_retry_note(envelope_text: str, problems: list[str]) -> str:
    """Return the envelope with a trusted note listing validation problems."""
    envelope = json.loads(envelope_text)
    envelope["TRUSTED_CONTEXT"]["RETRY"] = {
        "note": "The previous report failed validation. Emit a corrected full report.",
        "problems": problems,
    }
    return json.dumps(envelope, indent=JSON_INDENT, ensure_ascii=False)


def review_chunk(name: str, envelope_text: str, unreviewed: list[str], policy: Path, model: ModelCall) -> ChunkResult:
    """Review one envelope with one retry on an invalid report."""
    classes = check_review_response.load_classes(policy)
    system_prompt = policy.read_text(encoding="ascii")
    context = check_review_response.context_from_envelope(json.loads(envelope_text), unreviewed)
    case_text = envelope_text
    report, problems = "", []
    for _attempt in range(MAX_ATTEMPTS):
        try:
            report = model(system_prompt, "PR", case_text)
        except ModelCallError as error:
            return ChunkResult(name, "NEEDS-HUMAN", "", [f"model call failed: {error}"])
        problems = check_review_response.validate(report, context, classes)
        if not problems:
            parsed = review_report.parse_report(report)
            return ChunkResult(name, parsed.token or "NEEDS-HUMAN", report, [])
        case_text = with_retry_note(envelope_text, problems)
    return ChunkResult(name, "NEEDS-HUMAN", report, problems)


def fence(text: str) -> str:
    """Return text inside a fence longer than any backtick run it holds."""
    longest = max((len(match.group(0)) for match in FENCE_RUN.finditer(text)), default=0)
    marker = "`" * max(MIN_FENCE, longest + 1)
    return f"{marker}text\n{text.rstrip()}\n{marker}"


def fenced_list(items: list[str]) -> str:
    """Return capped items one per line inside a fence.

    Paths, prescan messages, and validation problems carry pull request or model text. A fence keeps that
    text from rendering as markdown in the posted comment.
    """
    shown = [" ".join(item.split())[:MAX_ITEM_CHARS] for item in items[:MAX_LISTED_ITEMS]]
    if len(items) > MAX_LISTED_ITEMS:
        shown.append(f"... and {len(items) - MAX_LISTED_ITEMS} more")
    return fence("\n".join(shown))


def final_verdict(chunks: list[ChunkResult], prescan: list[dict], unreviewed: list[str]) -> str:
    """Merge chunk verdicts with prescan blockers and coverage."""
    verdicts = [chunk.verdict for chunk in chunks]
    if any(item.get("blocking") for item in prescan):
        verdicts.append("BLOCK")
    if unreviewed or not chunks:
        verdicts.append("NEEDS-HUMAN")
    return worst(verdicts)


def render_report(manifest: dict, chunks: list[ChunkResult], prescan: list[dict], verdict: str) -> str:
    """Return the markdown PR comment."""
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    lines = [REPORT_MARKER, f"## Euler quality review: {verdict}", ""]
    lines.append(f"Base `{manifest['base_sha']}`. Head `{manifest['head_sha']}`.")
    if run_id:
        lines.append(f"Workflow run: {server}/{repository}/actions/runs/{run_id}")
    blocking = [
        f"{item['file']}:{item['line']} {item['class']}: {item['message']}" for item in prescan if item.get("blocking")
    ]
    if blocking:
        lines += ["", "### Blocking prescan findings", "", fenced_list(blocking)]
    if manifest["unreviewed"]:
        lines += ["", "### Unreviewed files", "", fenced_list(manifest["unreviewed"])]
    for chunk in chunks:
        lines += ["", f"### Chunk {chunk.envelope}: {chunk.verdict}", ""]
        if chunk.problems:
            lines += ["Validation problems:", "", fenced_list(chunk.problems)]
        if chunk.report:
            lines += ["", fence(chunk.report)]
    return "\n".join(lines) + "\n"


def run(review_dir: Path, policy: Path, model: ModelCall) -> str:
    """Review every envelope, write report.md and result.json, and return the verdict."""
    manifest = json.loads((review_dir / "manifest.json").read_text(encoding="utf-8"))
    prescan = json.loads((review_dir / "prescan.json").read_text(encoding="utf-8"))
    chunks = []
    for chunk in manifest["chunks"]:
        envelope_text = (review_dir / "envelopes" / chunk["envelope"]).read_text(encoding="utf-8")
        chunks.append(review_chunk(chunk["envelope"], envelope_text, manifest["unreviewed"], policy, model))
    verdict = final_verdict(chunks, prescan, manifest["unreviewed"])
    (review_dir / "report.md").write_text(render_report(manifest, chunks, prescan, verdict), encoding="utf-8")
    result = {
        "verdict": verdict,
        "base_sha": manifest["base_sha"],
        "head_sha": manifest["head_sha"],
        "unreviewed": manifest["unreviewed"],
        "blocking_prescan": sum(1 for item in prescan if item.get("blocking")),
        "chunks": [
            {"envelope": chunk.envelope, "verdict": chunk.verdict, "problems": chunk.problems} for chunk in chunks
        ],
    }
    (review_dir / "result.json").write_text(json.dumps(result, indent=JSON_INDENT) + "\n", encoding="utf-8")
    return verdict


def gate_status(verdict: str, fail_on_block: bool) -> int:
    """Return the gate exit status for a verdict."""
    return 1 if fail_on_block and verdict in BLOCKING_VERDICTS else 0


def load_model_call(spec: str) -> ModelCall:
    """Import a trusted module:function model callable."""
    module_name, _, function_name = spec.partition(":")
    return getattr(importlib.import_module(module_name), function_name)


def main() -> int:
    """Dispatch the review and gate subcommands."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review")
    review.add_argument("--review-dir", type=Path, required=True)
    review.add_argument("--policy", type=Path, default=REPO_ROOT / "QUALITY.md")
    gate = commands.add_parser("gate")
    gate.add_argument("result", type=Path)
    gate.add_argument("--fail-on-block", choices=["true", "false"], default="true")
    args = parser.parse_args()
    if args.command == "gate":
        verdict = json.loads(args.result.read_text(encoding="utf-8"))["verdict"]
        sys.stdout.write(f"quality review verdict: {verdict}\n")
        return gate_status(verdict, args.fail_on_block == "true")
    verdict = run(args.review_dir, args.policy, load_model_call(DEFAULT_MODEL_CALL))
    sys.stdout.write(f"quality review verdict: {verdict}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
