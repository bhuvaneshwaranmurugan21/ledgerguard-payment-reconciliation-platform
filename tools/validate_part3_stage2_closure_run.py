#!/usr/bin/env python3
"""Validate one exact Part 3 Stage 2 evidence-closure environment."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from ledgerguard_part2_stage1_evidence import parse_junit_counts
from ledgerguard_part3_stage2_closure import validate_stage2_closure
from ledgerguard_part3_stage2_closure_evidence import run_closure_mutation_checks


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
        raise SystemExit("closure output must be outside the repository")
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("closure validation requires exact CPython 3.11.13")
    junit = output.parent / "pytest.xml"
    coverage_json = output.parent / "coverage.json"
    tests = str(root / "tests/test_part3_closure_stage2.py")
    execute([sys.executable, "-m", "ruff", "format", "--check", "."], root)
    execute([sys.executable, "-m", "ruff", "check", "."], root)
    execute([sys.executable, "-m", "mypy", "src"], root)
    execute([sys.executable, "-m", "pytest", "--junitxml", str(junit), tests], root)
    execute([sys.executable, "-m", "coverage", "erase"], root)
    execute(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=ledgerguard_part3_stage2_closure",
            "-m",
            "pytest",
            tests,
        ],
        root,
    )
    execute([sys.executable, "-m", "coverage", "report", "--fail-under=100"], root)
    execute([sys.executable, "-m", "coverage", "json", "-o", str(coverage_json)], root)
    totals = json.loads(coverage_json.read_text(encoding="utf-8"))["totals"]
    authority = validate_stage2_closure(root)
    mutations = run_closure_mutation_checks(root)
    result = {
        "actions": [
            "ruff-format",
            "ruff-check",
            "mypy-strict",
            "closure-tests",
            "closure-branch-coverage",
            "closure-semantic-mutations",
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
        "dependency_versions": sorted(
            line
            for line in subprocess.check_output(
                [sys.executable, "-m", "pip", "freeze", "--all"], text=True
            ).splitlines()
            if not line.lower().startswith("ledgerguard")
        ),
        "authority": authority,
        "toolchain": {"python": "3.11.13", "jsonschema": version("jsonschema")},
        "execution_boundary": {
            "aws_api_called": False,
            "aws_workflow_dispatched": False,
            "infrastructure_mutated": False,
            "managed_reconciliation_started": False,
            "closure_merge_authorized": False,
            "part3_complete": False,
            "project_complete": False,
        },
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
