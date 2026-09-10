"""AWS Glue 5.1 script for the exact LedgerGuard Stage 3 runtime wheel."""

from ledgerguard.stage3.job import main

if __name__ == "__main__":
    raise SystemExit(main())
