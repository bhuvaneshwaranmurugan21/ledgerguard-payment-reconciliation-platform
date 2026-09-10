#!/usr/bin/env python3
"""Run two clean Stage 3 qualifications and bind their deterministic evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes

BASE_COMMIT = "d0fb01392f7f975909229f418c13a9c73ba8395e"
BASE_TREE = "6be2444b583fde20d6fd84d47a87cde9432e2952"
BASE_PARENT = "aa136331e44dcd181f766b42d76ee2616a22f435"
OWNED_INCLUDE = ",".join(
    (
        "src/ledgerguard/stage3/*",
        "tools/build_part3_stage3_runtime.py",
        "tools/inspect_part3_stage3_artifact.py",
        "tools/validate_part3_stage3.py",
        "tools/run_part3_stage3.py",
        "tools/run_part3_stage3_mutations.py",
        "tools/build_part3_stage3_ci_evidence.py",
        "tools/inspect_part3_stage3_ci_artifact.py",
    )
)
STAGE3_TESTS = (
    "tests/test_part3_stage3_assets.py",
    "tests/test_part3_stage3_controls.py",
    "tests/test_part3_stage3_failures.py",
    "tests/test_part3_stage3_job.py",
    "tests/test_part3_stage3_package.py",
    "tests/test_part3_stage3_spark.py",
    "tests/test_part3_stage3_tooling.py",
)
CURRENT_COMPATIBILITY_TESTS = (
    "tests/test_financial_contracts_v2.py",
    "tests/test_financial_semantics_spec.py",
    "tests/test_part2_stage3_admission.py",
    "tests/test_part2_stage4_transaction.py",
    "tests/test_part2_stage5_settlement.py",
    "tests/test_part2_stage6_finalization.py",
    "tests/test_part2_stage7_spark_parity.py",
)


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=repository, text=True).strip()


def _identity(path: Path) -> dict[str, Any]:
    digest = sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return {"path": path.as_posix(), "size_bytes": size, "sha256": digest.hexdigest()}


def _execute(repository: Path, command: list[str], environment: dict[str, str]) -> None:
    subprocess.run(command, cwd=repository, env=environment, check=True)


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = root.findall("testsuite") if root.tag != "testsuite" else [root]
    counts = {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if counts["tests"] <= 0 or any(counts[key] for key in ("failures", "errors", "skipped")):
        raise SystemExit(f"test execution is not complete and green: {path.name}")
    return counts


def _qualification(repository: Path, output: Path, environment: dict[str, str]) -> dict[str, Any]:
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("Stage 3 runner requires exact CPython 3.11.13")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        if environment.get(name):
            raise SystemExit(f"Stage 3 forbids AWS credential environment: {name}")
    environment = dict(environment)
    environment["PYSPARK_PYTHON"] = sys.executable
    environment["PYSPARK_DRIVER_PYTHON"] = sys.executable
    output.mkdir()
    _execute(repository, [sys.executable, "-m", "ruff", "check", "."], environment)
    _execute(
        repository,
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "src/ledgerguard/stage3",
            "tools/build_part3_stage3_runtime.py",
            "tools/inspect_part3_stage3_artifact.py",
            "tools/validate_part3_stage3.py",
            "tools/run_part3_stage3.py",
            "tools/run_part3_stage3_mutations.py",
            "tools/build_part3_stage3_ci_evidence.py",
            "tools/inspect_part3_stage3_ci_artifact.py",
        ],
        environment,
    )
    coverage_file = output / ".coverage"
    focused_junit = output / "focused-tests.xml"
    coverage_environment = dict(environment, COVERAGE_FILE=str(coverage_file))
    _execute(repository, [sys.executable, "-m", "coverage", "erase"], coverage_environment)
    _execute(
        repository,
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=ledgerguard.stage3,tools",
            "-m",
            "pytest",
            "-q",
            "--junitxml",
            str(focused_junit),
            *STAGE3_TESTS,
        ],
        coverage_environment,
    )
    _execute(
        repository,
        [
            sys.executable,
            "-m",
            "coverage",
            "report",
            "--fail-under=100",
            f"--include={OWNED_INCLUDE}",
        ],
        coverage_environment,
    )
    coverage_json = output / "coverage.json"
    _execute(
        repository,
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            "-o",
            str(coverage_json),
            f"--include={OWNED_INCLUDE}",
        ],
        coverage_environment,
    )
    mutation_output = output / "mutations"
    _execute(
        repository,
        [
            sys.executable,
            "tools/run_part3_stage3_mutations.py",
            "--root",
            str(repository),
            "--output",
            str(mutation_output),
        ],
        environment,
    )
    compatibility_junit = output / "current-compatibility-tests.xml"
    _execute(
        repository,
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml",
            str(compatibility_junit),
            *CURRENT_COMPATIBILITY_TESTS,
        ],
        environment,
    )
    coverage = json.loads(coverage_json.read_text())
    mutation_rows = json.loads((mutation_output / "results.json").read_text())
    if coverage["totals"]["percent_covered"] != 100.0:
        raise SystemExit("Stage 3 owned coverage differs from 100%")
    if len(mutation_rows) != 24 or any(not row["killed"] for row in mutation_rows):
        raise SystemExit("Stage 3 semantic mutation qualification differs")
    return {
        "focused_tests": _junit_counts(focused_junit),
        "current_compatibility_tests": _junit_counts(compatibility_junit),
        "coverage": coverage["totals"],
        "mutations": {"total": len(mutation_rows), "killed": len(mutation_rows)},
        "ruff": "PASS",
        "mypy_strict": "PASS",
        "aws_credentials_present": False,
    }


def run(repository: Path, output: Path, clean_runs: int) -> dict[str, Any]:
    repository = repository.resolve()
    output = output.resolve()
    if clean_runs != 2:
        raise SystemExit("Stage 3 qualification requires exactly two clean runs")
    if repository == output or repository in output.parents:
        raise SystemExit("Stage 3 output must be outside the repository")
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Stage 3 output directory must be empty")
    if _git(repository, "status", "--porcelain"):
        raise SystemExit("Stage 3 exact-head qualification requires a clean worktree")
    head = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    if _git(repository, "show", "-s", "--format=%T", BASE_COMMIT) != BASE_TREE:
        raise SystemExit("Stage 3 base tree differs")
    if _git(repository, "show", "-s", "--format=%P", BASE_COMMIT) != BASE_PARENT:
        raise SystemExit("Stage 3 base parent differs")
    source_date_epoch = _git(repository, "show", "-s", "--format=%ct", head)
    if not source_date_epoch.isdigit() or int(source_date_epoch) < 315532800:
        raise SystemExit("Stage 3 head timestamp is invalid")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASE_COMMIT, head], cwd=repository, check=False
    )
    if ancestor.returncode != 0:
        raise SystemExit("Stage 3 head does not descend from the exact base")
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    qualification = _qualification(repository, output / "qualification", environment)
    results: list[dict[str, Any]] = []
    for index in range(1, clean_runs + 1):
        run_root = output / f"run-{index}"
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = str(index * 730031)
        environment["SOURCE_DATE_EPOCH"] = source_date_epoch
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.validate_part3_stage3",
                "--repository",
                str(repository),
                "--output",
                str(run_root),
                "--source-commit",
                head,
                "--source-tree",
                tree,
            ],
            cwd=repository,
            env=environment,
            check=True,
        )
        results.append(json.loads((run_root / "validation-result.json").read_text()))
    payloads = [row["deterministic_payload"] for row in results]
    encoded = [canonical_bytes(row) for row in payloads]
    if encoded[0] != encoded[1]:
        raise SystemExit("Stage 3 clean-run deterministic payloads differ")
    payload_sha = sha256(encoded[0]).hexdigest()
    if any(row["deterministic_payload_sha256"] != payload_sha for row in results):
        raise SystemExit("Stage 3 clean-run payload digest differs")
    evidence = {
        "schema_version": "1.0",
        "project": "ledgerguard-payment-reconciliation-platform",
        "part": 3,
        "stage": 3,
        "base_commit": BASE_COMMIT,
        "head_sha": head,
        "head_tree": tree,
        "clean_run_count": 2,
        "deterministic_equal": True,
        "deterministic_payload_sha256": payload_sha,
        "deterministic_payload": payloads[0],
        "qualification": qualification,
        "spark_physical_evidence": [row["spark_physical_evidence"] for row in results],
        "telemetry": [row["telemetry"] for row in results],
        "verdict": "PASS",
        "aws_execution": False,
        "managed_workload_execution": False,
        "authoritative_proof": False,
        "external_squash_gate": "PENDING_USER_CONTROLLED_MERGE",
    }
    evidence_path = output / "part3-stage3-local-evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    members = [
        _identity(path).copy()
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact-manifest.json"
    ]
    for row in members:
        row["path"] = Path(row["path"]).relative_to(output).as_posix()
    manifest = {
        "schema_version": "1.0",
        "head_sha": head,
        "head_tree": tree,
        "members": members,
    }
    manifest["manifest_sha256"] = sha256(canonical_bytes(manifest)).hexdigest()
    (output / "artifact-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clean-runs", type=int, default=2)
    arguments = parser.parse_args()
    evidence = run(arguments.repository, arguments.output, arguments.clean_runs)
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
