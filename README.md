# euler

Euler is a code quality and conventions review system for LLM-assisted software
development. It applies explicit rules to pull requests, files, fragments, and
whole codebases. It produces findings, evidence, and machine-readable verdicts.

## Relationship to foucault

`abuzucom/foucault` reviews security. Euler reviews code quality and
conventions. The two reviewers run side by side. `QUALITY.md` section 9 routes
security findings to foucault. Dependency classes overlap by design.

## Policy

[`QUALITY.md`](QUALITY.md) defines the review contract. A model reviewer loads
it as the system prompt. The contract defines these parts:

- **Four review modes.** PR, File, Piece, and Wholesale.
- **Classes.** Correctness (Q), maintainability (M), conventions (C), and
  dependencies (D).
- **Tiers.** Blocking, Escalate, Graded, and Advisory.
- **Verdicts.** `APPROVE | BLOCK | NEEDS-HUMAN` for PRs. `RISK` summaries for
  the other modes. A `VERDICT_JSON` line on every mode.

The rules derive from a reviewed subset of the `abuzucom/vibe-check` list plus
approved additions.

| Tier | Effect |
|---|---|
| Blocking | Any finding gives BLOCK. |
| Escalate | Any finding gives NEEDS-HUMAN. The check fails as for BLOCK. |
| Graded | The model rates each finding. HIGH gives BLOCK. |
| Advisory | Always LOW. The verdict stays unaffected. |

| ID | Class | Tier |
|---|---|---|
| Q1 | Contradictory or impossible logic | Blocking |
| Q2 | Unintended global or request-state caching | Graded |
| Q3 | Catastrophic regex backtracking | Graded +script |
| Q4 | Unchecked divisor | Blocking |
| Q5 | Unreachable dead code | Graded +script |
| Q6 | Obvious performance drains | Graded |
| Q7 | Single responsibility | Advisory |
| Q8 | Mutation during iteration | Graded +script |
| Q9 | Recursion without a depth limit | Graded +script |
| Q10 | Concurrency | Graded |
| Q11 | Resource leaks | Blocking +script |
| Q12 | Hallucinated APIs | Blocking |
| Q13 | Language traps | Graded +script |
| Q14 | Missing idempotency | Graded |
| M1 | Empty or swallowing catch blocks | Blocking +script |
| M2 | Non-descriptive names | Advisory |
| M3 | Function purpose not self-evident | Advisory |
| M4 | Large undocumented anonymous functions | Advisory |
| M5 | Needlessly verbose code | Advisory |
| M6 | Broken public API contract | Escalate |
| M7 | Deep nesting | Advisory |
| M8 | Long functions | Advisory |
| M9 | Break in nested loops | Advisory |
| M10 | Duplication | Blocking |
| M11 | Magic numbers | Blocking |
| M12 | Incomplete work | Blocking +script |
| M13 | Suppressed checks | Blocking +script |
| M14 | Comment drift | Graded |
| M15 | Over-engineering | Graded |
| M16 | Broad catch or uninformative error | Graded +script |
| M17 | Debug leftovers | Graded +script |
| M18 | Hardcoded environment values | Graded +script |
| C1 | Repository convention deviation | Graded |
| C2 | Test integrity | Escalate |
| C3 | Untested changes | Graded +script |
| D1 | Unpinned versions | Escalate +script |
| D2 | Lockfile drift | Escalate +script |
| D3 | Unjustified new dependency | Escalate |
| D4 | Redundant or overlapping dependencies | Graded |
| D5 | Unused or undeclared dependencies | Graded +script |
| D6 | Deprecated or stale dependencies | Graded |

`+script` marks classes with a deterministic heuristic checker in
`scripts/check_code_quality.py`.

## Operational use

1. Load `QUALITY.md` as the system prompt before the review target.
2. Select the review mode from the supplied material.
3. Supply prescan output from the deterministic checkers when available.
4. Require the mode-specific final line and the `VERDICT_JSON` line.

## Versioning

Pin a tag or full commit SHA when loading `QUALITY.md`. `CHANGELOG.md` records
every change to a class, a tier, a hard blocker, or the `VERDICT_JSON` schema.

## Checks

Run `make check` for the full local suite. `.github/workflows/ci.yml` runs the
same target on Python 3.11, 3.12, and 3.13 on every pull request.

Run `make lint` for ruff, mypy, and yamllint. Install the tools first with
`pip install --require-hashes -r requirements-dev.txt`. The `ci` workflow runs
`make lint` in a separate job.

Other workflows cover the time between pull requests:

- `codeql.yml` scans the Python sources and the workflows on pull requests,
  pushes to `main`, and a weekly schedule.
- `scheduled-validation.yml` runs `make check` weekly and on manual dispatch.
- `.github/dependabot.yml` opens weekly update PRs for the pinned actions and
  lint tools.

`scripts/check_quality_policy.py` validates `QUALITY.md`. The checker enforces
these properties:

- every class ID with a valid tier
- the verdict tokens
- unique headings
- ASCII text and LF line endings
- prose lines of 120 characters or fewer
- no prose dashes
- the 32 KiB size cap

## Eval corpus

[`eval/`](eval/README.md) holds the golden corpus. `python3 eval/run_eval.py`
validates its structure. `--model-call module:function` runs it against a real
model.

## PR quality review

[`quality-review.yml`](.github/workflows/quality-review.yml) reviews one pull
request against `QUALITY.md`. The workflow runs the deterministic checkers,
calls the configured model, validates the report, posts a comment, and gates
on the verdict. [`quality-review-pr.yml`](.github/workflows/quality-review-pr.yml)
calls it for this repository after `ci` completes. The active provider is
Ollama with `kimi-k2.7-code`. The caller maps the `OLLAMA_API_KEY` secret to
`MODEL_API_KEY`. See [`docs/pr-quality-review.md`](docs/pr-quality-review.md)
for the event flow, the trust boundary, and adoption steps.

## PR security review

[`security-review-pr.yml`](.github/workflows/security-review-pr.yml) runs the
`abuzucom/foucault` security review on this repository's pull requests. The
workflow pins foucault v3.3.14 and runs its adapter from a pinned checkout.
The caller maps the `OLLAMA_API_KEY` secret to `MODEL_API_KEY`. See
[`docs/pr-security-review.md`](docs/pr-security-review.md) for the wiring,
the trust boundary, and upgrade steps.

## Agent policy

[`AGENTS.md`](AGENTS.md) governs agents working in this repository. It holds a
tailored import of the `abuzucom/agents` policy text. Most of its rules have no
mechanical enforcement here. Its enforcement section lists the checks that
exist.
