# PR security review

## Purpose

`.github/workflows/security-review-pr.yml` runs the `abuzucom/foucault` security
review on this repository's pull requests. Foucault's `AUDIT.md` drives the
review. Euler's `QUALITY.md` review runs separately in `quality-review-pr.yml`.
The two reviews publish separate check runs.

## Pin

The workflow pins foucault v3.7.12 at commit
`770ecbb4c52e50c554214c68245e16832a70e0be`. The workflow-level `FOUCAULT_REF`
variable holds the pin. The `resolve-pr` job republishes it as the `audit_ref`
output for the reusable-workflow calls. The workflow loads `AUDIT.md` and the
foucault adapter from that one commit. A verify step re-reads the checked-out
revision and rejects a mismatch with the pin.

## Wiring

The reusable `security-review.yml` carries the review steps. The caller
resolves metadata, gates executions, and maps the provider secret. Both
execution paths call the reusable file in this repository. Foucault's
reusable workflow runs its adapter from fixed paths in the caller checkout.
Euler's own quality adapter occupies `ci/build_pr_case.py` and
`ci/call_model.py`. Euler's reusable copy keeps every foucault script inside
the pinned `.foucault/` checkout instead:

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

1. GitHub runs `immutable-conflict-check.yml` for the pull request target
   event. The runner scans every pull request tree with the vendored
   compliance checker.
2. GitHub runs `security-review-pr.yml` after the compliance run completes.
3. `resolve-pr` resolves one pull request from the workflow run head SHA.
4. `resolve-pr` skips a head that already carries a genuine `security-review`
   check run with a verdict. The dedupe section defines genuine.
5. A same-repository pull request runs the `review` job. A fork pull request
   with the `safe-to-review` label runs `fork-review` behind the environment.
   Any other fork pull request runs `fork-review-skipped`.
6. `review` checks out the repository's default branch and the pinned
   foucault revision. No API-derived ref is ever checked out.
7. `review` fetches the base and head pull request objects into the trusted
   checkout's object store.
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

Runs for one head SHA share a concurrency group. A newer run for the same
head cancels an obsolete run. The trusted verdict record skips the newer
review when the first run already finished.

## Differences from upstream

- Every foucault script path carries the `.foucault/` prefix. Upstream
  adopters copy the adapter scripts into their own checkout.
- Euler's reusable workflow pins `model_call_command` to the adapter
  command. Upstream keeps it a public input for adopter compatibility.
- The compliance checker accepts only the hash-verified pip install
  command. Upstream still accepts the plain install during its own
  transition.
- The pull request review holds the worktree on the repository's default
  branch and fetches the base and head as git objects. Upstream checks out
  the pull request base revision.
- The vendored checker modules under `scripts/` carry euler's compliance
  configuration. The branch-prefix list accepts euler's `ci/` prefix.
- The caller keeps read-only permissions at workflow level and per-job
  permission declarations. Upstream grants write permissions at workflow
  level.
- The file follows the repository yamllint rules. It quotes the `on` key and
  wraps long expressions.
- The compliance runner and `scripts/check_compliance_tree.py` trust
  `actions/checkout` v7.0.1 and `actions/setup-python` v7.1.0. Upstream
  v3.7.12 still trusts checkout v4.4.0. A pin refresh keeps the euler pins.
- `scripts/check_compliance_tree.py` keeps the `process.stdout is None`
  guard that upstream dropped. mypy over `scripts/` types the stream as
  optional.

## Fork review

`same_repository == false` plus the `safe-to-review` label plus a successful
compliance run on the same head makes resolve-pr mark the head as approved.
The label is a capacity gate. The environment approval and the compliance
run carry the security gate. The pull request author or a maintainer applies
the label before requesting review; the workflow only reads it. The
`fork-review` caller selects the reusable workflow's `fork-review` job,
which attaches the `fork-review` environment. GitHub waits for environment
approval and exposes environment secrets before the model call. The caller
maps `OLLAMA_API_KEY` to `MODEL_API_KEY`, and an environment secret with the
same name takes precedence inside the protected job.

## Compliance

`immutable-conflict-check.yml` runs on `pull_request_target`. The runner
keeps the exact trusted schema the vendored `check_compliance_tree.py`
validates in every pull request tree, so a pull request cannot weaken the
runner. The checker modules under `scripts/` and the hash-pinned
`requirements-checkers.txt` come from the same foucault commit as the review
pin. The scan reads pull request objects as data and never executes pull
request code. A failed scan leaves the head non-compliant and keeps the fork
review skipped. Same-repository reviews run the security review after the
compliance run completes on the same head.

## Trust boundary

`workflow_run` runs default-branch code. A pull request cannot edit the
reviewer. The workflow never executes pull request content. Every checkout
sets `persist-credentials: false`. The model step receives only the
`OLLAMA_API_KEY` secret as `MODEL_API_KEY`. An invalid model response goes to
an artifact. The log never echoes model text. The compliance runner executes
default-branch code and scans pull request object trees as data only.

## Secret

The active foucault provider profile is `ollama-large`. That profile runs
Ollama with `minimax-m3.1-flash`. Set the
`OLLAMA_API_KEY` repository secret for the same-repository review. Without
it, every review fails before a verdict. The protected fork path reads the
`fork-review` environment secret.

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

1. Create the `safe-to-review` label for fork requests that may consume the
   protected model capacity. The workflows only read the label.
2. Create a GitHub environment named `fork-review`. Limit its deployment
   branches to the default branch.
3. Add the key as a `fork-review` environment secret.
4. Delete the `OLLAMA_API_KEY` repository secret after both review paths see
   it in place, or keep a mapped repository secret for the same-repository
   review.
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
2. Diff foucault's `security-review.yml`, `immutable-conflict-check.yml`, and
   the adapter scripts between the old and new pins.
3. Port each upstream change. The review steps live in
   `security-review.yml`; keep the `.foucault/` path prefix. Refresh the
   vendored checker modules and `requirements-checkers.txt` from the new pin
   in the same change.
4. Set `FOUCAULT_REF` and the version comment.
5. Update this document and the contract tests.
