# Adopter: infiniteprep

See `docs/pr-quality-review.md` for the architecture and trust boundary this
record assumes.

## Pins

- `QUALITY.md`: commit `1a3f67cba9d6ed7f45af4822f9ca27dd14db6a46`, through
  `quality_ref`.
- `quality-review.yml`: the same commit, through the `uses:` pin.

## Wiring

- `.github/workflows/quality-review-pr.yml` mirrors this repository's caller.
  It triggers on completion of the adopter's `ci` workflow. The wiring lands
  in draft pull request abuzucom/infiniteprep#1.
- The review job grants `actions: read` beside `contents: read`,
  `pull-requests: write`, and `checks: write`. The reusable review job
  requests each of these permissions.
- The provider profile is the euler default. The caller maps the
  `OLLAMA_API_KEY` repository secret to `MODEL_API_KEY`.
- `exclude_paths` is empty.
- `fail_on_block: true`. Fork pull requests receive a skipped
  `quality-review` check and no secret.
- `tests/test_review_wiring.py` in the adopter checks the trigger, the pins,
  the permissions, the secret mapping, the fork skip, and the action pins.

## Customization

None. `QUALITY.md` loads unmodified from the pinned commit.

## Local wiring record

The adopter records this adoption in its own `docs/pr-review.md`.
