"""Contract checks for the security review workflow pin, gates, and steps."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALLER_PATH = ROOT / ".github" / "workflows" / "security-review-pr.yml"
REUSABLE_PATH = ROOT / ".github" / "workflows" / "security-review.yml"


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


def extract_job(workflow: str, job_name: str) -> str:
    """Return one workflow job block by its name."""
    lines = workflow.splitlines()
    job_index = lines.index(f"  {job_name}:")
    starts = [index for index, line in enumerate(lines) if line.startswith("  ") and not line.startswith("   ")]
    following = [index for index in starts if index > job_index]
    end = following[0] if following else len(lines)
    return "\n".join(lines[job_index:end])


class SecurityReviewCallerTests(unittest.TestCase):
    """Verify the caller's pin, gates, and delegation to the reusable file."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.caller = CALLER_PATH.read_text(encoding="utf-8")

    def test_pin_is_full_sha_with_release_comment(self) -> None:
        self.assertRegex(self.caller, r'FOUCAULT_REF: "([0-9a-f]{40})"')
        self.assertRegex(self.caller, r"# Foucault v3\.\d+\.\d+\.")

    def test_review_and_fork_jobs_delegate_to_the_reusable(self) -> None:
        for job_name in ("review", "fork-review"):
            job = extract_job(self.caller, job_name)
            self.assertIn("uses: ./.github/workflows/security-review.yml", job)
            self.assertIn("audit_ref: ${{ env.FOUCAULT_REF }}", job)
            self.assertIn("MODEL_API_KEY: ${{ secrets.OLLAMA_API_KEY }}", job)
            self.assertIn("pr_comment: true", job)
            self.assertIn("fail_on_block: true", job)
        fork_job = extract_job(self.caller, "fork-review")
        self.assertIn("fork_review: true", fork_job)

    def test_fork_review_requires_the_label(self) -> None:
        self.assertIn('"safe-to-review"', self.caller)
        self.assertIn("fork_review_approved: ${{ steps.resolve.outputs.fork_review_approved }}", self.caller)
        skipped = extract_job(self.caller, "fork-review-skipped")
        self.assertIn(
            "needs.resolve-pr.outputs.fork_review_approved != 'true'",
            skipped,
        )
        review = extract_job(self.caller, "review")
        self.assertIn("needs.resolve-pr.outputs.same_repository == 'true'", review)
        fork = extract_job(self.caller, "fork-review")
        self.assertIn("needs.resolve-pr.outputs.same_repository == 'false'", fork)
        self.assertIn("needs.resolve-pr.outputs.fork_review_approved == 'true'", fork)

    def test_dedupe_requires_trusted_record_artifact(self) -> None:
        self.assertIn("hasTrustedVerdictRecord", self.caller)
        self.assertIn("listArtifactsForRepo", self.caller)
        self.assertIn('producer.event === "workflow_run"', self.caller)
        self.assertIn("producer.head_branch === defaultBranch", self.caller)

    def test_head_metadata_is_revalidated_for_forks(self) -> None:
        self.assertIn('"pull request changed while resolving review metadata"', self.caller)
        self.assertIn("github.rest.pulls.get", self.caller)

    def test_concurrency_cancels_an_obsolete_run(self) -> None:
        self.assertIn("cancel-in-progress: true", self.caller)
        self.assertNotIn("cancel-in-progress: false", self.caller)


class SecurityReviewReusableTests(unittest.TestCase):
    """Verify the reusable review implementation and its trust boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.reusable = REUSABLE_PATH.read_text(encoding="utf-8")

    def test_fork_review_job_holds_the_only_environment(self) -> None:
        environments = [line.strip() for line in self.reusable.splitlines() if line.strip().startswith("environment:")]
        self.assertEqual(environments, ["environment: fork-review"])
        fork_job = extract_job(self.reusable, "fork-review")
        self.assertIn("environment: fork-review", fork_job)
        self.assertIn("steps: *security_review_steps", fork_job)
        review = extract_job(self.reusable, "review")
        self.assertIn("steps: &security_review_steps", review)

    def test_every_checkout_persists_no_credentials(self) -> None:
        for workflow in (CALLER_PATH, REUSABLE_PATH):
            lines = workflow.read_text(encoding="utf-8").splitlines()
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
        self.assertIn("Write verdict record", self.reusable)
        self.assertIn("Upload verdict record", self.reusable)
        self.assertIn(
            "security-review-verdict-${{ steps.resolve.outputs.head_sha }}",
            self.reusable,
        )
        upload = extract_step(self.reusable, "Upload verdict record")
        self.assertIn("if: ${{ always() && steps.verdict.outputs.line != '' }}", upload)
        self.assertNotIn("Write review marker", self.reusable)
        self.assertNotIn("security-review-head-", self.reusable)

    def test_capacity_report_is_fixed_text_before_validation(self) -> None:
        capacity = extract_step(self.reusable, "Write capacity review report")
        self.assertIn(
            "VERDICT: NEEDS-HUMAN - diff exceeds automated review capacity",
            capacity,
        )
        self.assertIn(
            'VERDICT_JSON: {"mode": "PR", "verdict": "NEEDS-HUMAN", "findings": []}',
            capacity,
        )
        validate_index = self.reusable.index("- name: Validate report structure")
        capacity_index = self.reusable.index("- name: Write capacity review report")
        self.assertLess(capacity_index, validate_index)

    def test_model_call_fails_closed_on_capacity_exits(self) -> None:
        model = extract_step(self.reusable, "Run model call")
        self.assertIn("if: ${{ steps.case.outputs.oversized != 'true' }}", model)
        for name in ("Build provenance-labeled case text", "Run model call"):
            self.assertIn("-eq 3", extract_step(self.reusable, name))

    def test_case_builder_diffs_from_the_merge_base(self) -> None:
        build = extract_step(self.reusable, "Build provenance-labeled case text")
        self.assertIn("AUDIT_PROMPT_FILE: .foucault/AUDIT.md", build)
        fetch = extract_step(self.reusable, "Fetch pull request head object")
        self.assertNotIn("--depth=1", fetch)
        self.assertIn(
            "Full history lets the case builder diff from the merge base",
            fetch,
        )
        adapter = extract_step(self.reusable, "Run model call")
        self.assertIn(
            'python3 .foucault/ci/run_model_command.py "$MODEL_CALL_COMMAND"',
            adapter,
        )

    def test_audit_ref_is_validated_as_a_full_sha(self) -> None:
        self.assertIn(r"auditRefPattern = /^[0-9a-f]{40}$/", self.reusable)
        verify = extract_step(self.reusable, "Verify AUDIT.md revision")
        self.assertIn("git -C .foucault rev-parse HEAD", verify)
        scripts = extract_step(self.reusable, "Verify pinned review scripts")
        for path in (
            ".foucault/ci/build_pr_case.py",
            ".foucault/ci/run_model_command.py",
            ".foucault/scripts/check_pr_review_response.py",
        ):
            self.assertIn(path, scripts)

    def test_verdict_parse_reads_the_gate_line(self) -> None:
        parse = extract_step(self.reusable, "Parse verdict")
        self.assertIn("grep -E '^VERDICT:' response.txt | tail -1", parse)
        self.assertIn('read -r verdict_token _ <<< "$rest"', parse)

    def test_check_run_publication_reports_the_verdict(self) -> None:
        publish = extract_step(self.reusable, "Publish check run")
        self.assertIn('name: "security-review"', publish)
        self.assertIn("github.rest.checks.create(request)", publish)


if __name__ == "__main__":
    unittest.main()
