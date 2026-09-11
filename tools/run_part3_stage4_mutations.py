"""Run the frozen Stage 4 semantic faults against the real tests in isolation."""

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

REQUIRED_MUTATIONS = (
    "S4-M01-ceiling-equality",
    "S4-M02-stale-cost",
    "S4-M03-credit-netting",
    "S4-M04-reserve-overlap",
    "S4-M05-cleanup-reserve",
    "S4-M06-resource-properties",
    "S4-M07-address-count",
    "S4-M08-resource-extras",
    "S4-M09-runtime-identity",
    "S4-M10-artifact-admission",
    "S4-M11-excess-iam",
    "S4-M12-runtime-start-deny",
    "S4-M13-boundary-resource",
    "S4-M14-state-deletion",
    "S4-M15-policy-size",
    "S4-M16-credential-authority",
    "S4-M17-native-result-types",
    "S4-M18-coverage-inventory",
    "S4-M19-excluded-code",
    "S4-M20-process-timeout",
    "S4-M21-registry-identity",
    "S4-M22-process-status",
    "S4-M23-reader-self-observation",
    "S4-M24-successor-role-parity",
    "S4-M25-successor-policy-parity",
    "S4-M26-default-policy-version",
)


def load_registry(root: Path) -> list[dict[str, Any]]:
    rows = json.loads((root / "spec/part3-stage4-mutations-v1.json").read_text())["mutations"]
    if tuple(row["id"] for row in rows) != REQUIRED_MUTATIONS:
        raise ValueError("required mutation inventory differs")
    return list(rows)


def prepare_mutation(original: str, row: dict[str, Any]) -> str:
    if original.count(row["before"]) != 1:
        raise ValueError("mutation target is not unique: " + row["id"])
    mutant = original.replace(row["before"], row["after"])
    if mutant == original:
        raise ValueError("mutation does not alter source: " + row["id"])
    ast.parse(mutant)
    return mutant


def evaluate_test_result(code: int, path: Path) -> tuple[dict[str, int], bool]:
    document = ET.parse(path).getroot()
    suites = list(document.iter("testsuite"))
    counts = {
        key: sum(int(s.attrib.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    cases = list(document.iter("testcase"))
    actual = {
        "tests": len(cases),
        "failures": sum(c.find("failure") is not None for c in cases),
        "errors": sum(c.find("error") is not None for c in cases),
        "skipped": sum(c.find("skipped") is not None for c in cases),
    }
    if counts != actual:
        raise ValueError("mutation JUnit counts differ from actual cases")
    killed = code == 1 and counts["failures"] > 0 and counts["errors"] == counts["skipped"] == 0
    return counts, killed


def require_killed(result: dict[str, Any]) -> None:
    if result["killed"] is not True:
        raise ValueError("mutation survived or failed for wrong reason: " + result["id"])


def run(root: Path, output: Path) -> list[dict[str, Any]]:
    rows = load_registry(root)
    output.mkdir(parents=True, exist_ok=False)
    repository = output / "repository"
    repository.mkdir()
    for name in ("tools", "src", "tests", "spec", "contracts", "infra", "evidence"):
        shutil.copytree(
            root / name,
            repository / name,
            ignore=shutil.ignore_patterns(".terraform", "__pycache__", ".pytest_cache"),
        )
    shutil.copy(root / "pyproject.toml", repository / "pyproject.toml")
    results = []
    for row in rows:
        path = repository / row["path"]
        original = path.read_text()
        mutant = prepare_mutation(original, row)
        trial = output / row["id"]
        trial.mkdir()
        script = (
            "import importlib,pathlib,sys,pytest; "
            "m=importlib.import_module(sys.argv[1]); "
            "assert pathlib.Path(m.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[2])); "
            "raise SystemExit(pytest.main(sys.argv[3:]))"
        )
        module = row["path"][:-3].replace("/", ".")
        env = dict(
            os.environ,
            PYTHONPATH=str(repository / "src") + os.pathsep + str(repository),
            PYTHONDONTWRITEBYTECODE="1",
        )
        path.write_text(mutant)
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    script,
                    module,
                    str(repository),
                    row["test"],
                    "-q",
                    "-o",
                    "addopts=",
                    "--tb=short",
                    "--junitxml=" + str(trial / "tests.xml"),
                ],
                cwd=repository,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            (trial / "stdout.log").write_text(completed.stdout)
            (trial / "stderr.log").write_text(completed.stderr)
        finally:
            path.write_text(original)
        counts, killed = evaluate_test_result(completed.returncode, trial / "tests.xml")
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
        require_killed(result)
    shutil.rmtree(repository)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve())
