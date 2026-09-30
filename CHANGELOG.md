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
- Rewrote `README.md` around the review contract and the foucault boundary.
