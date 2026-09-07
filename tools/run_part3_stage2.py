#!/usr/bin/env python3
"""Build, install, and validate Part 3 Stage 2 in independent clean environments."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-runs", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if args.clean_runs != 2:
        raise ValueError("exactly two clean runs required")
    if output.exists():
        raise ValueError("output must not already exist")
    output.mkdir(parents=True)
    epoch = subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=root, text=True
    ).strip()
    results = []
    for number in (1, 2):
        directory = output / f"run-{number}"
        directory.mkdir()
        venv = directory / "venv"
        run([sys.executable, "-m", "venv", str(venv)], root, dict(os.environ))
        python = venv / "bin/python"
        env = dict(os.environ, SOURCE_DATE_EPOCH=epoch, PYTHONHASHSEED="0")
        env.pop("PYTHONPATH", None)
        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(root / "requirements/part2-stage8-bootstrap.lock"),
            ],
            root,
            env,
        )
        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(root / "requirements/part2-stage8-py311.lock"),
            ],
            root,
            env,
        )
        wheel_dir = directory / "wheel"
        wheel_dir.mkdir()
        build_source = directory / "source"
        shutil.copytree(
            root,
            build_source,
            ignore=shutil.ignore_patterns(
                ".git",
                ".mypy_cache",
                ".pytest_cache",
                "__pycache__",
                "*.egg-info",
                "build",
            ),
        )
        run(
            [
                str(python),
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheel_dir),
                str(build_source),
            ],
            root,
            env,
        )
        wheels = list(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("exactly one wheel required")
        run([str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])], root, env)
        result_path = directory / "result.json"
        run(
            [
                str(python),
                str(root / "tools/validate_part3_stage2_run.py"),
                "--root",
                str(root),
                "--output",
                str(result_path),
            ],
            root,
            env,
        )
        result = json.loads(result_path.read_text())
        result["wheel_sha256"] = sha256(wheels[0].read_bytes()).hexdigest()
        result_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
        results.append(result)

    def stable(result: dict[str, object]) -> dict[str, object]:
        return {
            "deterministic": result["deterministic"],
            "deterministic_sha256": result["deterministic_sha256"],
            "wheel_sha256": result["wheel_sha256"],
            "execution_boundary": result["execution_boundary"],
        }

    if stable(results[0]) != stable(results[1]):
        raise ValueError("two clean Stage 2 runs differ")
    aggregate = {
        "schema_version": "1.0",
        "part": 3,
        "stage": 2,
        "clean_run_count": 2,
        "deterministic_equal": True,
        "deterministic_payload": stable(results[0]),
        "deterministic_payload_sha256": sha256(
            json.dumps(stable(results[0]), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "execution_boundary": {
            "aws_execution": False,
            "aws_infrastructure_mutated": False,
            "managed_reconciliation_started": False,
            "project_complete": False,
        },
    }
    (output / "part3-stage2-local-evidence.json").write_text(
        json.dumps(aggregate, sort_keys=True, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
