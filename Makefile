.PHONY: check evidence
check:
	ruff check .
	mypy src
	pytest
evidence:
	python -m ledgerguard.cli simulate --output evidence/local-simulation.json

