#!/usr/bin/env python3
"""Validate one clean Part 2 Stage 2 oracle environment."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from ledgerguard_part2_stage2 import validate_stage2
from ledgerguard_part2_stage2_evidence import parse_junit_counts, run_mutation_checks


def execute(command: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    output = arguments.output.resolve()
    if root == output.parent or root in output.parents:
        raise SystemExit("Stage 2 output must be outside the source repository")
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("Stage 2 requires exact CPython 3.11.13")

    junit = output.parent / "pytest.xml"
    coverage_json = output.parent / "coverage.json"
    execute([sys.executable, "-m", "ruff", "format", "--check", "."], root)
    execute([sys.executable, "-m", "ruff", "check", "."], root)
    execute([sys.executable, "-m", "mypy", "src"], root)
    execute(
        [sys.executable, "-m", "pytest", "--junitxml", str(junit), str(root / "tests")],
        root,
    )
    execute([sys.executable, "-m", "coverage", "erase"], root)
    execute(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=ledgerguard_reference_oracle",
            "-m",
            "pytest",
            str(root / "tests/test_part2_stage2_oracle.py"),
        ],
        root,
    )
    execute([sys.executable, "-m", "coverage", "report", "--fail-under=100"], root)
    execute([sys.executable, "-m", "coverage", "json", "-o", str(coverage_json)], root)
    coverage = json.loads(coverage_json.read_text())
    totals = coverage["totals"]
    if totals["percent_covered"] != 100.0:
        raise SystemExit("Stage 2 oracle coverage is not 100 percent")

    authority = validate_stage2(root)
    mutations = run_mutation_checks(root)
    dependencies = sorted(
        line
        for line in subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze", "--all"], text=True
        ).splitlines()
        if not line.lower().startswith("ledgerguard")
    )
    result = {
        "actions": [
            "ruff-format",
            "ruff-check",
            "mypy-strict",
            "full-pytest",
            "oracle-branch-coverage",
            "semantic-mutations",
            "wheel-install-smoke",
        ],
        "test_counts": parse_junit_counts(junit),
        "coverage": {
            "percent": totals["percent_covered"],
            "statements": totals["num_statements"],
            "branches": totals["num_branches"],
            "missing_lines": totals["missing_lines"],
            "missing_branches": totals["missing_branches"],
        },
        "mutations": mutations,
        "dependency_versions": dependencies,
        "authority": authority,
        "toolchain": {
            "python": ".".join(map(str, sys.version_info[:3])),
            "jsonschema": version("jsonschema"),
            "pytest": version("pytest"),
            "ruff": version("ruff"),
            "mypy": version("mypy"),
        },
        "execution_boundary": {
            "aws_api_called": False,
            "aws_workflow_dispatched": False,
            "infrastructure_mutated": False,
            "production_reconciliation_executed": False,
            "authoritative_proof_persisted": False,
        },
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
