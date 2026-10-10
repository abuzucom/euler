"""Regression tests for process narration in review comments."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

from ci import check_review_response
from ci import run_review
import run_eval
import review_report


class ReviewNarrationTest(unittest.TestCase):
    def test_validator_rejects_process_narration(self) -> None:
        context = check_review_response.ReviewContext("PR", {"app.py"}, set(), [])
        classes = check_review_response.load_classes(REPO_ROOT / "QUALITY.md")
        report = (
            "I'll review this PR carefully.\n\n"
            "VERDICT: APPROVE - No findings.\n"
            "VERDICT_JSON: "
            + json.dumps({
                "schema_version": "1",
                "mode": "PR",
                "verdict": "APPROVE",
                "findings": [],
                "prescan": [],
            })
            + "\n"
        )
        problems = check_review_response.validate(report, context, classes)
        self.assertIn("report contains process narration", problems)

    def test_validator_allows_concise_conclusion_and_code_literal(self) -> None:
        context = check_review_response.ReviewContext("PR", {"app.py"}, set(), [])
        classes = check_review_response.load_classes(REPO_ROOT / "QUALITY.md")
        code_literal = chr(96) + "I need to verify this" + chr(96)
        report = (
            "Reviewed material: app.py. Unseen material: none.\n"
            "No confirmed findings.\n"
            "The string " + code_literal + " appears in a test fixture.\n\n"
            "VERDICT: APPROVE - No confirmed findings.\n"
            "VERDICT_JSON: "
            + json.dumps({
                "schema_version": "1",
                "mode": "PR",
                "verdict": "APPROVE",
                "findings": [],
                "prescan": [],
            })
            + "\n"
        )
        self.assertEqual(check_review_response.validate(report, context, classes), [])

    def test_eval_flags_process_narration_when_requested(self) -> None:
        case = run_eval.Case(
            "review-narration-pr",
            {
                "mode": "PR",
                "expected_verdict": "APPROVE",
                "expected_classes": [],
                "expect_json": True,
                "forbid_process_narration": True,
            },
            {},
            "",
        )
        report = (
            "Let me inspect the changed code first.\n"
            "VERDICT: APPROVE - No confirmed findings.\n"
            "VERDICT_JSON: "
            + json.dumps({
                "schema_version": "1",
                "mode": "PR",
                "verdict": "APPROVE",
                "findings": [],
                "prescan": [],
            })
        )
        self.assertTrue(any("process narration" in issue for issue in run_eval.evaluate_response(case, report)))

    def test_persistent_narration_is_not_returned_for_comment(self) -> None:
        envelope = json.dumps({
            "mode": "PR",
            "REVIEW_TARGET": {"files": ["app.py"]},
            "TRUSTED_CONTEXT": {"prescan": []},
        })
        calls = 0

        def narrated_model(system_prompt: str, mode: str, case_text: str) -> str:
            nonlocal calls
            calls += 1
            return (
                "I'll review this PR carefully.\n"
                "VERDICT: APPROVE - No findings.\n"
                "VERDICT_JSON: "
                + json.dumps({
                    "schema_version": "1",
                    "mode": "PR",
                    "verdict": "APPROVE",
                    "findings": [],
                    "prescan": [],
                })
            )

        result = run_review.review_chunk(
            "chunk-001",
            envelope,
            [],
            REPO_ROOT / "QUALITY.md",
            narrated_model,
        )
        self.assertEqual(calls, 2)
        self.assertEqual(result.verdict, "NEEDS-HUMAN")
        self.assertEqual(result.report, "")
        self.assertIn("report contains process narration", result.problems)
        comment = run_review.render_report(
            {
                "base_sha": "base",
                "head_sha": "head",
                "unreviewed": [],
            },
            [result],
            [],
            result.verdict,
        )
        self.assertNotIn("I'll review", comment)
        self.assertIn("Validation: report contains process narration", comment)

    def test_narration_detector_ignores_code_spans(self) -> None:
        code_literal = chr(96) + "I need to check" + chr(96)
        self.assertFalse(review_report.contains_process_narration("The fixture contains " + code_literal + "."))
        self.assertTrue(review_report.contains_process_narration("Actually, I need to check this."))
        self.assertTrue(review_report.contains_process_narration("I only see changed lines."))
        self.assertTrue(review_report.contains_process_narration("Need to verify each item."))


if __name__ == "__main__":
    unittest.main()