#!/usr/bin/env python3
"""Execute registered Stage 2 semantic mutations in isolated source roots."""

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
    registry = json.loads((root / "spec/part3-stage2-code-mutations-v1.json").read_text())
    rows = registry["mutations"]
    if [row["mutation_id"] for row in rows] != [f"P3-S2-M{i:03d}" for i in range(1, 31)]:
        raise ValueError("Stage 2 mutation inventory differs")
    required_families = {
        "dispatch_boundary",
        "identity_boundary",
        "iam_semantics",
        "backend_security",
        "backend_lifecycle",
        "lease_semantics",
        "cost_headroom",
        "cleanup_integrity",
        "glue_no_run",
        "inventory_visibility",
        "evidence_integrity",
        "governance_closure",
        "resource_tags",
    }
    if {row["family"] for row in rows} != required_families:
        raise ValueError("Stage 2 mutation families differ")
    results = []
    for row in rows:
        directory = output / row["mutation_id"]
        source = directory / "src"
        shutil.copytree(
            root / "src", source, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
        )
        path = source / row["module_path"]
        original = path.read_text()
        if original.count(row["before"]) != 1:
            raise ValueError("mutation target is not unique: " + row["mutation_id"])
        path.write_text(original.replace(row["before"], row["after"]))
        junit = directory / "pytest.xml"
        env = dict(os.environ, PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1")
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--junitxml",
            str(junit),
            *[str(root / node) for node in row["tests"]],
        ]
        run = subprocess.run(
            command, cwd=directory, env=env, capture_output=True, text=True, timeout=180
        )
        (directory / "stdout.log").write_text(run.stdout)
        (directory / "stderr.log").write_text(run.stderr)
        if not junit.exists():
            raise ValueError("mutation produced no JUnit evidence: " + row["mutation_id"])
        suites = ET.parse(junit).getroot().findall("testsuite")
        counts = {
            key: sum(int(s.attrib.get(key, "0")) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        killed = (
            run.returncode == 1
            and counts["failures"] > 0
            and counts["errors"] == counts["skipped"] == 0
        )
        result = {
            "mutation_id": row["mutation_id"],
            "family": row["family"],
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
                "semantic mutation survived or failed to execute: " + row["mutation_id"]
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
