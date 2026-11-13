"""Contract checks for the QUALITY.md diff report and the Dependabot scope."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT_PATH = ROOT / ".github" / "dependabot.yml"
REPORT_STEP = "      - name: QUALITY.md diff report"
STEP_PREFIX = "      - "


def extract_step(workflow: str, marker: str) -> str:
    """Return one workflow step block that starts at the marker line."""
    lines = workflow.splitlines()
    start = lines.index(marker)
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith(STEP_PREFIX)), len(lines))
    return "\n".join(lines[start:end])


def extract_update(dependabot: str, ecosystem: str) -> str:
    """Return one Dependabot update entry by its package ecosystem."""
    entries = dependabot.split("  - package-ecosystem: ")
    return next(entry for entry in entries if entry.startswith(ecosystem))


class QualityDiffReportTests(unittest.TestCase):
    """The diff report compares the pull request with its merge base."""

    def test_report_diffs_from_the_merge_base(self) -> None:
        step = extract_step(CI_PATH.read_text(encoding="utf-8"), REPORT_STEP)
        self.assertIn('merge_base="$(git merge-base "$BASE_SHA" "$HEAD_SHA")"', step)
        self.assertIn('git show "$merge_base:QUALITY.md"', step)
        self.assertIn('git diff --name-only "$merge_base" "$HEAD_SHA"', step)
        self.assertNotIn('git show "$BASE_SHA:QUALITY.md"', step)
        self.assertNotIn('git diff --name-only "$BASE_SHA"', step)


class DependabotScopeTests(unittest.TestCase):
    """Dependabot leaves the files refreshed from the foucault pin alone."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dependabot = DEPENDABOT_PATH.read_text(encoding="utf-8")

    def test_actions_updates_skip_the_compliance_runner(self) -> None:
        entry = extract_update(self.dependabot, "github-actions")
        self.assertIn('      - ".github/workflows/immutable-conflict-check.yml"', entry)

    def test_pip_updates_skip_the_vendored_checker_requirements(self) -> None:
        entry = extract_update(self.dependabot, "pip")
        self.assertIn('      - "requirements-checkers.txt"', entry)


if __name__ == "__main__":
    unittest.main()
