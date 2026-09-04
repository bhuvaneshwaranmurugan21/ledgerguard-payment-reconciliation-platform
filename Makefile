.PHONY: quality foundation stage6 stage7 part2-stage8 part2-stage8-closure

foundation:
	ledgerguard-foundation

quality:
	python tools/run_part1_stage6.py --clean-runs 2

stage6: quality

stage7:
	ledgerguard-stage7

part2-stage8:
	ledgerguard-part2-stage8

part2-stage8-closure:
	ledgerguard-part2-stage8-closure
