"""Contract checks for the security review workflow pin and gates."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "security-review-pr.yml"


def extract_step(workflow: str, name: str) -> str:
    """Return one workflow step block by its name."""
    lines = workflow.splitlines()
    marker = f"      - name: {name}"
    start = lines.index(marker)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("      - "):
            end = index
            break
    return "\n".join(lines[start:end])


class SecurityReviewWorkflowContractTests(unittest.TestCase):
    """Verify the foucault pin, capacity handling, and dedupe trust scheme."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_pin_is_full_sha_with_release_comment(self) -> None:
        pin = re.search(r'FOUCAULT_REF: "([0-9a-f]{40})"', self.workflow)
        self.assertIsNotNone(pin, "FOUCAULT_REF must hold a full commit SHA")
        comment = re.search(r"# Foucault v3\.\d+\.\d+\.", self.workflow)
        self.assertIsNotNone(comment, "the pin needs a version comment")

    def test_every_checkout_persists_no_credentials(self) -> None:
        lines = self.workflow.splitlines()
        for index, line in enumerate(lines):
            if "uses: actions/checkout@" not in line:
                continue
            block_end = next(
                (stop for stop in range(index + 1, len(lines)) if lines[stop].startswith("      - ")),
                len(lines),
            )
            block = "\n".join(lines[index:block_end])
            self.assertIn("persist-credentials: false", block)

    def test_verdict_record_replaces_the_marker(self) -> None:
        self.assertIn("Write verdict record", self.workflow)
        self.assertIn("Upload verdict record", self.workflow)
        self.assertIn("security-review-verdict-${{ steps.resolve.outputs.head_sha }}", self.workflow)
        upload = extract_step(self.workflow, "Upload verdict record")
        self.assertIn("if: ${{ always() && steps.verdict.outputs.line != '' }}", upload)
        self.assertNotIn("Write review marker", self.workflow)
        self.assertNotIn("Upload review marker", self.workflow)
        self.assertNotIn("security-review-head-", self.workflow)

    def test_dedupe_requires_trusted_record_artifact(self) -> None:
        self.assertIn("hasTrustedVerdictRecord", self.workflow)
        self.assertIn("listArtifactsForRepo", self.workflow)
        self.assertIn('producer.event === "workflow_run"', self.workflow)
        self.assertIn("producer.head_branch === defaultBranch", self.workflow)

    def test_capacity_report_is_fixed_text_before_validation(self) -> None:
        capacity = extract_step(self.workflow, "Write capacity review report")
        self.assertIn("VERDICT: NEEDS-HUMAN - diff exceeds automated review capacity", capacity)
        self.assertIn(
            'VERDICT_JSON: {"mode": "PR", "verdict": "NEEDS-HUMAN", "findings": []}',
            capacity,
        )
        validate_index = self.workflow.index("- name: Validate report structure")
        capacity_index = self.workflow.index("- name: Write capacity review report")
        self.assertLess(capacity_index, validate_index)

    def test_model_call_fails_closed_on_capacity_exits(self) -> None:
        model = extract_step(self.workflow, "Run model call")
        self.assertIn("if: ${{ steps.case.outputs.oversized != 'true' }}", model)
        for name in ("Build provenance-labeled case text", "Run model call"):
            self.assertIn("-eq 3", extract_step(self.workflow, name))

    def test_case_builder_diffs_from_the_merge_base(self) -> None:
        build = extract_step(self.workflow, "Build provenance-labeled case text")
        self.assertIn("AUDIT_PROMPT_FILE: .foucault/AUDIT.md", build)
        fetch = extract_step(self.workflow, "Fetch pull request head object")
        self.assertNotIn("--depth=1", fetch)
        self.assertIn("Full history lets the case builder diff from the merge base", fetch)

    def test_concurrency_cancels_an_obsolete_run(self) -> None:
        self.assertIn("cancel-in-progress: true", self.workflow)
        self.assertNotIn("cancel-in-progress: false", self.workflow)

    def test_pin_is_verified_after_checkout(self) -> None:
        verify = extract_step(self.workflow, "Verify AUDIT.md revision")
        self.assertIn("git -C .foucault rev-parse HEAD", verify)
        scripts = extract_step(self.workflow, "Verify pinned review scripts")
        for path in (
            ".foucault/ci/build_pr_case.py",
            ".foucault/ci/run_model_command.py",
            ".foucault/scripts/check_pr_review_response.py",
        ):
            self.assertIn(path, scripts)

    def test_verdict_parse_reads_the_gate_line(self) -> None:
        parse = extract_step(self.workflow, "Parse verdict")
        self.assertIn("grep -E '^VERDICT:' response.txt | tail -1", parse)
        self.assertIn('read -r verdict_token _ <<< "$rest"', parse)


if __name__ == "__main__":
    unittest.main()
