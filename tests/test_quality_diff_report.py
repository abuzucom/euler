"""Tests for scripts/quality_diff_report.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import quality_diff_report as report  # resolved through the path set above

BASE = "### Q1 Logic (Blocking)\n### Q2 Cache (Graded)\n### M2 Names (Advisory)\n"


class DiffReportTest(unittest.TestCase):
    def test_no_change(self) -> None:
        changes = report.compare_policies(BASE, BASE)
        self.assertEqual(changes, [])

    def test_tier_change_detected(self) -> None:
        head = BASE.replace("Q2 Cache (Graded)", "Q2 Cache (Blocking)")
        self.assertIn("Q2 tier: Graded -> Blocking", report.compare_policies(BASE, head))

    def test_added_and_removed_classes(self) -> None:
        head = BASE.replace("### M2 Names (Advisory)\n", "### M3 Purpose (Advisory)\n")
        changes = report.compare_policies(BASE, head)
        self.assertIn("M2 removed (Advisory)", changes)
        self.assertIn("M3 added (Advisory)", changes)

    def test_verdict_affecting_change_requires_eval_case(self) -> None:
        head = BASE.replace("Q2 Cache (Graded)", "Q2 Cache (Blocking)")
        changes = report.compare_policies(BASE, head)
        self.assertTrue(report.requires_eval_case(changes))
        self.assertFalse(report.has_eval_change(["QUALITY.md"]))
        self.assertTrue(report.has_eval_change(["QUALITY.md", "eval/cases/x/expected.json"]))

    def test_rename_does_not_require_eval_case(self) -> None:
        head = BASE.replace("Q2 Cache (Graded)", "Q2 Request cache (Graded)")
        changes = report.compare_policies(BASE, head)
        self.assertEqual(changes, ["Q2 renamed: Cache -> Request cache"])
        self.assertFalse(report.requires_eval_case(changes))


if __name__ == "__main__":
    unittest.main()
