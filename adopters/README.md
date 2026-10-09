# Adopters

This directory records repositories that load `QUALITY.md` as a review
system prompt or call `.github/workflows/quality-review.yml`. See
`docs/pr-quality-review.md` for the wiring steps.

## Recording an adoption

Add `adopters/<repo>.md` with these facts:

- the pinned tag or full commit SHA of `QUALITY.md`
- the pinned commit SHA of `quality-review.yml`
- the provider profile and the secret mapped to `MODEL_API_KEY`
- whether fork reviews use `fork_review: true` and the `fork-review`
  environment secret
- the `exclude_paths` value
- any stack-specific customization

## Tags

Release tags follow the `CHANGELOG.md` versions, such as `v0.1.0`. Tag
creation requires active-human consent at release time. Pin a full commit SHA
in workflows even when a tag exists.

## Upstream adoptions

- `abuzucom/foucault` v3.3.14 at commit
  `06d74fba4d9013654cdaf9896bb7535724385186` runs through
  `.github/workflows/security-review-pr.yml`. See
  `docs/pr-security-review.md`.

## Current adopters

- `abuzucom/euler` reviews its own pull requests through
  `.github/workflows/quality-review-pr.yml`. The caller pins `quality_ref` to
  the default-branch commit of the run. The prescan excludes `eval/cases/**`.
- `abuzucom/xdj-rx3-emu` pins `quality-review.yml` and `quality_ref` to
  commit `b23947068a328c19215f8ade3db7bd2b4bcb05cc`. See
  [`xdj-rx3-emu.md`](xdj-rx3-emu.md).
