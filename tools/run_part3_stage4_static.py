#!/usr/bin/env python3
"""Run real provider validation and lint without AWS credentials or a backend."""

from __future__ import annotations

import json
import os
import re
import sys
from hashlib import sha256
from pathlib import Path

from tools.part3_stage4.qualification import (
    adjudicate_results,
    execute_check,
    require_read_only_environment,
    require_source_identity,
)

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


def build_commands(root: Path, destination: Path, schema_directory: Path) -> dict[str, list[str]]:
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
        "handoff": [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--rcfile=spec/part3-stage4-coverage.ini",
            "--data-file=" + str(destination / ".coverage.critical"),
            "-m",
            "tools.validate_part3_stage4_handoff",
        ],
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
    focused_tests = sorted(
        str(path.relative_to(root)) for path in (root / "tests").glob("test_part3_stage4_*.py")
    )
    commands["controls-tests"] = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--branch",
        "--rcfile=spec/part3-stage4-coverage.ini",
        "--data-file=" + str(destination / ".coverage.critical"),
        "-m",
        "pytest",
        *focused_tests,
        "-q",
        "-o",
        "addopts=",
        "--junitxml=" + str(destination / "controls-tests.xml"),
    ]
    commands["controls-coverage-combine"] = [
        sys.executable,
        "-m",
        "coverage",
        "combine",
        "--keep",
        "--data-file=" + str(destination / ".coverage.critical"),
    ]
    commands["controls-coverage"] = [
        sys.executable,
        "-m",
        "coverage",
        "report",
        "--fail-under=100",
        "--data-file=" + str(destination / ".coverage.critical"),
        "--include=tools/part3_stage4/*",
    ]
    commands["controls-coverage-json"] = [
        sys.executable,
        "-m",
        "coverage",
        "json",
        "--data-file=" + str(destination / ".coverage.critical"),
        "--include=tools/part3_stage4/*",
        "-o",
        str(destination / "controls-coverage.json"),
    ]
    commands["controls-lint"] = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "tools/part3_stage4",
        "tools/run_part3_stage4_mutations.py",
        *focused_tests,
    ]
    commands["controls-types"] = [
        sys.executable,
        "-m",
        "mypy",
        "--strict",
        "tools/part3_stage4",
        "tools/run_part3_stage4_mutations.py",
    ]
    commands["controls-mutations"] = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--rcfile=spec/part3-stage4-coverage.ini",
        "--data-file=" + str(destination / ".coverage.critical"),
        "-m",
        "tools.run_part3_stage4_mutations",
        "--output",
        str(destination / "mutations"),
    ]
    commands["inspector-rehearsal"] = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--rcfile=spec/part3-stage4-coverage.ini",
        "--data-file=" + str(destination / ".coverage.critical"),
        "-m",
        "tools.rehearse_part3_stage4_inspector",
        "--source",
        os.environ["STAGE4_ACCEPTED_CI_ARTIFACT"],
        "--destination",
        str(destination / "inspector-rehearsal"),
    ]
    commands["security-raw-scan"] = [
        "trivy",
        "config",
        "--disable-telemetry",
        "--cache-dir",
        str(destination / "trivy-cache"),
        "--skip-version-check",
        "--skip-check-update",
        "--include-non-failures",
        "--exit-code",
        "1",
        "--format",
        "json",
        "--output",
        str(destination / "trivy.json"),
        "infra/part3",
    ]
    commands["security-applicability"] = [
        sys.executable,
        "-c",
        "import json,sys; from pathlib import Path; "
        "from tools.part3_stage4.security import assess; "
        "print(json.dumps(assess(Path.cwd(), Path(sys.argv[1]).read_bytes()),sort_keys=True))",
        str(destination / "trivy.json"),
    ]
    return commands


def main() -> None:
    destination = Path(os.environ["STAGE4_EVIDENCE"]).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    source = require_source_identity(ROOT, os.environ["EXPECTED_SHA"])
    require_read_only_environment(os.environ, Path.home())
    schema_directory = destination.parent / (destination.name + "-provider-schema")
    schema_binding = prepare_schema_context(
        ROOT / "infra/part3/.terraform.lock.hcl", schema_directory
    )
    (destination / "schema-binding.json").write_text(json.dumps(schema_binding, indent=2) + "\n")
    env = dict(os.environ)
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    env["MYPYPATH"] = str(ROOT / "src")
    commands = build_commands(ROOT, destination, schema_directory)
    results = []
    for name, command in commands.items():
        result = execute_check(name, command, ROOT, destination, env)
        code = result["exit_code"]
        results.append(result)
        print(name + ": " + ("PASS" if code == 0 else "FAIL"), flush=True)
    payload_validation = adjudicate_results(
        destination,
        results,
        list(commands),
        {str(path.relative_to(ROOT)) for path in (ROOT / "tools/part3_stage4").glob("*.py")},
    )
    passed = payload_validation["passed"] is True
    summary = {
        **source,
        "checks": results,
        "static_subset_passed": passed,
        "schema_binding": schema_binding,
        "payload_validation": payload_validation,
        "stage4_complete": False,
        "rehearsal_ready": False,
        "aws_execution": False,
    }
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    raise SystemExit(int(not passed))


if __name__ == "__main__":
    main()
