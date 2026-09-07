#!/usr/bin/env python3
"""Validate current installed code, complete test ownership, and reproducible outcomes."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any

from run_part3_stage1_mutations import run_mutations

from ledgerguard_part2_stage1_evidence import parse_junit_counts
from ledgerguard_part3_stage1_validation import validate_entry, validate_surfaces


def execute(command: list[str], root: Path, env: dict[str, str]) -> None:
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=root, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if root == output.parent or root in output.parents:
        raise ValueError("evidence must be outside source")
    if sys.version_info[:3] != (3, 11, 13):
        raise ValueError("requires exact CPython 3.11.13")
    if version("pyspark") != "3.5.6" or version("py4j") != "0.10.9.7":
        raise ValueError("Spark versions differ")
    java = subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT, text=True)
    if '"17.' not in java.splitlines()[0]:
        raise ValueError("requires Java 17")
    for name in ("PYSPARK_PYTHON", "PYSPARK_DRIVER_PYTHON"):
        if os.environ.get(name) != sys.executable:
            raise ValueError("Spark interpreter differs")
    modules = [
        "ledgerguard.reconciliation.finalization",
        "ledgerguard.reconciliation.correction",
        "ledgerguard_reference_oracle",
        "ledgerguard_part3_stage1_correct",
        "ledgerguard_part3_stage1_validation",
    ]
    imports = {}
    for name in modules:
        module = importlib.import_module(name)
        path = Path(str(module.__file__)).resolve()
        if not path.is_relative_to(Path(sys.prefix)) or path.is_relative_to(root):
            raise ValueError("current installed-wheel import required: " + name)
        imports[name] = sha256(path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    execute([sys.executable, "-m", "ruff", "format", "--check", "."], root, env)
    execute([sys.executable, "-m", "ruff", "check", "."], root, env)
    execute(
        [
            sys.executable,
            "-m",
            "mypy",
            "src",
            "tools/run_part3_stage1.py",
            "tools/validate_part3_stage1_run.py",
            "tools/run_part3_stage1_mutations.py",
        ],
        root,
        env,
    )
    entry = validate_entry(root)
    surfaces = validate_surfaces(root)
    collection = output.parent / "collection.json"
    collector = (
        "import json,pathlib,pytest; "
        'P=type("P",(),{"pytest_collection_finish":lambda self,session:'
        f"pathlib.Path({str(collection)!r}).write_text("
        "json.dumps([x.nodeid for x in session.items]))}); "
        'raise SystemExit(pytest.main(["--collect-only","-q","tests"],plugins=[P()]))'
    )
    execute([sys.executable, "-c", collector], root, env)
    nodes = json.loads(collection.read_text())
    manifest = json.loads((root / "spec/part3-stage1-test-execution-v1.json").read_text())
    historical = {row["node"] for row in manifest["historical_nodes"]}
    if not historical.issubset(nodes):
        raise ValueError("historical obligation missing from collection")
    selected = [node for node in nodes if node not in historical]
    if len(set(nodes)) != len(nodes):
        raise ValueError("duplicate test collection")
    for required in manifest["current_required_files"]:
        if not any(node.startswith(required + "::") for node in selected):
            raise ValueError("current behavioral suite missing")
    trace = json.loads((root / "spec/part3-stage1-scenario-traceability-v1.json").read_text())
    if [row["scenario_id"] for row in trace["scenarios"]] != [f"T{i:02d}" for i in range(1, 33)]:
        raise ValueError("required Stage 1 scenario inventory differs")
    for row in trace["scenarios"]:
        for target in row["tests"]:
            if not any(node == target or node.startswith(target + "::") for node in selected):
                raise ValueError(
                    "required scenario is not executed on current code: " + row["scenario_id"]
                )
    (output.parent / "execution-selection.json").write_text(
        json.dumps(
            {"all": nodes, "current": selected, "historical": sorted(historical)},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    junit = output.parent / "pytest.xml"
    execute([sys.executable, "-m", "pytest", "--junitxml", str(junit), *selected], root, env)
    counts = parse_junit_counts(junit)
    if counts != {"tests": len(selected), "failures": 0, "errors": 0, "skipped": 0}:
        raise ValueError("current tests incomplete")
    cov = output.parent / "coverage"
    cov.mkdir()
    env["COVERAGE_FILE"] = str(cov / "data")
    rc = str(root / "spec/part3-stage1-coverage.ini")
    execute(
        [sys.executable, "-m", "coverage", "run", "--rcfile", rc, "-m", "pytest", *selected],
        root,
        env,
    )
    execute([sys.executable, "-m", "coverage", "combine", "--rcfile", rc, str(cov)], root, env)
    coverage = output.parent / "coverage.json"
    execute(
        [sys.executable, "-m", "coverage", "json", "--rcfile", rc, "-o", str(coverage)], root, env
    )
    report = json.loads(coverage.read_text())
    if report["totals"]["percent_covered"] < 90:
        raise ValueError("overall production coverage below 90%")
    owned = {
        "src/ledgerguard/reconciliation/finalization.py",
        "src/ledgerguard/reconciliation/correction.py",
        "src/ledgerguard_part3_stage1_correct.py",
        "src/ledgerguard_part3_stage1_validation.py",
        "src/ledgerguard_part3_stage1_evidence.py",
    }
    for name in owned:
        row = report["files"][name]
        if row["missing_lines"] or row["missing_branches"] or row["excluded_lines"]:
            raise ValueError("owned surface is not fully covered: " + name)
    mutations = run_mutations(root, output.parent / "mutations")
    (output.parent / "mutations.json").write_text(
        json.dumps(mutations, sort_keys=True, indent=2) + "\n"
    )
    deterministic: dict[str, Any] = {
        "entry": entry,
        "surfaces": surfaces,
        "counts": counts,
        "imports": imports,
        "tests": selected,
        "coverage": {k: v["summary"] for k, v in report["files"].items()},
        "mutations": mutations,
    }
    result = {
        "schema_version": "1.0",
        "deterministic": deterministic,
        "toolchain": {"python": "3.11.13", "java_major": 17, "spark": "3.5.6", "py4j": "0.10.9.7"},
        "execution_boundary": {"aws_execution": False, "account_wide_inactivity_proven": False},
        "deterministic_sha256": sha256(
            json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
