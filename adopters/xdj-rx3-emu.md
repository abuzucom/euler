# Adopter: xdj-rx3-emu

See `docs/pr-quality-review.md` for the architecture and trust boundary this
record assumes.

## Pins

- `QUALITY.md`: commit `b23947068a328c19215f8ade3db7bd2b4bcb05cc`, through
  `quality_ref`.
- `quality-review.yml`: the same commit, through the `uses:` pin.

## Wiring

- `.github/workflows/quality-review-pr.yml` mirrors this repository's caller.
  It triggers on completion of the adopter's `ci` workflow.
- The provider profile is the euler default. The caller maps the
  `OLLAMA_API_KEY` repository secret to `MODEL_API_KEY`.
- `exclude_paths` is empty.
- `fail_on_block: true`. Fork pull requests receive a skipped
  `quality-review` check and no secret.
- `tests/test_quality_review_wiring.py` in the adopter checks the trigger,
  the pins, the secret mapping, the fork skip, and the action pins.

## Customization

None. `QUALITY.md` loads unmodified from the pinned commit.

## Local wiring record

The adopter records this adoption in its own `docs/pr-quality-review.md`.
