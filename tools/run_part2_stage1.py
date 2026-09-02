#!/usr/bin/env python3
"""Run Part 2 Stage 1 in independent, exact, clean environments."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

IGNORED = shutil.ignore_patterns(
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "*.egg-info",
    "build",
    "dist",
    ".coverage",
)


def execute(command: list[str], cwd: Path, environment: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def run_clean(
    repository: Path, workspace: Path, index: int, wheelhouses: list[Path]
) -> dict[str, Any]:
    run_root = workspace / f"run-{index}"
    source = run_root / "source"
    environment_path = run_root / "venv"
    result_path = run_root / "result.json"
    wheelhouse = run_root / "wheelhouse"
    run_root.mkdir(parents=True)
    shutil.copytree(repository, source, ignore=IGNORED)
    execute([sys.executable, "-m", "venv", str(environment_path)], run_root)
    python = environment_path / "bin" / "python"
    if os.name == "nt":
        python = environment_path / "Scripts" / "python.exe"
    offline = (
        ["--no-index", *[value for path in wheelhouses for value in ("--find-links", str(path))]]
        if wheelhouses
        else []
    )
    for lock in ("part2-stage1-bootstrap.lock", "part2-stage1-py311.lock"):
        execute(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *offline,
                "--require-hashes",
                "-r",
                str(source / "requirements" / lock),
            ],
            run_root,
        )
    wheelhouse.mkdir()
    execute(
        [
            str(python),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
            str(source),
        ],
        run_root,
    )
    wheels = sorted(wheelhouse.glob("ledgerguard-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Stage 1 expected exactly one LedgerGuard wheel")
    execute([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])], run_root)
    spark_environment = dict(os.environ)
    spark_environment["PYSPARK_PYTHON"] = str(python)
    spark_environment["PYSPARK_DRIVER_PYTHON"] = str(python)
    spark_environment.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    execute(
        [
            str(python),
            str(source / "tools/validate_part2_stage1_run.py"),
            "--root",
            str(source),
            "--output",
            str(result_path),
        ],
        run_root,
        spark_environment,
    )
    return json.loads(result_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-runs", type=int, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--wheelhouse", type=Path, action="append", default=[])
    arguments = parser.parse_args()
    if arguments.clean_runs < 2:
        raise SystemExit("P2-S1-R018 requires at least two clean runs")
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("Part 2 Stage 1 requires exact CPython 3.11.13")
    repository = Path(__file__).resolve().parents[1]
    owned_temporary: tempfile.TemporaryDirectory[str] | None = None
    if arguments.output is None:
        owned_temporary = tempfile.TemporaryDirectory(prefix="ledgerguard-part2-stage1-")
        workspace = Path(owned_temporary.name)
    else:
        workspace = arguments.output.resolve()
        if repository == workspace or repository in workspace.parents:
            raise SystemExit("Part 2 Stage 1 output must be outside the repository")
        workspace.mkdir(parents=True, exist_ok=True)
    wheelhouses = [path.resolve() for path in arguments.wheelhouse]
    if any(not path.is_dir() for path in wheelhouses):
        raise SystemExit("Stage 1 wheelhouse does not exist")
    results = [
        run_clean(repository, workspace, index + 1, wheelhouses)
        for index in range(arguments.clean_runs)
    ]
    deterministic = [
        {
            "actions": row["actions"],
            "test_counts": row["test_counts"],
            "dependency_versions": row["dependency_versions"],
            "authority": row["authority"],
            "toolchain": row["toolchain"],
            "spark_probe": row["spark_probe"],
        }
        for row in results
    ]
    first = canonical(deterministic[0])
    if any(canonical(row) != first for row in deterministic[1:]):
        raise SystemExit("P2-S1-R018 clean-run deterministic payloads differ")
    evidence = {
        "schema_version": "1.0",
        "project": "ledgerguard-payment-reconciliation-platform",
        "part": 2,
        "stage": 1,
        "clean_run_count": len(results),
        "deterministic_equal": True,
        "deterministic_payload_sha256": sha256(first).hexdigest(),
        "deterministic_payload": deterministic[0],
        "execution_boundary": {
            "aws_api_called": False,
            "aws_workflow_dispatched": False,
            "infrastructure_mutated": False,
            "reconciliation_oracle_added": False,
            "reconciliation_engine_added": False,
            "spark_reconciliation_claimed": False,
            "merge_authorized": False,
        },
    }
    destination = workspace / "part2-stage1-local-evidence.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if owned_temporary is not None:
        owned_temporary.cleanup()


if __name__ == "__main__":
    main()
