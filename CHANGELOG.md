# Changelog

This file documents every notable project change.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows Semantic Versioning. Pin a tag or commit SHA when
loading `QUALITY.md` into a deployment.

## [0.3.0] (2026-09-30)

### Added

- Added `codeql.yml` for CodeQL scanning of Python and GitHub Actions.
- Added `scheduled-validation.yml` for a weekly `make check`.
- Added `.github/dependabot.yml` for weekly action and lint tool updates.
- Added `make lint` with ruff, mypy, and yamllint pinned by hash in
  `requirements-dev.txt`. The `ci` workflow runs it in a `lint` job.
- Added a Python 3.11, 3.12, and 3.13 matrix to the `ci` checks job.

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
