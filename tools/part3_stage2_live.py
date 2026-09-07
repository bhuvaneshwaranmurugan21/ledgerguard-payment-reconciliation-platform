#!/usr/bin/env python3
"""Dispatch exact-main Part 3 Stage 2 AWS qualification operations."""

from __future__ import annotations

import argparse
from pathlib import Path

from part3_stage2_runtime import run_capability, run_read_only, run_recovery


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read-only")
    read.add_argument("--expected-sha", required=True)
    read.add_argument("--output", type=Path, required=True)
    capability = sub.add_parser("capability")
    capability.add_argument("--expected-sha", required=True)
    capability.add_argument("--preflight-run-id", required=True)
    capability.add_argument("--preflight-run-attempt", required=True)
    capability.add_argument("--preflight-artifact-id", required=True)
    capability.add_argument("--preflight-artifact-sha256", required=True)
    capability.add_argument("--preflight-inspection-sha256", required=True)
    capability.add_argument("--output", type=Path, required=True)
    recovery = sub.add_parser("recovery")
    recovery.add_argument("--expected-sha", required=True)
    recovery.add_argument("--failed-run-id", required=True)
    recovery.add_argument("--failed-run-attempt", required=True)
    recovery.add_argument("--failed-artifact-id", required=True)
    recovery.add_argument("--journal-sha256", required=True)
    recovery.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "read-only":
        run_read_only(args.expected_sha, args.output)
    elif args.command == "capability":
        run_capability(
            args.expected_sha,
            {
                "run_id": args.preflight_run_id,
                "run_attempt": args.preflight_run_attempt,
                "artifact_id": args.preflight_artifact_id,
                "artifact_sha256": args.preflight_artifact_sha256,
                "inspection_sha256": args.preflight_inspection_sha256,
            },
            args.output,
        )
    else:
        run_recovery(
            args.expected_sha,
            args.failed_run_id,
            args.failed_run_attempt,
            args.failed_artifact_id,
            args.journal_sha256,
            args.output,
        )


if __name__ == "__main__":
    main()
