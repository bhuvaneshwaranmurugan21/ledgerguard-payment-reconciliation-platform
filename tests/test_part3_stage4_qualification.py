from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from tools.part3_stage4.qualification import (
    AUTHORITY_ENVIRONMENT,
    adjudicate_results,
    admit_coverage,
    admit_native_results,
    execute_check,
    require_read_only_environment,
    require_source_identity,
)

FIXTURE = Path(__file__).parent / "fixtures/part3-stage4-native-f23d77d"


def test_actual_native_records_are_admitted_without_claiming_successor_execution() -> None:
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    for name, digest in provenance["members"].items():
        assert sha256((FIXTURE / name).read_bytes()).hexdigest() == digest
    assert admit_native_results(FIXTURE)["native_results_admitted"] is True
    raw = (FIXTURE / "controls-coverage.json").read_bytes()
    files = set(json.loads(raw)["files"])
    assert admit_coverage(raw, files) == {
        "num_statements": 369,
        "covered_lines": 369,
        "num_branches": 178,
        "covered_branches": 178,
    }


@pytest.mark.parametrize("key", AUTHORITY_ENVIRONMENT)
def test_every_credential_authority_surface_rejects(key: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="credential authority"):
        require_read_only_environment({key: "present"}, tmp_path)


@pytest.mark.parametrize("name", [".aws/credentials", ".aws/config", ".boto"])
def test_inherited_credential_files_reject(name: str, tmp_path: Path) -> None:
    require_read_only_environment({}, tmp_path)
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("adversarial credential configuration sentinel")
    with pytest.raises(ValueError, match="credential configuration"):
        require_read_only_environment({}, tmp_path)


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("terraform-version.stdout", "terraform_version", "1.13.0"),
        ("terraform-version.stdout", "platform", "linux_arm64"),
        ("terraform-validate.stdout", "valid", False),
        ("terraform-validate.stdout", "valid", 1),
        ("terraform-validate.stdout", "error_count", False),
        ("terraform-validate.stdout", "warning_count", False),
        ("terraform-validate.stdout", "warning_count", 1),
        ("terraform-validate.stdout", "diagnostics", [{}]),
        ("tflint.stdout", "issues", [{}]),
        ("tflint.stdout", "errors", [{}]),
        ("tflint-version.stdout", None, "TFLint version 0.59.0\n"),
    ],
)
def test_native_result_drift_rejects_even_if_process_exited_zero(
    name: str,
    field: str | None,
    value: object,
    tmp_path: Path,
) -> None:
    shutil.copytree(FIXTURE, tmp_path / "records")
    path = tmp_path / "records" / name
    if field is None:
        path.write_text(str(value))
    else:
        data = json.loads(path.read_text())
        data[field] = value
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        admit_native_results(tmp_path / "records")


@pytest.mark.parametrize(
    "kind",
    [
        "missing_lines",
        "excluded_lines",
        "missing_branches",
        "count_type",
        "negative",
        "partial",
        "executed_branches",
        "uncovered",
        "totals",
        "total_gap",
        "inventory",
        "branch_mode",
    ],
)
def test_coverage_omissions_and_forged_summaries_reject(kind: str) -> None:
    data = json.loads((FIXTURE / "controls-coverage.json").read_text())
    files = set(data["files"])
    row = data["files"]["tools/part3_stage4/iam.py"]
    if kind in {"missing_lines", "excluded_lines", "missing_branches"}:
        row[kind] = [1]
    elif kind == "count_type":
        row["summary"]["covered_lines"] = True
    elif kind == "negative":
        row["summary"]["covered_lines"] = -1
    elif kind == "partial":
        row["summary"]["num_partial_branches"] = 1
    elif kind == "executed_branches":
        row["executed_branches"].pop()
    elif kind == "uncovered":
        row["summary"]["covered_lines"] -= 1
    elif kind == "totals":
        data["totals"]["covered_lines"] -= 1
    elif kind == "total_gap":
        data["totals"]["excluded_lines"] = 1
    elif kind == "inventory":
        files.add("tools/missing-critical-runner.py")
    else:
        data["meta"]["branch_coverage"] = False
    with pytest.raises(ValueError):
        admit_coverage(json.dumps(data).encode(), files)


@pytest.mark.parametrize("code", [0, 1, 2, 137])
def test_actual_process_status_and_both_streams_are_preserved(code: int, tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-c",
        f"import sys;print('out');print('err',file=sys.stderr);sys.exit({code})",
    ]
    result = execute_check("real-process", command, tmp_path, tmp_path, os.environ)
    assert result == {"check": "real-process", "command": command, "exit_code": code}
    assert (tmp_path / "real-process.stdout").read_text() == "out\n"
    assert (tmp_path / "real-process.stderr").read_text() == "err\n"
    with pytest.raises(FileExistsError):
        execute_check("real-process", command, tmp_path, tmp_path, os.environ)


def test_actual_timeout_and_missing_executable_are_not_success(tmp_path: Path) -> None:
    assert (
        execute_check(
            "timeout",
            [sys.executable, "-c", "import time;time.sleep(2)"],
            tmp_path,
            tmp_path,
            os.environ,
            timeout=0.02,
        )["exit_code"]
        == 124
    )
    assert "time limit" in (tmp_path / "timeout.stderr").read_text()
    assert (
        execute_check("missing", [str(tmp_path / "absent")], tmp_path, tmp_path, os.environ)[
            "exit_code"
        ]
        == 127
    )
    assert (tmp_path / "missing.stderr").read_text()


@pytest.mark.parametrize(
    "name,command,timeout",
    [("../escape", ["python"], 1), ("empty", [], 1), ("expired", ["python"], 0)],
)
def test_unsafe_process_requests_are_rejected_before_execution(
    name: str,
    command: list[str],
    timeout: float,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="invocation"):
        execute_check(name, command, tmp_path, tmp_path, os.environ, timeout)


def test_empty_coverage_inventory_cannot_pass() -> None:
    data = json.loads((FIXTURE / "controls-coverage.json").read_text())
    data["files"] = {}
    with pytest.raises(ValueError, match="inventory"):
        admit_coverage(json.dumps(data).encode(), set())


def test_actual_git_checkout_identity_and_cleanliness(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", "--shared", "--no-hardlinks", str(FIXTURE.parents[2]), str(repository)],
        check=True,
        capture_output=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    identity = require_source_identity(repository, head)
    assert identity["source_commit"] == head
    assert len(identity["source_tree"]) == 40
    with pytest.raises(ValueError, match="expected head"):
        require_source_identity(repository, "0" * 40)
    (repository / "unexpected-input.txt").write_text("untracked source")
    with pytest.raises(ValueError, match="not clean"):
        require_source_identity(repository, head)


@pytest.mark.parametrize(
    "change", ["none", "missing", "empty", "failed", "boolean", "absent-payload"]
)
def test_adjudication_requires_complete_real_records(change: str, tmp_path: Path) -> None:
    checks = json.loads((FIXTURE / "summary.json").read_text())["checks"]
    expected = [row["check"] for row in checks]
    files = set(json.loads((FIXTURE / "controls-coverage.json").read_text())["files"])
    source = FIXTURE
    if change == "missing":
        checks.pop()
    elif change == "empty":
        expected, checks = [], []
    elif change == "failed":
        checks[0]["exit_code"] = 1
    elif change == "boolean":
        checks[0]["exit_code"] = False
    elif change == "absent-payload":
        source = tmp_path
    result = adjudicate_results(source, checks, expected, files)
    assert result["passed"] is (change == "none")
