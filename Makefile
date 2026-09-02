.PHONY: quality foundation stage6

foundation:
	ledgerguard-foundation

quality:
	python tools/run_part1_stage6.py --clean-runs 2

stage6: quality
