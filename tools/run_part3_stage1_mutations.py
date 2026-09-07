#!/usr/bin/env python3
"""Execute registered source-code mutations in isolated import roots."""

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


def run_mutations(root: Path, output: Path) -> list[dict[str, Any]]:
    registry = json.loads((root / "spec/part3-stage1-code-mutations-v1.json").read_text())
    results: list[dict[str, Any]] = []
    for row in registry["mutations"]:
        directory = output / row["mutation_id"]
        source = directory / "src"
        shutil.copytree(
            root / "src", source, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
        )
        path = source / row["module_path"]
        original = path.read_text()
        if original.count(row["before"]) != 1:
            raise ValueError(f"mutation target is not unique: {row['mutation_id']}")
        path.write_text(original.replace(row["before"], row["after"]))
        junit = directory / "pytest.xml"
        environment = dict(os.environ, PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1")
        # Pin import provenance before pytest starts, including accidental stale wheel resolution.
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
            row["module"],
            str(source),
            "-q",
            "--tb=short",
            "--junitxml",
            str(junit),
            *[str(root / node) for node in row["tests"]],
        ]
        run = subprocess.run(
            command, cwd=directory, env=environment, capture_output=True, text=True, timeout=180
        )
        (directory / "stdout.log").write_text(run.stdout)
        (directory / "stderr.log").write_text(run.stderr)
        if not junit.exists():
            raise ValueError(f"mutation produced no test evidence: {row['mutation_id']}")
        suites = ET.parse(junit).getroot().findall("testsuite")
        counts = {
            k: sum(int(s.attrib.get(k, "0")) for s in suites)
            for k in ("tests", "failures", "errors", "skipped")
        }
        killed = (
            run.returncode == 1
            and counts["failures"] > 0
            and counts["errors"] == counts["skipped"] == 0
        )
        result = {
            "mutation_id": row["mutation_id"],
            "killed": killed,
            "returncode": run.returncode,
            "counts": counts,
            "original_sha256": sha256(original.encode()).hexdigest(),
            "mutant_sha256": sha256(path.read_bytes()).hexdigest(),
        }
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
        if not killed:
            raise ValueError(
                f"semantic mutation survived or failed to execute: {row['mutation_id']}"
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_mutations(args.root.resolve(), args.output.resolve())
    (args.output / "results.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
