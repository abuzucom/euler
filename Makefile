.PHONY: check test policy quality eval lint

# Overridable for platforms without this interpreter name:
#   make check PYTHON=py
PYTHON ?= python3

PROSE_DOCS = AGENTS.md README.md CHANGELOG.md eval/README.md docs/pr-quality-review.md docs/pr-security-review.md adopters/README.md
# The self-scan skips tests/ because test fixtures hold flagged patterns on purpose.
QUALITY_PATHS = scripts ci eval/run_eval.py

policy:
	$(PYTHON) scripts/check_quality_policy.py QUALITY.md
	for doc in $(PROSE_DOCS); do $(PYTHON) scripts/check_quality_policy.py $$doc --prose-only || exit 1; done

quality:
	$(PYTHON) scripts/check_code_quality.py all $(QUALITY_PATHS)

eval:
	$(PYTHON) eval/run_eval.py

# Needs the tools from requirements-dev.txt. make check stays standard-library only.
# The ruff steps follow the abuzucom/rough baseline. --ignore-noqa makes
# suppression comments ineffective. The warn tier reports and never fails.
RUFF_PATHS = scripts ci eval/run_eval.py tests

lint:
	$(PYTHON) -m ruff check --ignore-noqa $(RUFF_PATHS)
	$(PYTHON) -m ruff format --check $(RUFF_PATHS)
	$(PYTHON) -m ruff check --config ruff.warn.toml --ignore-noqa --exit-zero $(RUFF_PATHS)
	$(PYTHON) -m mypy
	$(PYTHON) -m yamllint --strict .github .yamllint.yml

test:
	$(PYTHON) -m unittest discover -s tests

check: policy quality eval test
