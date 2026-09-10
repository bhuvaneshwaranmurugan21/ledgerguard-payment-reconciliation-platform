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


def run(root: Path, output: Path) -> list[dict[str, Any]]:
    rows = json.loads((root / "spec/part3-stage4-mutations-v1.json").read_text())["mutations"]
    if len(rows) != 15 or len({r["id"] for r in rows}) != 15:
        raise ValueError("required mutation inventory differs")
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
        if original.count(row["before"]) != 1:
            raise ValueError("mutation target is not unique: " + row["id"])
        mutant = original.replace(row["before"], row["after"])
        ast.parse(mutant)
        path.write_text(mutant)
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
        path.write_text(original)
        suites = ET.parse(trial / "tests.xml").getroot().findall("testsuite")
        counts = {
            key: sum(int(s.attrib.get(key, "0")) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        killed = (
            completed.returncode == 1
            and counts["failures"] > 0
            and counts["errors"] == counts["skipped"] == 0
        )
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
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve())
