"""Contract checks for reusable quality review workflow paths."""

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "quality-review.yml"
CALLER_PATH = ROOT / ".github" / "workflows" / "quality-review-pr.yml"


def extract_block(source: str, heading: str, indent: int) -> list[str]:
    """Return one YAML indentation block starting at heading."""
    lines = source.splitlines()
    marker = f"{' ' * indent}{heading}"
    start = next(index for index, line in enumerate(lines) if line == marker)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            end = index
            break
    block = lines[start:end]
    while block and not block[-1].strip():
        block.pop()
    return block


def extract_step(job: list[str], name: str) -> list[str]:
    """Return one workflow step block by its name."""
    marker = f"      - name: {name}"
    start = job.index(marker)
    end = len(job)
    for index in range(start + 1, len(job)):
        line = job[index]
        if line.startswith("      - name:"):
            end = index
            break
    step = job[start:end]
    while step and not step[-1].strip():
        step.pop()
    return step


def normalize_fork_job(job: list[str]) -> list[str]:
    """Remove the fork selector and protected environment declaration."""
    normalized = [
        line
        for line in job
        if line
        not in {
            "  fork-review:",
            "    if: ${{ inputs.fork_review == true }}",
            "    environment: fork-review",
        }
    ]
    normalized = [line for line in normalized if line.strip()]
    return [
        "  review:",
        "    if: ${{ inputs.fork_review != true }}",
        *normalized,
    ]


class QualityReviewWorkflowContractTests(unittest.TestCase):
    """Verify backward-compatible same-repository and gated fork paths."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.caller = CALLER_PATH.read_text(encoding="utf-8")

    def test_fork_input_is_optional_and_defaults_to_same_repository_path(self) -> None:
        fork_input = extract_block(self.workflow, "fork_review:", 6)
        fork_input_text = "\n".join(fork_input)
        self.assertIn("required: false", fork_input_text)
        self.assertIn("type: boolean", fork_input_text)
        self.assertIn("default: false", fork_input_text)

        review = extract_block(self.workflow, "review:", 2)
        self.assertIn("    if: ${{ inputs.fork_review != true }}", review)

    def test_only_fork_job_uses_the_protected_environment(self) -> None:
        environment_lines = [line for line in self.workflow.splitlines() if line.strip().startswith("environment:")]
        self.assertEqual(environment_lines, ["    environment: fork-review"])

        fork_job = extract_block(self.workflow, "fork-review:", 2)
        self.assertIn("    if: ${{ inputs.fork_review == true }}", fork_job)
        self.assertIn("    environment: fork-review", fork_job)
        self.assertLess(
            fork_job.index("    environment: fork-review"),
            fork_job.index("      - name: Fetch review commits"),
        )

    def test_model_secret_is_optional_at_boundary_and_fails_closed(self) -> None:
        secret = extract_block(self.workflow, "MODEL_API_KEY:", 6)
        self.assertIn("required: false", "\n".join(secret))

        for job_name in ("review", "fork-review"):
            job = extract_block(self.workflow, f"{job_name}:", 2)
            validation = extract_step(job, "Validate model API key")
            model_review = extract_step(job, "Run model review")
            self.assertLess(job.index(validation[0]), job.index(model_review[0]))
            validation_text = "\n".join(validation)
            model_review_text = "\n".join(model_review)
            self.assertIn('if [[ -z "$MODEL_API_KEY" ]]', validation_text)
            self.assertIn("exit 1", validation_text)
            self.assertIn("MODEL_API_KEY: ${{ secrets.MODEL_API_KEY }}", model_review_text)

    def test_fork_path_reads_pr_head_without_running_it(self) -> None:
        fork_job = extract_block(self.workflow, "fork-review:", 2)
        fetch_commits = extract_step(fork_job, "Fetch review commits")
        fetch_text = "\n".join(fetch_commits)
        self.assertIn("FORK_REVIEW: ${{ inputs.fork_review }}", fetch_text)
        self.assertIn('git fetch --no-tags origin "refs/pull/$PR_NUMBER/head"', fetch_text)
        self.assertIn("git rev-parse --verify 'FETCH_HEAD^{commit}'", fetch_text)
        self.assertIn('if [[ "$FETCHED_HEAD" != "$HEAD_SHA" ]]', fetch_text)
        self.assertIn('git cat-file -e "$HEAD_SHA^{commit}"', fetch_text)
        self.assertNotIn("actions/checkout", fetch_text)

    def test_jobs_checkout_trusted_code_and_fetch_review_commits_as_objects(self) -> None:
        for job_name in ("review", "fork-review"):
            job = extract_block(self.workflow, f"{job_name}:", 2)
            checkout = extract_step(job, "Checkout trusted workflow revision")
            checkout_text = "\n".join(checkout)
            fetch_commits = extract_step(job, "Fetch review commits")
            fetch_text = "\n".join(fetch_commits)
            self.assertIn("ref: ${{ github.sha }}", checkout_text)
            self.assertIn("persist-credentials: false", checkout_text)
            self.assertNotIn("inputs.base_sha", checkout_text)
            self.assertIn('git fetch --no-tags origin "$BASE_SHA"', fetch_text)
            self.assertIn('git fetch --no-tags origin "$HEAD_SHA"', fetch_text)

    def test_both_paths_run_the_same_review_implementation(self) -> None:
        review = [line for line in extract_block(self.workflow, "review:", 2) if line.strip()]
        fork_job = extract_block(self.workflow, "fork-review:", 2)
        self.assertEqual(review, normalize_fork_job(fork_job))

    def test_existing_caller_keeps_its_secret_alias_and_default_input(self) -> None:
        self.assertNotIn("fork_review:", self.caller)
        self.assertIn("MODEL_API_KEY: ${{ secrets.OLLAMA_API_KEY }}", self.caller)


if __name__ == "__main__":
    unittest.main()
