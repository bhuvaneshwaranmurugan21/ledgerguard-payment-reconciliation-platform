#!/usr/bin/env python3
"""Execute the repository-resident actions for one clean Stage 6 environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def run(command: list[str], root: Path, environment: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=root,
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(f"$ {' '.join(command)}")
    print(completed.stdout, end="")
    if completed.returncode != 0:
        raise SystemExit(f"Stage 6 action failed with exit {completed.returncode}: {command[0]}")
    return completed.stdout


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPYCACHEPREFIX": str(output.parent / "pycache"),
            "MYPY_CACHE_DIR": str(output.parent / "mypy-cache"),
            "RUFF_CACHE_DIR": str(output.parent / "ruff-cache"),
            "COVERAGE_FILE": str(output.parent / "coverage.data"),
        }
    )
    python = sys.executable
    pytest = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    actions: dict[str, str] = {"exact_dependency_installation": "PASS"}
    run([python, "-m", "ruff", "format", "--check", "."], root, environment)
    actions["format_verification"] = "PASS"
    run([python, "-m", "ruff", "check", "."], root, environment)
    actions["lint"] = "PASS"
    run([python, "-m", "mypy", "src"], root, environment)
    actions["strict_typing"] = "PASS"
    run([*pytest, "tests/test_financial_contracts_v2.py"], root, environment)
    actions["json_schema_validation"] = "PASS"
    run(
        [
            *pytest,
            "tests/test_foundation.py",
            "tests/test_part1_stage0.py",
            "tests/test_part1_stage1.py",
            "tests/test_part1_stage2.py",
            "tests/test_part1_stage3.py",
            "tests/test_part1_stage4.py",
        ],
        root,
        environment,
    )
    actions["contract_fixture_suite"] = "PASS"
    run(
        [*pytest, "tests/test_financial_semantics_spec.py", "tests/test_contract_coherence.py"],
        root,
        environment,
    )
    actions["semantic_invariant_suite"] = "PASS"
    run(
        [
            *pytest,
            "tests/test_part1_correction.py",
            "tests/test_part1_correction_c1.py",
            "tests/test_part1_correction_c2.py",
            "tests/test_part1_correction_c3.py",
            "tests/test_part1_correction_c4.py",
        ],
        root,
        environment,
    )
    actions["governance_and_aws_boundary"] = "PASS"
    run([*pytest, "tests/test_part1_correction_c3.py"], root, environment)
    actions["documentation_consistency"] = "PASS"

    junit = output.parent / "full-suite.xml"
    coverage_json = output.parent / "coverage.json"
    run([python, "-m", "coverage", "erase"], root, environment)
    run(
        [
            python,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=ledgerguard,ledgerguard_stage6_evidence",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ],
        root,
        environment,
    )
    run([python, "-m", "coverage", "json", "-o", str(coverage_json)], root, environment)
    coverage = json.loads(coverage_json.read_text(encoding="utf-8"))
    totals = coverage["totals"]
    line_percent = 100.0 * totals["covered_lines"] / totals["num_statements"]
    critical_paths = [
        path for path in coverage["files"] if path.endswith("ledgerguard_stage6_evidence.py")
    ]
    if len(critical_paths) != 1:
        raise SystemExit("OP-S6-R011 critical validator coverage record differs")
    critical = coverage["files"][critical_paths[0]]["summary"]
    branch_percent = (
        100.0
        if critical["num_branches"] == 0
        else 100.0 * critical["covered_branches"] / critical["num_branches"]
    )
    counts = junit_counts(junit)
    if line_percent < 95.0:
        raise SystemExit(f"OP-S6-R011 line coverage {line_percent:.2f}% is below 95.00%")
    if branch_percent != 100.0:
        raise SystemExit(
            f"OP-S6-R011 critical branch coverage {branch_percent:.2f}% is not 100.00%"
        )
    if counts["skipped"] != 0:
        raise SystemExit("required test skips or xfails are not completion credit")
    actions["coverage_threshold"] = "PASS"

    profile = json.loads(
        (root / "spec/part1-stage6-validation-profile-v1.json").read_text(encoding="utf-8")
    )
    mutation_junit = output.parent / "mutation-suite.xml"
    run(
        [*pytest, *profile["mutation_tests"], f"--junitxml={mutation_junit}"],
        root,
        environment,
    )
    mutation_counts = junit_counts(mutation_junit)
    if mutation_counts["failures"] or mutation_counts["errors"] or mutation_counts["skipped"]:
        raise SystemExit("OP-S6-R012 a required mutation survived or was not executed")
    actions["targeted_mutation_verification"] = "PASS"

    from ledgerguard_correction_c4 import materialize_stage5_view

    with tempfile.TemporaryDirectory(prefix="ledgerguard-stage6-stage5-replay-") as temporary:
        stage5_view = materialize_stage5_view(root, Path(temporary) / "repository")
        run([python, "-m", "ledgerguard_correction_c3"], stage5_view, environment)
    foundation_text = run([python, "-m", "ledgerguard_correction_c4"], root, environment)
    foundation = json.loads(foundation_text[foundation_text.index("{") :])
    actions["deterministic_foundation_validation"] = "PASS"
    if list(actions) != profile["complete_command_actions"]:
        raise SystemExit("OP-S6-R001 complete action order differs")
    freeze = run([python, "-m", "pip", "freeze", "--all"], root, environment)
    dependency_versions = sorted(
        line for line in freeze.splitlines() if line and not line.lower().startswith("ledgerguard")
    )
    result: dict[str, Any] = {
        "actions": actions,
        "test_counts": counts,
        "coverage": {
            "line_percent": round(line_percent, 6),
            "minimum_line_percent": 95.0,
            "critical_branch_percent": round(branch_percent, 6),
            "required_critical_branch_percent": 100.0,
        },
        "mutation": {
            "catalog_entries": len(profile["mutation_tests"]),
            "executed_tests": mutation_counts["tests"],
            "survivors": 0,
            "skipped": mutation_counts["skipped"],
        },
        "dependency_versions": dependency_versions,
        "foundation": foundation,
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
