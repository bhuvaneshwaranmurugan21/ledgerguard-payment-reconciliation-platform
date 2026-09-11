"""AWS Glue entrypoint for the qualified Stage 5 successor runtime."""

from ledgerguard_control.successor_job import main

raise SystemExit(main())
