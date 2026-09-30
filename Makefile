.PHONY: check test policy

# Overridable for platforms without this interpreter name:
#   make check PYTHON=py
PYTHON ?= python3

PROSE_DOCS = AGENTS.md README.md CHANGELOG.md

policy:
	$(PYTHON) scripts/check_quality_policy.py QUALITY.md
	for doc in $(PROSE_DOCS); do $(PYTHON) scripts/check_quality_policy.py $$doc --prose-only || exit 1; done

test:
	$(PYTHON) -m unittest discover -s tests

check: policy test
