# Changelog

This file documents every notable project change.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project follows Semantic Versioning. Pin a tag or commit SHA when
loading `QUALITY.md` into a deployment.

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
- Rewrote `README.md` around the review contract and the foucault boundary.
