"""Tests for ci/check_review_response.py."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ci import check_review_response as checker  # resolved through the path set above

POLICY = REPO_ROOT / "QUALITY.md"


def build_report(verdict: str, findings: list[dict], prescan: list[dict] | None = None, **overrides: object) -> str:
    """Return a report with a final line and a VERDICT_JSON companion."""
    payload = {"schema_version": "1", "mode": "PR", "verdict": verdict, "findings": findings, "prescan": prescan or []}
    payload.update(overrides)
    return f"Findings above.\n\nVERDICT: {verdict} - summary\nVERDICT_JSON: {json.dumps(payload)}\n"


def finding(class_id: str, severity: str = "HIGH", file: str = "app.py") -> dict:
    """Return one finding entry."""
    return {"severity": severity, "class": class_id, "file": file, "line": 3, "title": "t", "confidence": "certain"}


class ValidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classes = checker.load_classes(POLICY)
        self.context = checker.ReviewContext("PR", {"app.py"}, {"P1"}, [])

    def problems(self, report: str, context: checker.ReviewContext | None = None) -> list[str]:
        return checker.validate(report, context or self.context, self.classes)

    def dismissed(self) -> list[dict]:
        return [{"id": "P1", "status": "dismissed", "reason": "value clear from context"}]

    def test_valid_block_report(self) -> None:
        self.assertEqual(self.problems(build_report("BLOCK", [finding("M1")], self.dismissed())), [])

    def test_valid_clean_approve(self) -> None:
        self.assertEqual(self.problems(build_report("APPROVE", [], self.dismissed())), [])

    def test_two_final_lines_rejected(self) -> None:
        report = "VERDICT: APPROVE - a\n" + build_report("APPROVE", [], self.dismissed())
        self.assertIn("expected exactly one final VERDICT line, found 2", self.problems(report))

    def test_json_verdict_mismatch_rejected(self) -> None:
        report = build_report("APPROVE", [], self.dismissed()).replace('"verdict": "APPROVE"', '"verdict": "BLOCK"')
        self.assertIn("VERDICT_JSON verdict 'BLOCK' differs from final line 'APPROVE'", self.problems(report))

    def test_blocking_finding_requires_block(self) -> None:
        problems = self.problems(build_report("APPROVE", [finding("Q4")], self.dismissed()))
        self.assertIn("verdict APPROVE conflicts with tiers, expected BLOCK", problems)

    def test_escalate_finding_requires_needs_human(self) -> None:
        problems = self.problems(build_report("APPROVE", [finding("C2")], self.dismissed()))
        self.assertIn("verdict APPROVE conflicts with tiers, expected NEEDS-HUMAN", problems)

    def test_precedence_block_over_escalate(self) -> None:
        report = build_report("BLOCK", [finding("M1"), finding("C2")], self.dismissed())
        self.assertEqual(self.problems(report), [])

    def test_block_without_basis_rejected(self) -> None:
        problems = self.problems(build_report("BLOCK", [finding("M2", "LOW")], self.dismissed()))
        self.assertIn("verdict BLOCK conflicts with tiers, expected APPROVE or NEEDS-HUMAN", problems)

    def test_advisory_above_low_rejected(self) -> None:
        problems = self.problems(build_report("APPROVE", [finding("M2", "MEDIUM")], self.dismissed()))
        self.assertIn("advisory class M2 rated MEDIUM, ceiling is LOW", problems)

    def test_file_outside_diff_rejected(self) -> None:
        problems = self.problems(build_report("BLOCK", [finding("M1", file="other.py")], self.dismissed()))
        self.assertIn("finding cites other.py outside the changed files", problems)

    def test_unknown_class_rejected(self) -> None:
        problems = self.problems(build_report("APPROVE", [finding("Z1", "LOW")], self.dismissed()))
        self.assertIn("unknown class Z1", problems)

    def test_missing_confidence_rejected(self) -> None:
        entry = finding("M1")
        del entry["confidence"]
        self.assertIn("finding confidence must be certain or likely", self.problems(build_report("BLOCK", [entry], self.dismissed())))

    def test_schema_version_required(self) -> None:
        report = build_report("APPROVE", [], self.dismissed(), schema_version="2")
        self.assertIn("VERDICT_JSON schema_version must be '1'", self.problems(report))

    def test_unresolved_prescan_rejected(self) -> None:
        self.assertIn("prescan item P1 lacks a resolution", self.problems(build_report("APPROVE", [], [])))

    def test_unreviewed_files_forbid_approve(self) -> None:
        context = checker.ReviewContext("PR", {"app.py"}, set(), ["big.bin"])
        self.assertIn("unreviewed files forbid APPROVE", self.problems(build_report("APPROVE", []), context))


if __name__ == "__main__":
    unittest.main()
