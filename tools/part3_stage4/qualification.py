"""Fail-closed native-result admission and real subprocess evidence capture."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

AUTHORITY_ENVIRONMENT = (
    "AWS_ACCESS_KEY_ID",
    "AWS_ACCESS_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SECRET_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_ROLE_SESSION_NAME",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "BOTO_CONFIG",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)


def require_source_identity(root: Path, expected: str) -> dict[str, str]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != expected:
        raise ValueError("checkout does not match exact expected head")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root):
        raise ValueError("qualification source is not clean")
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
    return {"source_commit": head, "source_tree": tree}


def require_read_only_environment(environment: Mapping[str, str], home: Path) -> None:
    if any(environment.get(key) for key in AUTHORITY_ENVIRONMENT):
        raise ValueError("static validation must not receive AWS credential authority")
    if any((home / name).exists() for name in (".aws/credentials", ".aws/config", ".boto")):
        raise ValueError("static validation must not inherit credential configuration")


def execute_check(
    name: str,
    command: Sequence[str],
    root: Path,
    destination: Path,
    environment: Mapping[str, str],
    timeout: float = 600,
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or not command or timeout <= 0:
        raise ValueError("invalid check invocation")
    with (
        (destination / (name + ".stdout")).open("x") as out,
        (destination / (name + ".stderr")).open("x") as err,
    ):
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=dict(environment),
                stdout=out,
                stderr=err,
                timeout=timeout,
                check=False,
            )
            code = completed.returncode
        except subprocess.TimeoutExpired:
            code = 124
            err.write("qualification process exceeded its time limit\n")
        except OSError as error:
            code = 127
            err.write(str(error) + "\n")
    return {"check": name, "command": list(command), "exit_code": code}


def admit_native_results(directory: Path) -> dict[str, Any]:
    version = json.loads((directory / "terraform-version.stdout").read_text())
    if (version.get("terraform_version"), version.get("platform")) != ("1.13.1", "linux_amd64"):
        raise ValueError("native Terraform identity differs")
    validation = json.loads((directory / "terraform-validate.stdout").read_text())
    if (
        validation.get("valid") is not True
        or type(validation.get("error_count")) is not int
        or type(validation.get("warning_count")) is not int
    ):
        raise ValueError("native Terraform result types differ")
    if validation != {
        "format_version": "1.0",
        "valid": True,
        "error_count": 0,
        "warning_count": 0,
        "diagnostics": [],
    }:
        raise ValueError("native Terraform validation did not pass cleanly")
    lint_version = (directory / "tflint-version.stdout").read_text().splitlines()
    if lint_version != ["TFLint version 0.59.1", "+ ruleset.terraform (0.13.0-bundled)"]:
        raise ValueError("native TFLint identity differs")
    if json.loads((directory / "tflint.stdout").read_text()) != {"issues": [], "errors": []}:
        raise ValueError("native TFLint findings remain")
    return {"terraform": "1.13.1", "tflint": "0.59.1", "native_results_admitted": True}


def admit_coverage(raw: bytes, required_files: set[str]) -> dict[str, int]:
    data = json.loads(raw)
    if (
        not required_files
        or data["meta"]["branch_coverage"] is not True
        or set(data["files"]) != required_files
    ):
        raise ValueError("critical coverage inventory differs")
    aggregate = {"num_statements": 0, "covered_lines": 0, "num_branches": 0, "covered_branches": 0}
    for row in data["files"].values():
        summary = row["summary"]
        if row["missing_lines"] or row["excluded_lines"] or row["missing_branches"]:
            raise ValueError("critical coverage has missing or excluded code")
        for key in aggregate:
            value = summary[key]
            if type(value) is not int or value < 0:
                raise ValueError("invalid coverage count")
            aggregate[key] += value
        if (
            summary["num_statements"] != summary["covered_lines"]
            or summary["num_branches"] != summary["covered_branches"]
            or any(
                summary[key] != 0
                for key in (
                    "missing_lines",
                    "missing_branches",
                    "excluded_lines",
                    "num_partial_branches",
                )
            )
            or len(row["executed_branches"]) != summary["covered_branches"]
        ):
            raise ValueError("critical coverage summary differs from executed records")
    if any(data["totals"][key] != value for key, value in aggregate.items()):
        raise ValueError("critical coverage totals differ")
    if any(
        data["totals"][key] != 0
        for key in ("missing_lines", "missing_branches", "excluded_lines", "num_partial_branches")
    ):
        raise ValueError("critical coverage totals contain gaps")
    return aggregate


def adjudicate_results(
    directory: Path,
    results: list[dict[str, Any]],
    expected_checks: list[str],
    required_files: set[str],
) -> dict[str, Any]:
    validation: dict[str, Any] = {"passed": False}
    try:
        if not expected_checks or [row["check"] for row in results] != expected_checks:
            raise ValueError("qualification command inventory differs")
        native = admit_native_results(directory)
        coverage = admit_coverage(
            (directory / "controls-coverage.json").read_bytes(), required_files
        )
        validation.update(native=native, coverage=coverage)
        validation["passed"] = all(
            type(row["exit_code"]) is int
            and row["exit_code"] == (1 if row["check"] == "security-raw-scan" else 0)
            for row in results
        )
    except (ValueError, KeyError, TypeError, OSError) as error:
        validation["error"] = str(error)
    return validation
