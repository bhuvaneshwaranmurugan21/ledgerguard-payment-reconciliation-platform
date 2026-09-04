#!/usr/bin/env python3
"""Validate one exact Part 2 Stage 7 Spark environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pyspark

from ledgerguard_part2_stage1_evidence import parse_junit_counts
from ledgerguard_part2_stage7_evidence import run_mutation_checks
from ledgerguard_part2_stage7_validation import validate_stage7


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
        raise SystemExit("Stage 7 output must be outside the repository")
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("Stage 7 requires exact CPython 3.11.13")
    if pyspark.__version__ != "3.5.6" or version("py4j") != "0.10.9.7":
        raise SystemExit("Stage 7 Spark dependency versions differ")
    if (
        os.environ.get("PYSPARK_PYTHON") != sys.executable
        or os.environ.get("PYSPARK_DRIVER_PYTHON") != sys.executable
    ):
        raise SystemExit("Stage 7 Spark driver and worker interpreters differ")
    java = subprocess.check_output(
        ["java", "-version"], stderr=subprocess.STDOUT, text=True
    ).splitlines()[0]
    if '"17.' not in java:
        raise SystemExit(f"Stage 7 Java major differs: {java}")

    junit = output.parent / "pytest.xml"
    coverage_json = output.parent / "coverage.json"
    execute([sys.executable, "-m", "ruff", "format", "--check", "."], root)
    execute([sys.executable, "-m", "ruff", "check", "."], root)
    execute([sys.executable, "-m", "mypy", "src"], root)
    execute([sys.executable, "-m", "pytest", "--junitxml", str(junit), str(root / "tests")], root)
    execute([sys.executable, "-m", "coverage", "erase"], root)
    execute(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=ledgerguard_part2_stage7_spark",
            "-m",
            "pytest",
            str(root / "tests/test_part2_stage7_spark_parity.py"),
        ],
        root,
    )
    execute([sys.executable, "-m", "coverage", "report", "--fail-under=100"], root)
    execute([sys.executable, "-m", "coverage", "json", "-o", str(coverage_json)], root)
    totals = json.loads(coverage_json.read_text())["totals"]
    authority = validate_stage7(root)
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
            "genuine-spark-parity",
            "parquet-write-read",
            "spark-parity-branch-coverage",
            "failure-matrix",
            "critical-paths",
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
            "python": "3.11.13",
            "java_major": 17,
            "spark": pyspark.__version__,
            "py4j": version("py4j"),
            "spark_master": "local[2]",
            "ansi": True,
            "timezone": "UTC",
            "driver_worker_python_equal": True,
        },
        "execution_boundary": {
            "spark_executed": True,
            "parquet_written_and_read": True,
            "spark_authoritative": False,
            "aws_api_called": False,
            "aws_workflow_dispatched": False,
            "managed_persistence": False,
            "infrastructure_mutated": False,
        },
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
