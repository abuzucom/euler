# Eval harness

The golden corpus checks `QUALITY.md` against known cases. Each case under
`cases/` pairs a small fixture with the verdict a careful reviewer applying
`QUALITY.md` produces.

## Purpose

`QUALITY.md` is a system prompt. A well-written prompt gives no guarantee of
model compliance. The corpus turns trust in the prompt into a check. Any
`QUALITY.md` change to a verdict, a hard blocker, or a tier ships with a new or
updated case.

## Running

`python3 eval/run_eval.py` validates corpus structure only. `make check` runs
that mode. Structure checks cover these properties:

- every `expected.json` parses and holds the required keys
- the mode is PR, File, Piece, or Wholesale
- the expected verdict fits the mode
- every expected class exists in `QUALITY.md`
- PR cases hold `diff.patch` and other cases hold an `input.<ext>` file

`python3 eval/run_eval.py --model-call module:function` runs every case live.
The callable signature is `call_model(system_prompt, mode, case_text) -> str`.
The runner loads `QUALITY.md` as the system prompt. `case_text` holds the JSON
review envelope from `scripts/review_envelope.py`. Non-PR cases also carry
prescan candidates from `scripts/check_code_quality.py`.

`ci.call_model:call_model` provides the repository adapter. Set
`MODEL_API_KEY` outside the repository before a live run.

`--model-call` imports and executes code. Treat the value as trusted input.
Supply it only from a local invocation or CI configuration under repository
control. Never derive it from pull request content.

## Case format

```
eval/cases/<slug>/
  diff.patch | input.<ext>   the review unit
  context.md                 optional PR text or selection note
  expected.json              required
```

| Field | Meaning |
|---|---|
| `mode` | `PR`, `File`, `Piece`, or `Wholesale` |
| `expected_verdict` | Substring of the final line, such as `BLOCK` or `RISK: HIGH` |
| `expected_classes` | Exact set of class IDs the report must list in `VERDICT_JSON` |
| `expect_json` | `true` requires a parseable `VERDICT_JSON` line |
| `notes` | Why the verdict holds, for human reviewers |

## Current cases

| Case | Mode | Verdict | Classes |
|---|---|---|---|
| `advisory-bundle-pr` | PR | `APPROVE` | M2, M7, M8 |
| `api-break-pr` | PR | `NEEDS-HUMAN` | M6 |
| `broad-catch-file` | File | `RISK: MEDIUM` | M16 |
| `clean-file` | File | `RISK: NONE-FOUND` | none |
| `clean-pr` | PR | `APPROVE` | none |
| `contradictory-logic-file` | File | `RISK: HIGH` | Q1 |
| `debug-leftover-pr` | PR | `BLOCK` | M17 |
| `divide-by-zero-pr` | PR | `BLOCK` | Q4 |
| `docstring-drift-file` | File | `RISK: HIGH` | M14 |
| `dropped-classes-pr` | PR | `APPROVE` | none |
| `duplicated-utility-pr` | PR | `BLOCK` | M10 |
| `hallucinated-api-pr` | PR | `BLOCK` | Q12 |
| `hardcoded-host-file` | File | `RISK: MEDIUM` | M18 |
| `heavy-dependency-pr` | PR | `NEEDS-HUMAN` | D3 |
| `incomplete-work-pr` | PR | `BLOCK` | M12 |
| `magic-number-pr` | PR | `BLOCK` | M11 |
| `migration-idempotency-pr` | PR | `BLOCK` | Q14 |
| `missing-lockfile-pr` | PR | `NEEDS-HUMAN` | D2 |
| `mutable-default-file` | File | `RISK: HIGH` | Q13 |
| `mutation-during-iteration-file` | File | `RISK: HIGH` | Q8 |
| `overlapping-http-client-pr` | PR | `APPROVE` | D4 |
| `piece-unseen-caller` | Piece | `RISK (partial)` | none |
| `precedence-pr` | PR | `BLOCK` | M1, C2 |
| `prescan-dismissal-pr` | PR | `APPROVE` | none |
| `prompt-injection-pr` | PR | `BLOCK` | C1 |
| `request-cache-pr` | PR | `BLOCK` | Q2 |
| `resolved-q4-pr` | PR | `APPROVE` | none |
| `resource-leak-pr` | PR | `BLOCK` | Q11 |
| `security-only-pr` | PR | `APPROVE` | none |
| `superseded-major-pr` | PR | `APPROVE` | D6 |
| `suppressed-check-pr` | PR | `BLOCK` | M13 |
| `swallowed-exception-pr` | PR | `BLOCK` | M1 |
| `unawaited-task-file` | File | `RISK: HIGH` | Q10 |
| `unbounded-recursion-file` | File | `RISK: HIGH` | Q9 |
| `unpinned-deps-pr` | PR | `NEEDS-HUMAN` | D1 |
| `untested-branch-pr` | PR | `BLOCK` | C3 |
| `unused-dependency-pr` | PR | `APPROVE` | D5 |
| `unused-option-file` | File | `RISK: LOW` | M15 |
| `weakened-test-pr` | PR | `NEEDS-HUMAN` | C2 |
