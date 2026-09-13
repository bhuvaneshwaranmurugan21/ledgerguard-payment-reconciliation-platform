"""Actual reproducible package, install, import and manifest qualification."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from tools.build_part3_stage5_release import (
    LAMBDA_UNZIPPED_LIMIT,
    LAMBDA_ZIPPED_LIMIT,
    PROJECT_WHEEL,
    _record_line,
    _verify_installed_distribution,
    build_release,
    inspect_release,
)

ROOT = Path(__file__).parents[1]
ENVIRONMENT = Path(sys.prefix)
COMMIT = "2" * 40
TREE = "3" * 40
OPERATION = "release-test1"
BUCKET = f"ledgerguard-p3-857229544428-{OPERATION}"


def reference() -> dict[str, Any]:
    return {
        "uri": f"s3://{BUCKET}/runs/run-release1/inputs/execution-input.json",
        "version_id": "version-release-1",
        "sha256": "4" * 64,
        "size_bytes": 4096,
    }


@pytest.fixture(scope="module")
def releases(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, dict[str, Any]]:
    root = tmp_path_factory.mktemp("stage5-release")
    left = root / "left"
    right = root / "right"
    arguments = {
        "source_commit": COMMIT,
        "source_tree": TREE,
        "source_date_epoch": 1789257600,
        "operation_id": OPERATION,
        "execution_input": reference(),
    }
    first = build_release(ROOT, ENVIRONMENT, left, **arguments)
    second = build_release(ROOT, ENVIRONMENT, right, **arguments)
    assert first == second
    return left, right, first


def test_release_is_reproducible_complete_and_independently_inspectable(
    releases: tuple[Path, Path, dict[str, Any]],
) -> None:
    left, right, result = releases
    assert (left / "ledgerguard-stage5-release.zip").read_bytes() == (
        right / "ledgerguard-stage5-release.zip"
    ).read_bytes()
    assert result["aws_calls"] == 0
    inspection = inspect_release(left)
    assert inspection == inspect_release(right)
    assert inspection["source_commit"] == COMMIT
    assert inspection["source_tree"] == TREE
    assert inspection["bundle_sha256"] == result["bundle_sha256"]
    assert inspection["runtime_sha256"] == result["runtime_package_sha256"]
    assert inspection["runtime_zipped_bytes"] <= LAMBDA_ZIPPED_LIMIT
    assert inspection["runtime_unzipped_bytes"] <= LAMBDA_UNZIPPED_LIMIT
    assert inspection["glue_wheel_count"] == 7


def test_release_manifest_binds_real_stage5_artifacts_and_configuration(
    releases: tuple[Path, Path, dict[str, Any]],
) -> None:
    release, _right, result = releases
    manifest = json.loads((release / "release-manifest.json").read_text())
    runtime = manifest["runtime"]
    assert runtime["runtime_package_sha256"] == sha256(
        (release / "runtime.zip").read_bytes()
    ).hexdigest()
    assert runtime["script_sha256"] == sha256(
        (release / "ledgerguard_stage5_job.py").read_bytes()
    ).hexdigest()
    assert runtime["wheels_sha256"] == sha256(
        (release / "ledgerguard.gluewheels.zip").read_bytes()
    ).hexdigest()
    config = json.loads((release / "handler-config.json").read_text())
    assert config["operation_id"] == OPERATION
    assert config["execution_input"] == reference()
    assert config["release_manifest_sha256"] == result["release_manifest_sha256"]
    definition = json.loads((release / "state-machine.json").read_text())
    assert definition["TimeoutSeconds"] == 1800
    assert definition["StartAt"] == "ValidateExecution"
    terraform = json.loads((release / "terraform-stage5-release.json").read_text())
    assert terraform["definition"] == (release / "state-machine.json").read_text()
    assert terraform["validator_zip"] == terraform["controller_zip"] == "runtime.zip"
    assert terraform["manifest_sha256"] == result["release_manifest_sha256"]
    assert terraform["handler_config"] == (release / "handler-config.json").read_text()
    assert terraform["handler_config_sha256"] == result["handler_config_sha256"]


def test_glue_zip_of_wheels_installs_offline_and_imports_successor(
    releases: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    release, _right, _result = releases
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    with zipfile.ZipFile(release / "ledgerguard.gluewheels.zip") as archive:
        archive.extractall(wheels)
    environment = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", environment], check=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheels),
            str(wheels / PROJECT_WHEEL),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    completed = subprocess.run(
        [
            str(python),
            "-c",
            "from ledgerguard.reconciliation.contracts import ContractRegistry; "
            "from ledgerguard_control.successor_job import main; "
            "r=ContractRegistry.load_packaged(); "
            "assert len(r.schemas)==9 and callable(main)",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"},
    )
    assert completed.returncode == 0, completed.stderr


def test_lambda_zip_imports_only_its_packaged_dependencies_and_reads_parquet(
    releases: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    release, _right, _result = releases
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with zipfile.ZipFile(release / "runtime.zip") as archive:
        names = archive.namelist()
        assert not any("__pycache__" in name or "/tests/" in name for name in names)
        assert not any("ledgerguard_reference_oracle" in name for name in names)
        assert not any(name.endswith(("generator.py", "expectations.py")) for name in names)
        archive.extractall(runtime)
    program = """
