# PR security review

## Purpose

`.github/workflows/security-review-pr.yml` runs the `abuzucom/foucault` security
review on this repository's pull requests. Foucault's `AUDIT.md` drives the
review. Euler's `QUALITY.md` review runs separately in `quality-review-pr.yml`.
The two reviews publish separate check runs.

## Pin

The workflow pins foucault v3.3.14 at commit
`06d74fba4d9013654cdaf9896bb7535724385186`. The `FOUCAULT_REF` job variable
holds the pin. The workflow loads `AUDIT.md` and the foucault adapter from that
one commit.

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
8. `review` builds the case, calls the model, validates the report, and retries
   once on a structural failure.
9. `review` uploads a `security-review-head-<head sha>` marker artifact.
10. `review` posts a fenced PR comment and fails on BLOCK or NEEDS-HUMAN.
11. `review` publishes a `security-review` check run on the head SHA.

## Dedupe

Any workflow with `checks: write` can create a check run named
`security-review`. A same-repository pull request can add such a workflow.
`resolve-pr` counts a check run as a completed review only when all of these
conditions hold:

- The summary carries a `VERDICT:` token.
- The summary names a run in this repository on a `Workflow run:` line.
  GitHub replaces the `details_url` of a check run created with the job
  token.
- That run comes from `.github/workflows/security-review-pr.yml` on the
  default branch through the `workflow_run` event.
- That run holds the marker artifact for the current head SHA.

A failed lookup counts as no review. The marker artifact expires after 30
days. A later `ci` run on an older head then triggers a fresh review.

The `quality-review` check run has no dedupe. A spoofed `quality-review` check
run adds a second check run with the same name. The real review still posts its
own result.

## Job limits

The `review` job stops after 30 minutes. The job makes at most two model calls.
The foucault adapter bounds each call at 600 seconds.

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
   `.github/workflows/`.
7. Require the `security-review` and `quality-review` checks from the GitHub
   Actions app.

## Upgrade

1. Pick a new foucault release commit.
2. Diff foucault's `security-review-pr.yml` and `security-review.yml` between
   the old and new pins.
3. Port each upstream change into `security-review-pr.yml`. Keep the
   `.foucault/` paths.
4. Set `FOUCAULT_REF` and the version comment.
5. Update this document and `adopters/README.md`.
