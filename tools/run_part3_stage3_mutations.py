#!/usr/bin/env python3
"""Execute every reviewed Stage 3 semantic mutation in an isolated repository copy."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from typing import Any

FAMILIES = {
    "financial_arithmetic",
    "skew_semantics",
    "split_allocation",
    "posting_sign",
    "profile_identity",
    "path_guard",
    "format_admission",
    "manifest_count",
    "independent_expectation",
    "campaign_determinism",
    "campaign_split",
    "spark_arithmetic",
    "reference_capacity",
    "join_grain",
    "settlement_formula",
    "authoritative_boundary",
    "package_allowlist",
    "package_inspection",
    "evidence_verdict",
    "no_aws_boundary",
    "candidate_completion",
    "source_identity",
}


def _copy_repository(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for name in ("src", "tools", "tests", "contracts", "spec", "glue", "requirements"):
        shutil.copytree(
            root / name,
            destination / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", ".pytest_cache"),
        )
    for name in ("pyproject.toml", "README.md", "PROJECT_STATUS.md", "LICENSE"):
        shutil.copy2(root / name, destination / name)


def run_mutations(root: Path, output: Path) -> list[dict[str, Any]]:
    registry = json.loads((root / "spec/part3-stage3-code-mutations-v1.json").read_text())
    rows = registry.get("mutations")
    if not isinstance(rows, list) or [row.get("mutation_id") for row in rows] != [
        f"P3-S3-M{index:03d}" for index in range(1, 25)
    ]:
        raise ValueError("required code mutation inventory differs")
    if {row.get("family") for row in rows} != FAMILIES:
        raise ValueError("required semantic mutation families differ")
    if registry.get("equivalent_mutations") != []:
        raise ValueError("equivalent mutation adjudication differs")
    output.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, Any]] = []
    for row in rows:
        directory = output / str(row["mutation_id"])
        repository = directory / "repository"
        _copy_repository(root, repository)
        path = repository / str(row["module_path"])
        original = path.read_text(encoding="utf-8")
        before = str(row["before"])
        after = str(row["after"])
        if original.count(before) != 1:
            raise ValueError(f"mutation target is not unique: {row['mutation_id']}")
        path.write_text(original.replace(before, after), encoding="utf-8")
        junit = directory / "pytest.xml"
        environment = dict(
            os.environ,
            PYTHONPATH=f"{repository / 'src'}{os.pathsep}{repository}",
            PYTHONDONTWRITEBYTECODE="1",
        )
        script = (
            "import importlib,pathlib,sys,pytest; "
            "m=importlib.import_module(sys.argv[1]); "
            "assert pathlib.Path(m.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[2])); "
            "raise SystemExit(pytest.main(sys.argv[3:]))"
        )
        command = [
            sys.executable,
            "-c",
            script,
            str(row["module"]),
            str(repository),
            "-q",
            "--tb=short",
            "--junitxml",
            str(junit),
            *[str(repository / str(node)) for node in row["tests"]],
        ]
        completed = subprocess.run(
            command,
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            timeout=240,
        )
        (directory / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (directory / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        if not junit.is_file():
            raise ValueError(f"mutation produced no test evidence: {row['mutation_id']}")
        suites = ET.parse(junit).getroot().findall("testsuite")
        counts = {
            key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        killed = (
            completed.returncode == 1
            and counts["failures"] > 0
            and counts["errors"] == counts["skipped"] == 0
        )
        result = {
            "mutation_id": row["mutation_id"],
            "family": row["family"],
            "killed": killed,
            "returncode": completed.returncode,
            "counts": counts,
            "original_sha256": sha256(original.encode()).hexdigest(),
            "mutant_sha256": sha256(path.read_bytes()).hexdigest(),
        }
        # Retain the immutable test/log evidence, not 24 redundant repository copies.
        shutil.rmtree(repository)
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
        if not killed:
            raise ValueError(f"semantic mutation survived or failed: {row['mutation_id']}")
    (output / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run_mutations(arguments.root.resolve(), arguments.output.resolve())


if __name__ == "__main__":
    main()
