#!/usr/bin/env python3
"""Validate a model review report against QUALITY.md tiers and the envelope.

A report passes only with one final line, a matching VERDICT_JSON, known
classes, tier-consistent severities and verdict, changed-file locations, and
a resolution for every prescan item.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_quality_policy  # resolved through the path set above
import review_report  # resolved through the path set above

SCHEMA_VERSION = "1"
SEVERITIES = ("HIGH", "MEDIUM", "LOW")
CONFIDENCES = ("certain", "likely")
PRESCAN_STATUSES = ("confirmed", "dismissed")
VERDICT_RANK = {"APPROVE": 0, "NEEDS-HUMAN": 1, "BLOCK": 2}


@dataclass(frozen=True)
class ReviewContext:
    """Envelope facts the report must agree with."""

    mode: str
    changed_files: set[str]
    prescan_ids: set[str]
    unreviewed: list[str]


def load_classes(policy_path: Path) -> dict[str, check_quality_policy.PolicyClass]:
    """Return the QUALITY.md classes keyed by ID."""
    return check_quality_policy.parse_classes(policy_path.read_text(encoding="ascii"))


def finding_problems(item: object, context: ReviewContext, classes: dict) -> list[str]:
    """Return problems for one VERDICT_JSON finding."""
    if not isinstance(item, dict):
        return ["finding must be a JSON object"]
    problems = []
    class_id, severity = item.get("class"), item.get("severity")
    policy_class = classes.get(class_id)
    if policy_class is None:
        problems.append(f"unknown class {class_id}")
    if severity not in SEVERITIES:
        problems.append(f"finding severity must be one of {', '.join(SEVERITIES)}")
    elif policy_class and policy_class.tier == "Advisory" and severity != "LOW":
        problems.append(f"advisory class {class_id} rated {severity}, ceiling is LOW")
    if item.get("confidence") not in CONFIDENCES:
        problems.append("finding confidence must be certain or likely")
    if not isinstance(item.get("line"), int):
        problems.append("finding line must be an integer")
    if context.mode == "PR" and item.get("file") not in context.changed_files:
        problems.append(f"finding cites {item.get('file')} outside the changed files")
    return problems


def required_verdict(findings: list[dict], classes: dict) -> str:
    """Return the minimum verdict the tiers demand."""
    tiers = [(classes[item["class"]].tier, item.get("severity")) for item in findings if item.get("class") in classes]
    if any(tier == "Blocking" or (tier == "Graded" and severity == "HIGH") for tier, severity in tiers):
        return "BLOCK"
    if any(tier == "Escalate" for tier, _ in tiers):
        return "NEEDS-HUMAN"
    return "APPROVE"


def verdict_problems(verdict: str, findings: list[dict], context: ReviewContext, classes: dict) -> list[str]:
    """Return problems where the verdict disagrees with tiers or coverage."""
    required = required_verdict([item for item in findings if isinstance(item, dict)], classes)
    problems = []
    if verdict not in VERDICT_RANK:
        return [f"unknown verdict token {verdict}"]
    if required == "BLOCK" and verdict != "BLOCK":
        problems.append(f"verdict {verdict} conflicts with tiers, expected BLOCK")
    elif required == "NEEDS-HUMAN" and verdict != "NEEDS-HUMAN":
        problems.append(f"verdict {verdict} conflicts with tiers, expected NEEDS-HUMAN")
    elif required == "APPROVE" and verdict == "BLOCK":
        problems.append("verdict BLOCK conflicts with tiers, expected APPROVE or NEEDS-HUMAN")
    if context.unreviewed and verdict == "APPROVE":
        problems.append("unreviewed files forbid APPROVE")
    return problems


def prescan_problems(entries: object, context: ReviewContext) -> list[str]:
    """Return problems in the prescan resolution array."""
    if not isinstance(entries, list):
        return ["VERDICT_JSON prescan must be an array"]
    resolved = set()
    problems = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") not in PRESCAN_STATUSES or not entry.get("reason"):
            problems.append("prescan entries need an id, a confirmed or dismissed status, and a reason")
            continue
        resolved.add(entry.get("id"))
    problems.extend(f"prescan item {item} lacks a resolution" for item in sorted(context.prescan_ids - resolved))
    return problems


def validate(text: str, context: ReviewContext, classes: dict) -> list[str]:
    """Return every problem in one report. An empty list means valid."""
    report = review_report.parse_report(text)
    problems = []
    if review_report.contains_process_narration(text):
        problems.append("report contains process narration")
    if context.mode == "PR" and (report.label != "VERDICT" or report.final_line_count != 1):
        problems.append(f"expected exactly one final VERDICT line, found {report.final_line_count}")
    if report.payload is None:
        return problems + [report.json_error or "missing VERDICT_JSON"]
    payload = report.payload
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"VERDICT_JSON schema_version must be '{SCHEMA_VERSION}'")
    if payload.get("verdict") != report.token:
        problems.append(f"VERDICT_JSON verdict '{payload.get('verdict')}' differs from final line '{report.token}'")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return problems + ["VERDICT_JSON findings must be an array"]
    for item in findings:
        problems.extend(finding_problems(item, context, classes))
    if context.mode == "PR" and report.token:
        problems.extend(verdict_problems(report.token, findings, context, classes))
    problems.extend(prescan_problems(payload.get("prescan", []), context))
    return problems


def context_from_envelope(envelope: dict, unreviewed: list[str]) -> ReviewContext:
    """Return the validation context for one envelope."""
    target = envelope["REVIEW_TARGET"]
    prescan = envelope["TRUSTED_CONTEXT"].get("prescan", [])
    return ReviewContext(envelope["mode"], set(target["files"]), {item["id"] for item in prescan}, unreviewed)


def main() -> int:
    """Validate one report file against one envelope file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("envelope", type=Path)
    parser.add_argument("--policy", type=Path, default=REPO_ROOT / "QUALITY.md")
    args = parser.parse_args()
    envelope = json.loads(args.envelope.read_text(encoding="utf-8"))
    context = context_from_envelope(envelope, [])
    problems = validate(args.report.read_text(encoding="utf-8"), context, load_classes(args.policy))
    for problem in problems:
        sys.stderr.write(f"error: {problem}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
