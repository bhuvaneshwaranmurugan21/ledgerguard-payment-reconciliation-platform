#!/usr/bin/env python3
"""Prove the Stage 4 inspector repair against a real external Stage 3 artifact."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from tools.inspect_part3_stage3_ci_artifact import inspect
from tools.validate_part3_stage4_handoff import BASELINE_COMMIT


def require_inventory_rejection(error: str | None) -> None:
    if error is None:
        raise AssertionError("undeclared nested manifest accepted")
    if "member set differs" not in error:
        raise ValueError("unexpected inspection rejection: " + error)


def require_equal_acceptance(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    if actual != expected:
        raise AssertionError("genuine artifact acceptance changed")


def execute(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise ValueError("fresh output directory required")
    # Inspect the source before copying, so source symlinks cannot be dereferenced silently.
    accepted = inspect(source, BASELINE_COMMIT, 34465749986, 1)
    shutil.copytree(source, destination, symlinks=True)
    negatives = []
    for relative in ["run-1/artifact-manifest.json", "run-1/profiles/artifact-manifest.json"]:
        extra = destination / relative
        extra.write_bytes(b"undeclared adversarial member\n")
        try:
            rejection = None
            try:
                inspect(destination, BASELINE_COMMIT, 34465749986, 1)
            except ValueError as error:
                rejection = str(error)
            require_inventory_rejection(rejection)
            negatives.append({"path": relative, "rejected": True})
        finally:
            extra.unlink()
    require_equal_acceptance(inspect(destination, BASELINE_COMMIT, 34465749986, 1), accepted)
    return {"genuine_artifact": accepted, "negative_cases": negatives, "aws_execution": False}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(execute(args.source, args.destination), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
