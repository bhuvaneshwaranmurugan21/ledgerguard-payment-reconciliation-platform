#!/usr/bin/env python3
"""Run real provider validation and lint without AWS credentials or a backend."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare_schema_context(lock: Path, destination: Path) -> dict[str, str]:
    """Inspect the pinned provider without initializing the workload backend."""
    raw = lock.read_bytes()
    providers = re.findall(r'provider "([^\"]+)"', raw.decode())
    versions = re.findall(r'^\s*version\s*=\s*"([^\"]+)"', raw.decode(), re.MULTILINE)
    if providers != ["registry.terraform.io/hashicorp/aws"] or versions != ["6.11.0"]:
        raise ValueError("unexpected schema provider lock identity")
    destination.mkdir(parents=True, exist_ok=False)
    (destination / ".terraform.lock.hcl").write_bytes(raw)
    configuration = {
        "terraform": {
            "required_version": "= 1.13.1",
            "required_providers": {"aws": {"source": "hashicorp/aws", "version": "= 6.11.0"}},
        }
    }
    encoded = (json.dumps(configuration, indent=2) + "\n").encode()
    (destination / "main.tf.json").write_bytes(encoded)
    return {
        "provider": providers[0],
        "version": versions[0],
        "workload_lock_sha256": sha256(raw).hexdigest(),
        "schema_lock_sha256": sha256(
            (destination / ".terraform.lock.hcl").read_bytes()
        ).hexdigest(),
        "schema_configuration_sha256": sha256(encoded).hexdigest(),
    }


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
    schema_directory = destination.parent / (destination.name + "-provider-schema")
    schema_binding = prepare_schema_context(
        ROOT / "infra/part3/.terraform.lock.hcl", schema_directory
    )
    (destination / "schema-binding.json").write_text(json.dumps(schema_binding, indent=2) + "\n")
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
        "terraform-schema-initialize": [
            "terraform",
            "-chdir=" + str(schema_directory),
            "init",
            "-backend=false",
            "-input=false",
            "-lockfile=readonly",
            "-no-color",
        ],
        "terraform-schema": [
            "terraform",
            "-chdir=" + str(schema_directory),
            "providers",
            "schema",
            "-json",
        ],
        "tflint-version": ["tflint", "--version"],
        "tflint": ["tflint", "--chdir=infra/part3", "--format=json"],
        "handoff": [sys.executable, "-m", "tools.validate_part3_stage4_handoff"],
        "tests": [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_part3_stage4_handoff.py",
            "tests/test_part3_stage4_static_schema.py",
            "tests/test_part3_stage3_tooling.py",
            "-k",
            "handoff or ci_artifact or schema_context",
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
            "tests/test_part3_stage4_static_schema.py",
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
        "schema_binding": schema_binding,
        "stage4_complete": False,
        "rehearsal_ready": False,
        "aws_execution": False,
    }
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
