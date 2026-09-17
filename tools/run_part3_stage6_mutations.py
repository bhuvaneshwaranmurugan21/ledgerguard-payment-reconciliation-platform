#!/usr/bin/env python3
"""Run every frozen Stage 6 source mutation against real tests in isolation."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from typing import Any

REQUIRED_MUTATIONS = tuple(f"S6-M{index:02d}-" for index in range(1, 39))


def load_registry(root: Path) -> list[dict[str, Any]]:
    value = json.loads((root / "spec/part3-stage6-mutations-v1.json").read_text())
    rows = value.get("mutations")
    if not isinstance(rows, list) or len(rows) != len(REQUIRED_MUTATIONS):
        raise ValueError("required Stage 6 mutation inventory differs")
    if any(
        not row.get("id", "").startswith(prefix)
        for row, prefix in zip(rows, REQUIRED_MUTATIONS, strict=True)
    ):
        raise ValueError("required Stage 6 mutation identity differs")
    return rows


def prepare_mutation(original: str, row: dict[str, Any]) -> str:
    before, after = row.get("before"), row.get("after")
    if not isinstance(before, str) or not isinstance(after, str) or original.count(before) != 1:
        raise ValueError("mutation target is not unique: " + str(row.get("id")))
    mutant = original.replace(before, after)
    if mutant == original:
        raise ValueError("mutation does not alter source: " + str(row.get("id")))
    ast.parse(mutant)
    return mutant


def evaluate(code: int, junit: Path) -> tuple[dict[str, int], bool]:
    root = ET.parse(junit).getroot()
    cases = list(root.iter("testcase"))
    counts = {
        "tests": len(cases),
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }
    killed = code == 1 and counts["failures"] > 0 and counts["errors"] == counts["skipped"] == 0
    return counts, killed


def run(root: Path, output: Path) -> list[dict[str, Any]]:
    rows = load_registry(root)
    frozen_sources = {str(row["path"]): (root / str(row["path"])).read_text() for row in rows}
    output.mkdir(parents=True, exist_ok=False)
    repository = output / "repository"
    repository.mkdir()
    for name in (".github", "tools", "src", "tests", "spec", "contracts", "infra"):
        shutil.copytree(
            root / name,
            repository / name,
            ignore=shutil.ignore_patterns(".terraform", "__pycache__", ".pytest_cache"),
        )
    shutil.copy(root / "pyproject.toml", repository / "pyproject.toml")
    results: list[dict[str, Any]] = []
    for row in rows:
        path = repository / row["path"]
        original = frozen_sources[str(row["path"])]
        path.write_text(original)
        mutant = prepare_mutation(original, row)
        trial = output / row["id"]
        trial.mkdir()
        path.write_text(mutant)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    row["test"],
                    "-q",
                    "-o",
                    "addopts=",
                    "--tb=short",
                    "--junitxml=" + str(trial / "tests.xml"),
                ],
                cwd=repository,
                env=dict(
                    os.environ,
                    PYTHONPATH=(
                        str(repository / "src")
                        + os.pathsep
                        + str(repository)
                        + os.pathsep
                        + os.environ.get("PYTHONPATH", "")
                    ),
                    PYTHONDONTWRITEBYTECODE="1",
                ),
                capture_output=True,
                text=True,
                timeout=180,
            )
            (trial / "stdout.log").write_text(completed.stdout)
            (trial / "stderr.log").write_text(completed.stderr)
        finally:
            path.write_text(original)
        counts, killed = evaluate(completed.returncode, trial / "tests.xml")
        result = {
            "id": row["id"],
            "killed": killed,
            "exit_code": completed.returncode,
            "counts": counts,
            "source_sha256": sha256(original.encode()).hexdigest(),
            "mutant_sha256": sha256(mutant.encode()).hexdigest(),
        }
        results.append(result)
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        if not killed:
            raise ValueError("mutation survived or failed for wrong reason: " + row["id"])
    shutil.rmtree(repository)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.root.resolve(), arguments.output.resolve())
