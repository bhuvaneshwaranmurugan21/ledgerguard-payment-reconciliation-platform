#!/usr/bin/env python3
"""Validate one clean installed-wheel Stage 2 repository run."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import sysconfig
import time
from hashlib import sha256
from importlib.metadata import distributions, version
from pathlib import Path

from ledgerguard.stage2.validation import validate_repository
from ledgerguard_part2_stage1_evidence import parse_junit_counts


def execute(command: list[str], root: Path, env: dict[str, str]) -> None:
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=root, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
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
    imports = {}
    for name in (
        "ledgerguard.stage2.control",
        "ledgerguard.stage2.aws_cli",
        "ledgerguard.stage2.evidence",
        "ledgerguard.stage2.validation",
    ):
        module = importlib.import_module(name)
        path = Path(str(module.__file__)).resolve()
        if not path.is_relative_to(Path(sys.prefix)) or path.is_relative_to(root):
            raise ValueError("installed-wheel import required: " + name)
        imports[name] = sha256(path.read_bytes()).hexdigest()
    installed = Path(sysconfig.get_paths()["purelib"])
    for source in (root / "src").rglob("*.py"):
        target = installed / source.relative_to(root / "src")
        if target.read_bytes() != source.read_bytes():
            raise ValueError("installed source differs: " + str(source.relative_to(root)))
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYSPARK_PYTHON"] = sys.executable
    env["PYSPARK_DRIVER_PYTHON"] = sys.executable
    execute([sys.executable, "-m", "ruff", "format", "--check", "."], root, env)
    execute([sys.executable, "-m", "ruff", "check", "."], root, env)
    execute(
        [
            sys.executable,
            "-m",
            "mypy",
            "src",
            "tools/part3_stage2_live.py",
            "tools/part3_stage2_runtime.py",
            "tools/part3_stage2_extract_artifact.py",
            "tools/part3_stage2_inspect_artifact.py",
            "tools/run_part3_stage2.py",
            "tools/validate_part3_stage2_run.py",
            "tools/run_part3_stage2_mutations.py",
            "tools/build_part3_stage2_ci_evidence.py",
        ],
        root,
        env,
    )
    repository = validate_repository(root)
    stage2_tests = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "tests").glob("test_part3_stage2_*.py")
    )
    if not stage2_tests:
        raise ValueError("Stage 2 tests are absent")
    collection = output.parent / "collection.json"
    collector_script = output.parent / "collect_tests.py"
    collector_script.write_text(
        "import json, pathlib, pytest, sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "class Plugin:\n"
        "    def pytest_collection_finish(self, session):\n"
        f"        pathlib.Path({str(collection)!r}).write_text("
        "json.dumps([item.nodeid for item in session.items]))\n"
        f"raise SystemExit(pytest.main(['--collect-only', '-q', *{stage2_tests!r}], "
        "plugins=[Plugin()]))\n"
    )
    execute([sys.executable, str(collector_script)], root, env)
    nodes = json.loads(collection.read_text())
    if len(nodes) != len(set(nodes)):
        raise ValueError("duplicate test collection")
    scenarios = json.loads((root / "spec/part3-stage2-scenario-registry-v1.json").read_text())
    if scenarios["count"] != len(scenarios["scenarios"]) or scenarios["count"] < 100:
        raise ValueError("Stage 2 scenario inventory incomplete")
    registered_nodes = [row["nodeid"] for row in scenarios["scenarios"]]
    if registered_nodes != nodes or len(registered_nodes) != len(set(registered_nodes)):
        raise ValueError("Stage 2 scenario registry does not exactly match collected tests")
    required_files = {row["test_file"] for row in scenarios["scenarios"]}
    for required in required_files:
        if not any(node.startswith(required + "::") for node in nodes):
            raise ValueError("Stage 2 scenario suite absent: " + required)
    junit = output.parent / "pytest.xml"
    execute(
        [sys.executable, "-m", "pytest", "--junitxml", str(junit), *stage2_tests],
        root,
        env,
    )
    counts = parse_junit_counts(junit)
    if counts != {"tests": len(nodes), "failures": 0, "errors": 0, "skipped": 0}:
        raise ValueError("full test execution incomplete")
    cov = output.parent / "coverage"
    cov.mkdir()
    coverage_env = dict(env)
    coverage_env["COVERAGE_FILE"] = str(cov / "data")
    coverage_env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root)))
    execute(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=src/ledgerguard/stage2",
            "-m",
            "pytest",
            *stage2_tests,
        ],
        root,
        coverage_env,
    )
    coverage = output.parent / "coverage.json"
    execute(
        [sys.executable, "-m", "coverage", "json", "-o", str(coverage)],
        root,
        coverage_env,
    )
    report = json.loads(coverage.read_text())
    inventory = {
        p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "src/ledgerguard/stage2").rglob("*.py"))
    }
    if set(report["files"]) != set(inventory):
        raise ValueError("coverage does not account for all Stage 2 source")
    if report["totals"]["percent_covered"] < 90:
        raise ValueError("Stage 2 source coverage below 90%")
    owned = {
        "src/ledgerguard/stage2/__init__.py",
        "src/ledgerguard/stage2/aws_cli.py",
        "src/ledgerguard/stage2/control.py",
        "src/ledgerguard/stage2/evidence.py",
        "src/ledgerguard/stage2/validation.py",
    }
    for name in owned:
        row = report["files"][name]
        if row["missing_lines"] or row["missing_branches"] or row["excluded_lines"]:
            raise ValueError("Stage 2 owned source is not fully covered: " + name)
    mutation_dir = output.parent / "mutations"
    execute(
        [
            sys.executable,
            str(root / "tools/run_part3_stage2_mutations.py"),
            "--root",
            str(root),
            "--output",
            str(mutation_dir),
        ],
        root,
        env,
    )
    mutations = json.loads((mutation_dir / "results.json").read_text())
    if len(mutations) != 29 or not all(row["killed"] for row in mutations):
        raise ValueError("Stage 2 mutation campaign incomplete")
    deterministic = {
        "repository": repository,
        "counts": counts,
        "test_nodes": nodes,
        "coverage": {p: v["summary"] for p, v in report["files"].items()},
        "inherited_validation": {
            "protected_paths_unchanged": repository["authority"]["protected_paths"],
            "stage1_source_coverage_percent": 94.24422855949024,
            "stage1_closure_commit": "5abef1a07899bd8ecd202008f1c397890184a0d2",
        },
        "source_inventory": inventory,
        "imports": imports,
        "mutations": mutations,
        "contracts": {
            p: sha256((root / p).read_bytes()).hexdigest()
            for p in (
                "contracts/part3-stage2-execution-v1.json",
                "contracts/part3-stage2-oidc-trust-v1.json",
                "contracts/part3-stage2-iam-permissions-v1.json",
                "contracts/part3-stage2-control-plane-v1.json",
                "contracts/part3-stage2-cost-v1.json",
                "contracts/part3-stage2-inventory-v1.json",
                "contracts/part3-stage2-glue-probe-v1.json",
            )
        },
        "toolchain": {"python": "3.11.13", "java_major": 17, "spark": "3.5.6", "py4j": "0.10.9.7"},
        "dependencies": dict(
            sorted((str(d.metadata["Name"]).lower(), d.version) for d in distributions())
        ),
    }
    result = {
        "schema_version": "1.0",
        "part": 3,
        "stage": 2,
        "state": "LOCAL_VALIDATION_FINISHED",
        "deterministic": deterministic,
        "deterministic_sha256": sha256(
            json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "observations": {"elapsed_seconds": time.monotonic() - started, "java": java},
        "execution_boundary": {
            "aws_execution": False,
            "aws_infrastructure_mutated": False,
            "managed_reconciliation_started": False,
            "project_complete": False,
        },
    }
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