from pathlib import Path
import tempfile
import numpy
import pyarrow as pa
import pyarrow.parquet as pq
from ledgerguard.reconciliation.contracts import ContractRegistry
from ledgerguard_control.controller import handler as controller
from ledgerguard_control.validator import handler as validator
assert numpy.__version__ == '2.1.3'
assert pa.__version__ == '17.0.0'
table = pa.table({'amount': pa.array([2**53 + 1], type=pa.int64())})
path = Path(tempfile.mkdtemp()) / 'proof.parquet'
pq.write_table(table, path)
assert pq.read_table(path).column('amount').to_pylist() == [2**53 + 1]
assert len(ContractRegistry.load_packaged().schemas) == 9
assert callable(controller) and callable(validator)
"""
    completed = subprocess.run(
        [sys.executable, "-S", "-c", program],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(runtime), "PYTHONNOUSERSITE": "1"},
    )
    assert completed.returncode == 0, completed.stderr


def test_release_inspector_rejects_changed_runtime_archive(
    releases: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    release, _right, _result = releases
    copied = tmp_path / "changed"
    copied.mkdir()
    for path in release.iterdir():
        if path.is_file():
            (copied / path.name).write_bytes(path.read_bytes())
    (copied / "runtime.zip").write_bytes(b"not a zip")
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        inspect_release(copied)


def test_distribution_verifier_allows_only_unhashed_generated_bytecode(
    tmp_path: Path,
) -> None:
    site = tmp_path / "environment/lib/python3.11/site-packages"
    package = site / "attrs"
    package.mkdir(parents=True)
    source = b'__version__ = "26.1.0"\n'
    (package / "__init__.py").write_bytes(source)
    info = site / "attrs-26.1.0.dist-info"
    info.mkdir()
    record = info / "RECORD"
    record.write_text(
        "\n".join(
            (
                _record_line("attrs/__init__.py", source),
                "attrs/__pycache__/__init__.cpython-311.pyc,,",
                "attrs/__pycache__/generated.cpython-311.pyc,sha256=changed,7",
                "attrs-26.1.0.dist-info/RECORD,,",
            )
        )
        + "\n"
    )
    _verify_installed_distribution(site, "attrs", "26.1.0")

    record.write_text(
        "\n".join(
            (
                _record_line("attrs/__init__.py", source),
                "attrs/unverified.txt,,",
                "attrs-26.1.0.dist-info/RECORD,,",
            )
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="unverified installed RECORD member"):
        _verify_installed_distribution(site, "attrs", "26.1.0")


def test_terraform_and_native_gate_bind_the_exact_handler_configuration() -> None:
    compute = (ROOT / "infra/part3/compute.tf").read_text()
    variables = (ROOT / "infra/part3/variables.tf").read_text()
    assert compute.count("HANDLER_CONFIG_JSON   = var.stage5_release.handler_config") == 2
    assert compute.count("HANDLER_CONFIG_SHA256 = var.stage5_release.handler_config_sha256") == 2
    for required in (
        "handler_config           = string",
        "handler_config_sha256    = string",
        "sha256(var.stage5_release.handler_config)",
        "jsondecode(var.stage5_release.handler_config).operation_id == var.operation_id",
    ):
        assert required in variables
    review = json.loads((ROOT / "spec/part3-stage4-security-review-v1.json").read_text())
    assert review["source_hashes"]["infra/part3/compute.tf"] == sha256(
        compute.encode()
    ).hexdigest()
    assert review["source_hashes"]["infra/part3/variables.tf"] == sha256(
        variables.encode()
    ).hexdigest()
    controls = (ROOT / "spec/part3-stage4-resource-controls-v1.json").read_bytes()
    assert review["resource_controls_sha256"] == sha256(controls).hexdigest()
    workflow = (ROOT / ".github/workflows/part3-stage5-incremental.yml").read_text()
    assert "tools/build_part3_stage5_release.py" in workflow
