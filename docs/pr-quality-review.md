# PR quality review architecture

## Purpose

The PR reviewer applies `QUALITY.md` to one pull request. The reviewer returns
a report with a machine-readable verdict. The check fails on `BLOCK` or
`NEEDS-HUMAN` by default.

## Event flow

1. GitHub runs `ci.yml` for the pull request event.
2. GitHub runs `quality-review-pr.yml` after `ci` completes.
3. The caller runs with default-branch code. It resolves one open pull request
   from the workflow run `head_sha`.
4. A same-repository pull request calls `quality-review.yml`.
5. A fork pull request receives a `skipped` check run. The skip job receives
   no secret.
6. The reusable workflow allows one active review per pull request. A newer
   head cancels an obsolete run.
7. The workflow checks out the base revision with full history. The head
   commit stays in the object store without a checkout.
8. The workflow checks out `abuzucom/euler` at `quality_ref` into `.euler`.
9. `ci/build_pr_case.py` writes one or more review envelopes.
10. `ci/run_review.py review` calls the model once per envelope.
11. `ci/check_review_response.py` validates each report. An invalid report
    triggers one retry with the problems attached.
12. The workflow posts one PR comment and a `quality-review` check run.
13. `ci/run_review.py gate` fails the job on a blocking verdict.

## Envelope and prescan

`ci/build_pr_case.py` reads the diff and the head tree from git objects. The
builder extracts the head tree with the tarfile data filter. It runs
`scripts/check_code_quality.py` checks on changed files. It keeps candidates
on added lines. Project-level classes C3, D2, and D5 keep candidates in
changed files.

The envelope from `scripts/review_envelope.py` holds two channels:

- `TRUSTED_CONTEXT` holds pipeline metadata and prescan candidates.
- `REVIEW_TARGET` holds the PR text and the per-file patches.

Each channel carries a SHA-256 digest. The model must resolve every prescan
item in the `prescan` array of `VERDICT_JSON`.

## Verdict merge

- The worst chunk verdict wins. BLOCK outranks NEEDS-HUMAN. NEEDS-HUMAN
  outranks APPROVE.
- A blocking prescan finding from Q11, M1, M12, or M13 forces BLOCK.
- A binary file or a file over the chunk budget becomes an unreviewed file.
  Unreviewed files force NEEDS-HUMAN.
- A model call failure forces NEEDS-HUMAN for that chunk.
- A report failing validation twice forces NEEDS-HUMAN for that chunk.

## Trust boundary

The caller runs default-branch code. The workflow never executes a pull
request file. Pull request titles and bodies reach scripts through environment
variables only. No workflow step places pull request text in shell syntax.
Every checkout sets `persist-credentials: false`.

The provider receives `QUALITY.md` and the review envelope. The provider
receives no GitHub token and no other repository secret.
`ci/call_model.py` sends requests only to endpoints in `ALLOWED_ENDPOINTS`.

## Adoption in another repository

Call `quality-review.yml` as a reusable workflow. Pin `uses:` and
`quality_ref` to the same full commit SHA. Mirror `quality-review-pr.yml` for
the caller. The adopter supplies these items:

- a caller workflow
- a provider API key as a repository secret, mapped to `MODEL_API_KEY`
- an `adopters/<repo>.md` record per `adopters/README.md`

The workflow checks out `abuzucom/euler` without credentials beyond the
caller token. An adopter outside the `abuzucom` organization needs read access
to `abuzucom/euler`.

The `workflow_run` trigger runs only from the default branch. A new caller
starts reviewing pull requests after the caller workflow reaches the default
branch.

## Local testing

- `make check` runs every unit test with stubbed HTTP.
- `python3 ci/build_pr_case.py --base <sha> --head <sha> --pr-number 1
  --out-dir review` builds envelopes for a local range.
- `MODEL_API_KEY=... python3 ci/run_review.py review --review-dir review`
  runs a live review against the active provider.

## Provider changes

Edit `active_provider` in `ci/model_providers.json`. The adapter supports the
`ollama`, `openai-compatible`, and `anthropic` protocols. A new endpoint needs
an `ALLOWED_ENDPOINTS` entry in `ci/call_model.py` in the same change. Map the
matching provider secret to `MODEL_API_KEY` in the caller workflow.
