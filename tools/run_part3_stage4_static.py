#!/usr/bin/env python3
"""Run real provider validation and lint without AWS credentials or a backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    destination = Path(os.environ["STAGE4_EVIDENCE"]).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != os.environ["EXPECTED_SHA"]:
        raise ValueError("checkout does not match exact expected head")
    if any(
        os.environ.get(key)
        for key in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_WEB_IDENTITY_TOKEN_FILE",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        )
    ):
        raise ValueError("static validation must not receive AWS credentials")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    env["MYPYPATH"] = str(ROOT / "src")
    commands = {
        "terraform-version": ["terraform", "version", "-json"],
        "terraform-format": ["terraform", "-chdir=infra/part3", "fmt", "-check", "-recursive"],
        "terraform-initialize": [
            "terraform",
            "-chdir=infra/part3",
            "init",
            "-backend=false",
            "-input=false",
            "-lockfile=readonly",
            "-no-color",
        ],
        "terraform-validate": ["terraform", "-chdir=infra/part3", "validate", "-json"],
        "terraform-schema": ["terraform", "-chdir=infra/part3", "providers", "schema", "-json"],
        "tflint-version": ["tflint", "--version"],
        "tflint": ["tflint", "--chdir=infra/part3", "--format=json"],
        "handoff": [sys.executable, "-m", "tools.validate_part3_stage4_handoff"],
        "tests": [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_part3_stage4_handoff.py",
            "tests/test_part3_stage3_tooling.py",
            "-k",
            "handoff or ci_artifact",
            "-q",
            "-o",
            "addopts=",
            "--junitxml=" + str(destination / "tests.xml"),
        ],
        "python-lint": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "tools/validate_part3_stage4_handoff.py",
            "tools/rehearse_part3_stage4_inspector.py",
            "tools/run_part3_stage4_static.py",
            "tests/test_part3_stage4_handoff.py",
        ],
        "python-types": [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "tools/validate_part3_stage4_handoff.py",
            "tools/rehearse_part3_stage4_inspector.py",
            "tools/run_part3_stage4_static.py",
        ],
    }
    results = []
    for name, command in commands.items():
        with (
            (destination / (name + ".stdout")).open("w") as out,
            (destination / (name + ".stderr")).open("w") as err,
        ):
            try:
                process = subprocess.run(
                    command, cwd=ROOT, env=env, stdout=out, stderr=err, timeout=600, check=False
                )
                code = process.returncode
            except subprocess.TimeoutExpired:
                code = 124
            except OSError as error:
                err.write(str(error))
                code = 127
        results.append({"check": name, "command": command, "exit_code": code})
        print(name + ": " + ("PASS" if code == 0 else "FAIL"), flush=True)
    passed = all(result["exit_code"] == 0 for result in results)
    summary = {
        "source_commit": head,
        "checks": results,
        "static_subset_passed": passed,
        "stage4_complete": False,
        "rehearsal_ready": False,
        "aws_execution": False,
    }
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
