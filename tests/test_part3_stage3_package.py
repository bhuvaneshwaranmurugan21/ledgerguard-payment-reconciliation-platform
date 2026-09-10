from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.build_part3_stage3_runtime import build_bundle
from tools.inspect_part3_stage3_artifact import inspect_runtime_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "d0fb01392f7f975909229f418c13a9c73ba8395e"
SOURCE_TREE = "6be2444b583fde20d6fd84d47a87cde9432e2952"
SOURCE_DATE_EPOCH = 1788948092


def test_runtime_bundle_is_reproducible_inspectable_and_offline_installable(
    tmp_path: Path,
) -> None:
    left = build_bundle(
        ROOT, Path(sys.prefix), tmp_path / "left", SOURCE_COMMIT, SOURCE_TREE, SOURCE_DATE_EPOCH
    )
    right = build_bundle(
        ROOT, Path(sys.prefix), tmp_path / "right", SOURCE_COMMIT, SOURCE_TREE, SOURCE_DATE_EPOCH
    )
    assert left == right
    left_bundle = tmp_path / "left/ledgerguard-stage3-glue-runtime.zip"
    right_bundle = tmp_path / "right/ledgerguard-stage3-glue-runtime.zip"
    assert left_bundle.read_bytes() == right_bundle.read_bytes()
    inspection = inspect_runtime_bundle(left_bundle)
    assert inspection["bundle_sha256"] == left["bundle"]["sha256"]
    assert inspection["wheel_count"] == 7
    assert inspection["oracle_excluded"] is inspection["generator_excluded"] is True

    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(left_bundle) as archive:
        archive.extractall(extracted)
    environment = tmp_path / "runtime"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--require-hashes",
            "--find-links",
            str(extracted / "wheelhouse"),
            "-r",
            str(extracted / "requirements/runtime.lock"),
        ],
        check=True,
    )
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "from importlib.util import find_spec; "
            "from ledgerguard.reconciliation.contracts import ContractRegistry; "
            "assert len(ContractRegistry.load_packaged().schemas)==9; "
            "assert find_spec('ledgerguard.stage3.job'); "
            "assert find_spec('ledgerguard.stage3.generator') is None; "
            "assert find_spec('ledgerguard.stage3.expectations') is None",
        ],
        check=False,
    )
    assert probe.returncode == 0


def test_runtime_package_manifest_matches_schema(tmp_path: Path) -> None:
    result = build_bundle(
        ROOT, Path(sys.prefix), tmp_path / "build", SOURCE_COMMIT, SOURCE_TREE, SOURCE_DATE_EPOCH
    )
    bundle = tmp_path / "build/ledgerguard-stage3-glue-runtime.zip"
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("package-manifest.json"))
    schema = json.loads(
        (ROOT / "contracts/part3-stage3/package-manifest-v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    assert result["source_commit"] == SOURCE_COMMIT


def test_runtime_builder_rejects_nonempty_destination(tmp_path: Path) -> None:
    destination = tmp_path / "not-empty"
    destination.mkdir()
    (destination / "unexpected").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="must be empty"):
        build_bundle(
            ROOT, Path(sys.prefix), destination, SOURCE_COMMIT, SOURCE_TREE, SOURCE_DATE_EPOCH
        )
