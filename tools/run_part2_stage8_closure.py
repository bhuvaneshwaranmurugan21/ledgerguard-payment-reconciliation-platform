#!/usr/bin/env python3
"""Run the Part 2 closure attestation twice in exact independent environments."""

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
    ".rsync-tmp",
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
SOURCE_DATE_EPOCH = "1788405487"


def execute(command: list[str], cwd: Path, environment: dict[str, str]) -> None:
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
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = str(index * 173)
    environment["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    execute([sys.executable, "-m", "venv", str(environment_path)], run_root, environment)
    python = environment_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    offline = (
        ["--no-index", *[value for path in wheelhouses for value in ("--find-links", str(path))]]
        if wheelhouses
        else []
    )
    for lock in ("part2-stage8-bootstrap.lock", "part2-stage8-py311.lock"):
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
            environment,
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
        environment,
    )
    wheels = sorted(wheelhouse.glob("ledgerguard-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("closure validation expected exactly one LedgerGuard wheel")
    wheel_sha = sha256(wheels[0].read_bytes()).hexdigest()
    execute(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        run_root,
        environment,
    )
    execute(
        [
            str(python),
            str(source / "tools/validate_part2_stage8_closure_run.py"),
            "--root",
            str(source),
            "--output",
            str(result_path),
        ],
        run_root,
        environment,
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["wheel_sha256"] = wheel_sha
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-runs", type=int, default=2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--wheelhouse", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.clean_runs < 2:
        raise SystemExit("closure reproducibility requires at least two clean runs")
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("closure validation requires exact CPython 3.11.13")
    repository = Path(__file__).resolve().parents[1]
    owned: tempfile.TemporaryDirectory[str] | None = None
    if args.output is None:
        owned = tempfile.TemporaryDirectory(prefix="ledgerguard-part2-stage8-closure-")
        workspace = Path(owned.name)
    else:
        workspace = args.output.resolve()
        if repository == workspace or repository in workspace.parents:
            raise SystemExit("closure output must be outside the repository")
        workspace.mkdir(parents=True, exist_ok=True)
    wheelhouses = [path.resolve() for path in args.wheelhouse]
    if any(not path.is_dir() for path in wheelhouses):
        raise SystemExit("closure wheelhouse does not exist")
    results = [
        run_clean(repository, workspace, index + 1, wheelhouses) for index in range(args.clean_runs)
    ]
    deterministic = [
        {
            key: row[key]
            for key in (
                "actions",
                "test_counts",
                "coverage",
                "mutations",
                "dependency_versions",
                "authority",
                "toolchain",
                "wheel_sha256",
            )
        }
        for row in results
    ]
    first = canonical(deterministic[0])
    if any(canonical(row) != first for row in deterministic[1:]):
        raise SystemExit("closure clean-run deterministic payloads differ")
    evidence = {
        "schema_version": "1.0",
        "project": "ledgerguard-payment-reconciliation-platform",
        "part": 2,
        "stage": 8,
        "transaction": "CLOSURE_ATTESTATION",
        "clean_run_count": len(results),
        "deterministic_equal": True,
        "deterministic_payload_sha256": sha256(first).hexdigest(),
        "deterministic_payload": deterministic[0],
        "execution_boundary": results[0]["execution_boundary"] | {"merge_authorized": False},
    }
    destination = workspace / "part2-stage8-closure-local-evidence.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if owned is not None:
        owned.cleanup()


if __name__ == "__main__":
    main()
