.PHONY: quality foundation

foundation:
	ledgerguard-foundation

quality:
	ruff format --check .
	ruff check .
	mypy src
	pytest
	ledgerguard-foundation
