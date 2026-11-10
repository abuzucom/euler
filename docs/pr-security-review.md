# PR security review

## Purpose

`.github/workflows/security-review-pr.yml` runs the `abuzucom/foucault` security
review on this repository's pull requests. Foucault's `AUDIT.md` drives the
review. Euler's `QUALITY.md` review runs separately in `quality-review-pr.yml`.
The two reviews publish separate check runs.

## Pin

The workflow pins foucault v3.7.1 at commit
`ae8a60036681ce8e865eee256fc685585c3f290d`. The `FOUCAULT_REF` job variable
holds the pin. The workflow loads `AUDIT.md` and the foucault adapter from that
one commit. A verify step re-reads the checked-out revision and rejects a
mismatch with the pin.

## Wiring

Foucault's reusable workflow runs its adapter from fixed paths in the caller
checkout. Euler's own quality adapter occupies `ci/build_pr_case.py` and
`ci/call_model.py`. The local workflow mirrors foucault's caller and reusable
job steps instead. Every foucault script runs from the pinned `.foucault/`
checkout:

- `.foucault/ci/build_pr_case.py` writes `case_text.txt`.
- `.foucault/ci/run_model_command.py` runs `ci/call_model.py` resolved inside
  `.foucault/`.
- `.foucault/ci/call_model.py` reads `.foucault/ci/model_providers.json`.
- `.foucault/scripts/check_pr_review_response.py` validates the report.

The case builder diffs from the merge base. It needs the `AUDIT_PROMPT_FILE`
environment variable and exits 3 when the diff exceeds review capacity. The
model adapter exits 3 when the input exceeds every configured model budget.
The capacity steps then write a fixed `NEEDS-HUMAN` report on exit 3.

## Event flow

1. GitHub runs `ci.yml` for the pull request event.
2. GitHub runs `security-review-pr.yml` after `ci` completes.
3. `resolve-pr` resolves one pull request from the workflow run head SHA.
4. `resolve-pr` skips a head that already carries a genuine `security-review`
   check run with a verdict. The dedupe section defines genuine.
5. A same-repository pull request runs `review`. A fork pull request runs
   `fork-review-skipped` without a secret.
6. `review` checks out the base revision and the pinned foucault revision.
7. `review` fetches the head object without a checkout.
8. `review` builds the case. An oversized diff writes a fixed capacity report
   with a `NEEDS-HUMAN` verdict instead of a model call.
9. `review` calls the model. An input above every model budget writes the same
   capacity report. A structural failure retries once.
10. `review` writes and uploads a `security-review-verdict-<head sha>` verdict
    record artifact.
11. `review` posts a fenced PR comment and fails on BLOCK or NEEDS-HUMAN.
12. `review` publishes a `security-review` check run on the head SHA.

## Dedupe

Check run names and summaries are writable by any workflow holding
`checks: write`. A check run alone cannot prove a review. `resolve-pr` uses a
check run with a verdict token as a prefilter. It then trusts a completed
review only when every condition holds:

- The run holds a verdict record artifact named
  `security-review-verdict-<head sha>`.
- The artifact belongs to a run of `.github/workflows/security-review-pr.yml`.
- That run uses the `workflow_run` event and the default branch of this
  repository. GitHub runs `workflow_run` workflows from the default branch
  alone, so a pull request branch cannot produce one.

A failed lookup counts as no review. An expired artifact counts as no
review. A later run on the same head then triggers a fresh review.

### Override

Any workflow with `checks: write` can post a `security-review` or
`quality-review` check run. The checks box and a required check follow the
most recent check run with a given name. A spoofed success posted after the
real result overrides the real result. A spoofed success after a real BLOCK
turns the gate green. The dedupe stops a skipped review only. It does not stop
an override. Manual settings step 6 closes the override.

## Job limits

The `review` job stops after 30 minutes. The job makes at most two model calls.
The foucault adapter bounds each call at 600 seconds.

Runs for one head SHA share a concurrency group. A second run waits for the
first run instead of cancelling it. The dedupe then skips the second review.

## Differences from upstream

- Every foucault script path carries the `.foucault/` prefix.
- Each job declares its own permissions. Upstream grants `checks: write` and
  `pull-requests: write` at workflow level.
- The file follows the repository yamllint rules. It quotes the `on` key and
  wraps the long `review` condition.

## Trust boundary

`workflow_run` runs default-branch code. A pull request cannot edit the
reviewer. The workflow never executes pull request content. Every checkout
sets `persist-credentials: false`. The model step receives only the
`OLLAMA_API_KEY` secret as `MODEL_API_KEY`. An invalid model response goes to
an artifact. The log never echoes model text.

## Secret

The active foucault provider profile is Ollama with `kimi-k2.7-code`. Set the
`OLLAMA_API_KEY` repository secret. Without it, every review fails before a
verdict.

### Residual risk

`OLLAMA_API_KEY` is a repository secret. `quality-review-pr.yml` also maps it
to `MODEL_API_KEY`. A `pull_request` workflow from a same-repository branch
runs the branch's own workflow files and can read repository secrets. A branch
can add a workflow that prints or sends the key. `workflow_run` protects the
reviewer only. It does not protect the key. The repository files record no
provider spending cap.

### Manual settings

These steps change repository and provider settings. A repository admin
performs them:

1. Create a GitHub environment for the model key. Limit its deployment
   branches to the default branch.
2. Add the key as an environment secret.
3. Add `environment:` to both review jobs in the same change as the secret
   move.
4. Delete the `OLLAMA_API_KEY` repository secret.
5. Set a spending cap with the provider.
6. Add a ruleset that requires human review for changes under
   `.github/workflows/`. This step closes the override. A pull request that
   adds or changes a workflow cannot merge before a human reviews the
   workflow.
7. Require the `security-review` and `quality-review` checks from the GitHub
   Actions app. This step blocks check runs from other apps. The GitHub
   Actions app authors both the real and the spoofed check runs. Step 7 does
   not block an override from a pull request workflow.

## Upgrade

1. Pick a new foucault release commit.
2. Diff foucault's `security-review-pr.yml` and `security-review.yml` between
   the old and new pins.
3. Port each upstream change into `security-review-pr.yml`. Keep the
   `.foucault/` paths.
4. Set `FOUCAULT_REF` and the version comment.
5. Update this document and `adopters/README.md`.
