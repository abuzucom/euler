"""Tests for false-positive detection in live golden-corpus evaluation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "eval"))

import run_eval  # resolved through the path set above


class FalsePositiveEvaluationTests(unittest.TestCase):
    """Require exact class matches for clean expected reviews."""

    def test_unexpected_finding_class_fails_clean_case(self) -> None:
        expected = {
            "mode": "PR",
            "expected_verdict": "APPROVE",
            "expected_classes": [],
            "expect_json": True,
        }
        case = run_eval.Case("resolved-q4-pr", expected, {}, "")
        response = (
            "VERDICT: APPROVE - The fix resolves division by zero.\n"
            'VERDICT_JSON: {"schema_version":"1","mode":"PR",'
            '"verdict":"APPROVE","findings":[{"class":"Q4"}],"prescan":[]}\n'
        )

        failures = run_eval.evaluate_response(case, response)

        self.assertIn("unexpected class Q4", failures)


if __name__ == "__main__":
    unittest.main()
