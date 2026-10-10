#!/usr/bin/env python3
"""Validate the golden corpus, or run it against a model call.

Without --model-call the runner checks corpus structure only. With
--model-call module:function it sends every case to that callable and
compares the report with expected.json. The callable signature is
call_model(system_prompt: str, mode: str, case_text: str) -> str.

--model-call imports and executes code. Pass it only from a trusted local
invocation or trusted CI configuration.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_quality_policy  # resolved through the path set above
import quality_checks  # resolved through the path set above
import review_envelope  # resolved through the path set above
import review_report  # resolved through the path set above

MODES = ("PR", "File", "Piece", "Wholesale")
PR_VERDICTS = ("APPROVE", "BLOCK", "NEEDS-HUMAN")
RISK_PREFIXES = {"File": ("RISK:",), "Wholesale": ("RISK:",), "Piece": ("RISK (partial)", "NEEDS-HUMAN")}
EXPECTED_KEYS = ("mode", "expected_verdict", "expected_classes", "expect_json", "notes")
RESERVED_FILES = frozenset({"expected.json", "context.md"})
DEFAULT_CASES = REPO_ROOT / "eval" / "cases"
DEFAULT_POLICY = REPO_ROOT / "QUALITY.md"

ModelCall = Callable[[str, str, str], str]


@dataclass(frozen=True)
class Case:
    """One golden corpus case."""

    slug: str
    expected: dict
    files: dict[str, str]
    context: str


def load_case(case_dir: Path) -> Case:
    """Return the case stored in one directory."""
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    context_path = case_dir / "context.md"
    context = context_path.read_text(encoding="utf-8") if context_path.is_file() else ""
    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(case_dir.iterdir())
        if path.is_file() and path.name not in RESERVED_FILES
    }
    return Case(case_dir.name, expected, files, context)


def verdict_fits_mode(mode: str, verdict: str) -> bool:
    """Return True when the expected verdict matches the mode's final line."""
    if mode == "PR":
        return verdict in PR_VERDICTS
    return verdict.startswith(RISK_PREFIXES.get(mode, ()))


def validate_expected(case: Case, known_classes: set[str]) -> list[str]:
    """Return structure problems for one case's expected.json."""
    expected = case.expected
    problems = [f"missing key '{key}'" for key in EXPECTED_KEYS if key not in expected]
    if problems:
        return problems
    mode, verdict = expected["mode"], expected["expected_verdict"]
    if mode not in MODES:
        return [f"invalid mode '{mode}'"]
    if not verdict_fits_mode(mode, verdict):
        problems.append(f"verdict '{verdict}' does not fit mode {mode}")
    problems.extend(f"unknown class '{item}'" for item in expected["expected_classes"] if item not in known_classes)
    if not isinstance(expected["expect_json"], bool):
        problems.append("expect_json must be a boolean")
    if not isinstance(expected["notes"], str) or not expected["notes"].strip():
        problems.append("notes must be a non-empty string")
    narration_required = expected.get("forbid_process_narration")
    if "forbid_process_narration" in expected and not isinstance(narration_required, bool):
        problems.append("forbid_process_narration must be a boolean")
    return problems


def validate_fixtures(case: Case) -> list[str]:
    """Return fixture problems for one case."""
    if case.expected.get("mode") == "PR":
        return [] if "diff.patch" in case.files else ["PR mode requires diff.patch"]
    inputs = [name for name in case.files if name.startswith("input.")]
    return [] if inputs else ["non-PR mode requires an input.<ext> file"]


def validate_corpus(cases_dir: Path, policy_path: Path = DEFAULT_POLICY) -> list[str]:
    """Return every structure problem across the corpus."""
    known_classes = set(check_quality_policy.parse_classes(policy_path.read_text(encoding="ascii")))
    problems: list[str] = []
    case_dirs = sorted(path for path in cases_dir.iterdir() if path.is_dir())
    if not case_dirs:
        return [f"no cases under {cases_dir}"]
    for case_dir in case_dirs:
        if not (case_dir / "expected.json").is_file():
            problems.append(f"{case_dir.name}: missing expected.json")
            continue
        try:
            case = load_case(case_dir)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            problems.append(f"{case_dir.name}: unreadable case: {error}")
            continue
        issues = validate_expected(case, known_classes) + validate_fixtures(case)
        problems.extend(f"{case.slug}: {issue}" for issue in issues)
    return problems


