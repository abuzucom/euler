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
4. `resolve-pr` skips a head that already carries a `security-review` check
   run with a verdict.
5. A same-repository pull request runs `review`. A fork pull request runs
   `fork-review-skipped` without a secret.
6. `review` checks out the base revision and the pinned foucault revision.
7. `review` fetches the head object without a checkout.
8. `review` builds the case, calls the model, validates the report, and retries
   once on a structural failure.
9. `review` posts a fenced PR comment and fails on BLOCK or NEEDS-HUMAN.
10. `review` publishes a `security-review` check run on the head SHA.

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

## Upgrade

1. Pick a new foucault release commit.
2. Diff foucault's `security-review-pr.yml` and `security-review.yml` between
   the old and new pins.
3. Port each upstream change into `security-review-pr.yml`. Keep the
   `.foucault/` paths.
4. Set `FOUCAULT_REF` and the version comment.
5. Update this document and `adopters/README.md`.
