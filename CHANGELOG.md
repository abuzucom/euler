# Changelog

This file documents every notable project change.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows Semantic Versioning. Pin a tag or commit SHA when
loading `QUALITY.md` into a deployment.

## [0.4.1] (2026-09-30)

### Fixed

- `ci/build_pr_case.py` reads changed paths with `git diff -z` and passes
  them as literal pathspecs. A file name with spaces or non-ASCII characters
  no longer hides its patch from the model and the prescan.
- A path that is not valid UTF-8 and a text file with an empty patch become
  unreviewed files.
- The prescan reads head blobs with `git ls-tree` and `git cat-file`. A
  `.gitattributes` `export-ignore` entry in the pull request no longer hides
  files from the prescan.
- `ci/build_pr_case.py` takes an optional `--max-chunks`, 20 by default.
  Files in chunks past the limit become unreviewed files.
- `ci/run_review.py` fences the blocking prescan list, the unreviewed list,
  and the validation problems in the PR comment. Each list shows at most 50
  items of at most 300 characters.
- `ci/call_model.py` writes the provider error body to the job log only. The
  `ModelCallError` message keeps the HTTP status.
- The checkers skip a Python or TOML file that raises `RecursionError` or
  `MemoryError` with a warning. The PR builder lists such a file as
  unreviewed.
- `security-review-pr.yml` trusts a `security-review` check run for dedupe
  only when its `details_url` names a default-branch run of this workflow
  holding a `security-review-head-<sha>` marker artifact. `resolve-pr` gains
  `actions: read`.
- `security-review-pr.yml` reads the verdict token with `read -r` in place of
  unquoted `set --`.
- Set a 30-minute timeout on the `security-review-pr.yml` `review` job and a
  45-minute timeout on the `quality-review.yml` `review` job.
- `quality-review.yml` takes an optional `max_chunks` input, 20 by default.
- Documented the shared model key risk and the manual settings steps in
  `docs/pr-security-review.md`.

## [0.4.0] (2026-09-30)

### Changed

- Adopted the `abuzucom/rough` ruff baseline at commit
  `b52aa382ebede9efb215e479f48cfb9c0b7a9272`. `ruff.toml` holds the block tier
  and `ruff.warn.toml` the warn tier. `target-version` stays `py311`. The
  baseline replaces the default rules plus the PL and S families.
- `make lint` runs the block tier with `--ignore-noqa`, `ruff format --check`,
  and the warn tier with `--exit-zero`.
- Reformatted the Python sources and tests with `ruff format`.
- `ci/call_model.py` posts over `http.client` with an HTTPS-only URL check in
  place of `urllib.request.urlopen`. New tests cover the request, status, and
  error paths.
- Applied two safe block-tier fixes in `dependencies.py` and a test fixture.

## [0.3.0] (2026-09-30)

### Added

- Added `codeql.yml` for CodeQL scanning of Python and GitHub Actions.
- Added `scheduled-validation.yml` for a weekly `make check`.
- Added `.github/dependabot.yml` for weekly action and lint tool updates.
- Added `make lint` with ruff, mypy, and yamllint pinned by hash in
  `requirements-dev.txt`. The `ci` workflow runs it in a `lint` job.
- Added a Python 3.11, 3.12, and 3.13 matrix to the `ci` checks job.
- Set a 15-minute timeout on the `checks`, `lint`, CodeQL `analyze`, and
  scheduled `validate` jobs.

### Changed

- Moved write permissions to job level in `quality-review-pr.yml` and
  `security-review-pr.yml`.
- Fixed D1 to read hash-format requirement files with line continuations.
- Limited D5 runtime declarations to `requirements.txt` and `pyproject.toml`.
- Fixed ruff and mypy findings in the checker code. Marked the command line
  scripts executable.
- Enabled the ruff pylint (PL) and bandit (S) rule families. Five S603 and
  S310 findings have no code fix. `make lint` fails on them by decision.
- Resolved `git` to an absolute path in `ci/build_pr_case.py`.
- Fixed empty quality review reports. `ci/call_model.py` sends `think: false`
  to Ollama and raises `ModelCallError` on empty model text.

### Deprecated

- `ci.call_model.call_model` takes `options=CallOptions(...)`. The
  `transport`, `profile_path`, and `api_key` parameters still work by position
  or keyword and emit a `DeprecationWarning`.

## [0.2.0] (2026-09-30)

### Added

- Added `.github/workflows/security-review-pr.yml`. The workflow runs the
  `abuzucom/foucault` v3.3.14 security review on pull requests from a pinned
  checkout.
- Added `docs/pr-security-review.md`.
- Recorded the foucault pin in `adopters/README.md` and `README.md`.

## [0.1.0] (2026-09-30)

### Added

- Added `AGENTS.md` as a tailored import of the `abuzucom/agents` policy text
  at commit `5b90aec191deccd474312ca4343ed8e47e83ab06`.
- Added `QUALITY.md` with four review modes, 41 classes, four tiers, hard
  blockers, and the `VERDICT_JSON` schema version 1.
- Added `scripts/check_quality_policy.py` and its tests.
- Added the `Makefile` and the `ci` workflow.
- Added `scripts/check_code_quality.py` with heuristic checkers for Q3, Q5, Q8,
  Q9, Q11, Q13, M1, M11, M12, M13, M16, M17, M18, C3, D1, D2, and D5.
- Added the `eval/` golden corpus with 38 cases and `eval/run_eval.py`.
- Added `scripts/review_report.py` and `scripts/review_envelope.py` for report
  parsing and the review envelope.
- Clarified that Blocking and Escalate findings rate HIGH in File, Piece, and
  Wholesale modes.
- Added the PR quality review: `ci/build_pr_case.py`, `ci/call_model.py`,
  `ci/check_review_response.py`, `ci/run_review.py`, and
  `ci/model_providers.json` with Ollama `kimi-k2.7-code` as the active profile.
- Added the reusable `quality-review` workflow and the `quality-review-pr`
  caller for this repository.
- Added `scripts/quality_diff_report.py` and a `ci` step that fails class or
  tier changes without an eval case.
- Added `docs/pr-quality-review.md` and `adopters/README.md`.
- Rewrote `README.md` around the review contract and the foucault boundary.