def prescan_for(case: Case, case_dir: Path) -> list[dict]:
    """Return checker candidates for non-PR input files. PR cases carry no head tree."""
    if case.expected["mode"] == "PR":
        return []
    inputs = [case_dir / name for name in case.files if name.startswith("input.")]
    findings = quality_checks.run_checks(list(quality_checks.CHECKS), inputs, case_dir)
    return [
        {"id": f"P{index}", "file": item.path, "line": item.line, "class": item.class_id, "message": item.message}
        for index, item in enumerate(findings, 1)
    ]


def build_case_text(case: Case, case_dir: Path) -> str:
    """Return the review envelope for one case."""
    metadata = {"source": "eval", "case": case.slug}
    prescan = prescan_for(case, case_dir)
    return review_envelope.build_envelope(case.expected["mode"], case.files, case.context, prescan, metadata)


def evaluate_response(case: Case, response: str) -> list[str]:
    """Return mismatches between a model report and the case expectation."""
    report = review_report.parse_report(response)
    expected = case.expected
    failures = []
    final_line = f"{report.label}: {report.value}" if report.label else ""
    if expected.get("forbid_process_narration") and review_report.contains_process_narration(response):
        failures.append("report contains process narration")
    if expected["expected_verdict"] not in final_line:
        failures.append(f"expected verdict '{expected['expected_verdict']}' in final line '{final_line}'")
    if expected["expect_json"] and report.payload is None:
        failures.append(report.json_error or "missing VERDICT_JSON")
    if report.payload is not None:
        reported = {
            item.get("class")
            for item in report.payload.get("findings", [])
            if isinstance(item, dict) and isinstance(item.get("class"), str)
        }
        expected_classes = set(expected["expected_classes"])
        failures.extend(f"missing expected class {item}" for item in sorted(expected_classes - reported))
        failures.extend(f"unexpected class {item}" for item in sorted(reported - expected_classes))
    return failures


def load_model_call(spec: str) -> ModelCall:
    """Import module:function from a trusted specification."""
    module_name, _, function_name = spec.partition(":")
    if not module_name or not function_name:
        raise ValueError(f"--model-call must look like module:function, got '{spec}'")
    sys.path.insert(0, str(REPO_ROOT))
    return getattr(importlib.import_module(module_name), function_name)


def run_live(cases_dir: Path, policy_path: Path, model_call: ModelCall) -> int:
    """Run every case through the model and return the failure count."""
    system_prompt = policy_path.read_text(encoding="ascii")
    failures = 0
    for case_dir in sorted(path for path in cases_dir.iterdir() if path.is_dir()):
        case = load_case(case_dir)
        response = model_call(system_prompt, case.expected["mode"], build_case_text(case, case_dir))
        problems = evaluate_response(case, response)
        status = "FAIL" if problems else "pass"
        sys.stdout.write(f"{status:4} {case.slug}\n")
        for problem in problems:
            sys.stdout.write(f"       {problem}\n")
        failures += bool(problems)
    return failures


def main() -> int:
    """Validate the corpus and optionally run it live."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--model-call", help="trusted module:function for a live run")
    args = parser.parse_args()
    problems = validate_corpus(args.cases, args.policy)
    for problem in problems:
        sys.stderr.write(f"error: {problem}\n")
    if problems:
        return 1
    case_count = sum(1 for path in args.cases.iterdir() if path.is_dir())
    sys.stdout.write(f"ok       {case_count} cases, structure valid\n")
    if not args.model_call:
        return 0
    failures = run_live(args.cases, args.policy, load_model_call(args.model_call))
    sys.stdout.write(f"{case_count - failures}/{case_count} cases passed\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
