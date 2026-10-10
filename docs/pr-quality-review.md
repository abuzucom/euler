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
4. A same-repository pull request calls `quality-review.yml` without setting
   `fork_review`. The default selects the existing `review` job.
5. An adopter can set `fork_review: true` to select `fork-review`. The job
   waits for the adopter's `fork-review` environment protection rules.
6. The fork job fetches `refs/pull/<number>/head` after approval. It reads PR
   files as data and never executes them.
7. The caller can provide `MODEL_API_KEY` as a reusable-workflow secret. A
   fork adopter can instead configure `MODEL_API_KEY` as an environment secret.
   The job fails before a model request when the key is empty.
8. The reusable workflow allows one active review per pull request. A newer
   head cancels an obsolete run.
9. Both execution paths keep the base and head commits in the object store.
   The same-repository path does not check out the pull request head.
10. The workflow checks out `abuzucom/euler` at `quality_ref` into `.euler`.
11. `ci/build_pr_case.py` writes one or more review envelopes.
12. `ci/run_review.py review` calls the model once per envelope.
13. `ci/check_review_response.py` validates each report, including process
    narration. An invalid report triggers one retry with the problems attached.
14. The workflow posts one PR comment and a `quality-review` check run.
15. `ci/run_review.py gate` fails the job on a blocking verdict.

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
- A report failing validation twice forces NEEDS-HUMAN for that chunk. The
  comment shows validation problems and omits the invalid model text.

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
- a provider API key mapped to `MODEL_API_KEY`
- `fork_review: true` for fork pull requests that require environment approval
- a `fork-review` environment with protection rules and a `MODEL_API_KEY`
  environment secret for that protected path
- an `adopters/<repo>.md` record per `adopters/README.md`

Same-repository callers can omit `fork_review` and keep mapping a repository or
organization secret to `MODEL_API_KEY`. Fork callers can map an accessible
`OLLAMA_API_KEY` secret to `MODEL_API_KEY` instead of configuring an environment
secret. If both sources use the `MODEL_API_KEY` name, the environment secret
takes precedence in the protected job.

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
