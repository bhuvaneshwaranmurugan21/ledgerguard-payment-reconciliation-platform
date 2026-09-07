from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from ledgerguard.stage2.control import Stage2Rejected, scan_safe_evidence, validate_manifest
from ledgerguard.stage2.evidence import build_manifest, finalize_artifact, write_json

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_exactness_and_finalization(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/report.json").write_text("{}\n")
    manifest = build_manifest(tmp_path)
    assert validate_manifest(tmp_path, manifest) == {"integrity_verified": True, "members": 1}
    assert finalize_artifact(tmp_path)["members"] == manifest["members"]
    (tmp_path / "opaque.bin").write_bytes(b"safe")
    assert scan_safe_evidence(tmp_path) == {"safe": True}


@pytest.mark.parametrize(
    "kind",
    ["empty", "shape", "path", "absolute", "backslash", "self", "digest", "extra", "symlink"],
)
def test_manifest_adversaries_are_rejected(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "report.json"
    path.write_text("{}\n")
    manifest = build_manifest(tmp_path)
    if kind == "empty":
        manifest["members"] = []
    elif kind == "shape":
        manifest["members"][0]["extra"] = True
    elif kind == "path":
        manifest["members"][0]["path"] = "../report.json"
    elif kind == "absolute":
        manifest["members"][0]["path"] = "/report.json"
    elif kind == "backslash":
        manifest["members"][0]["path"] = "a\\report.json"
    elif kind == "self":
        manifest["members"][0]["path"] = "manifest.json"
    elif kind == "digest":
        path.write_text("changed")
    elif kind == "extra":
        (tmp_path / "extra").write_text("extra")
    else:
        (tmp_path / "link").symlink_to(path)
    with pytest.raises(Stage2Rejected):
        validate_manifest(tmp_path, manifest)


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAABCDEFGHIJKLMNOP",
        "ASIAABCDEFGHIJKLMNOP",
        "-----BEGIN PRIVATE KEY-----",
        "account 857229544428",
    ],
)
def test_sensitive_evidence_is_rejected(tmp_path: Path, secret: str) -> None:
    (tmp_path / "evidence.json").write_text(secret)
    with pytest.raises(Stage2Rejected):
        scan_safe_evidence(tmp_path)


def _producer_artifact(path: Path) -> None:
    journal: list[dict[str, object]] = []
    evidence = {
        "schema_version": "1.0",
        "classification": "READ_ONLY_QUALIFICATION",
        "repository": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
        "event": "workflow_dispatch",
        "ref": "refs/heads/main",
        "commit": "a" * 40,
        "checkout_commit": "a" * 40,
        "workflow_path": ".github/workflows/part3-stage2-read-only.yml",
        "credential_mode": "GITHUB_OIDC",
        "authority_digests": {
            path: sha256((ROOT / path).read_bytes()).hexdigest()
            for path in (
                ".github/ledgerguard-target.json",
                ".github/workflows/part3-stage2-read-only.yml",
                "contracts/part3-stage2-control-plane-v1.json",
                "contracts/part3-stage2-cost-v1.json",
                "contracts/part3-stage2-glue-probe-v1.json",
                "contracts/part3-stage2-iam-permissions-v1.json",
                "contracts/part3-stage2-inventory-v1.json",
                "contracts/part3-stage2-oidc-trust-v1.json",
                "contracts/part3-stage2-operation-allowlist-v1.json",
                "contracts/part3/stage2-live-evidence-v1.schema.json",
                "fixtures/part3-stage2/inert_glue_probe_script.py",
                "fixtures/part3-stage2/qualification.asl.json",
            )
        },
        "run_id": "123",
        "run_attempt": "1",
        "identity": {
            "account_match": True,
            "region_match": True,
            "role_match": True,
            "identity_fingerprint": "b" * 64,
        },
        "checks": {"state": "PASSED"},
        "api_journal": journal,
        "mutation_journal": journal,
        "cleanup": {"required": False, "complete": True},
        "managed_reconciliation_started": False,
        "project_complete": False,
    }
    path.mkdir()
    write_json(path / "evidence.json", evidence)
    write_json(path / "api-journal.json", journal)
    write_json(path / "mutation-journal.json", journal)
    finalize_artifact(path)


def _run_metadata(path: Path, *, conclusion: str = "success") -> None:
    write_json(
        path,
        {
            "id": 123,
            "head_sha": "a" * 40,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "status": "completed",
            "conclusion": conclusion,
            "path": ".github/workflows/part3-stage2-read-only.yml",
            "repository": {
                "full_name": ("bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform")
            },
        },
    )


def test_safe_download_extraction_and_independent_inspection(tmp_path: Path) -> None:
    producer = tmp_path / "producer"
    _producer_artifact(producer)
    archive = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(producer.iterdir()):
            bundle.write(path, path.name)
    archive_digest = sha256(archive.read_bytes()).hexdigest()
    metadata = tmp_path / "metadata.json"
    write_json(
        metadata,
        {
            "id": 456,
            "name": f"ledgerguard-part3-stage2-read-only-{'a' * 40}-123",
            "expired": False,
            "workflow_run": {"id": 123},
        },
    )
    extracted = tmp_path / "extracted"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/part3_stage2_extract_artifact.py"),
            "--metadata",
            str(metadata),
            "--archive",
            str(archive),
            "--expected-artifact-id",
            "456",
            "--expected-run-id",
            "123",
            "--expected-name",
            f"ledgerguard-part3-stage2-read-only-{'a' * 40}-123",
            "--expected-archive-sha256",
            archive_digest,
            "--output",
            str(extracted),
        ],
        check=True,
    )
    report = tmp_path / "inspection.json"
    run_metadata = tmp_path / "run.json"
    _run_metadata(run_metadata)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/part3_stage2_inspect_artifact.py"),
            "--artifact",
            str(extracted),
            "--expected-sha",
            "a" * 40,
            "--expected-run-id",
            "123",
            "--expected-run-attempt",
            "1",
            "--expected-classification",
            "READ_ONLY_QUALIFICATION",
            "--run-metadata",
            str(run_metadata),
            "--expected-workflow-path",
            ".github/workflows/part3-stage2-read-only.yml",
            "--expected-conclusion-class",
            "SUCCESS",
            "--artifact-id",
            "456",
            "--artifact-zip-sha256",
            archive_digest,
            "--output",
            str(report),
        ],
        check=True,
    )
    assert json.loads(report.read_text())["independently_accepted"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_sha", "b" * 40),
        ("run_attempt", 2),
        ("event", "push"),
        ("head_branch", "dev"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("path", ".github/workflows/other.yml"),
        ("repository", {"full_name": "other/repository"}),
    ],
)
def test_independent_inspector_rejects_wrong_run_identity(
    tmp_path: Path, field: str, value: object
) -> None:
    producer = tmp_path / "producer"
    _producer_artifact(producer)
    run_metadata = tmp_path / "run.json"
    _run_metadata(run_metadata)
    run = json.loads(run_metadata.read_text())
    run[field] = value
    write_json(run_metadata, run)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/part3_stage2_inspect_artifact.py"),
            "--artifact",
            str(producer),
            "--expected-sha",
            "a" * 40,
            "--expected-run-id",
            "123",
            "--expected-run-attempt",
            "1",
            "--expected-classification",
            "READ_ONLY_QUALIFICATION",
            "--run-metadata",
            str(run_metadata),
            "--expected-workflow-path",
            ".github/workflows/part3-stage2-read-only.yml",
            "--expected-conclusion-class",
            "SUCCESS",
            "--artifact-id",
            "456",
            "--artifact-zip-sha256",
            "c" * 64,
            "--output",
            str(tmp_path / "inspection.json"),
        ],
        check=False,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("kind", ["metadata", "digest", "path"])
def test_download_artifact_adversaries_are_rejected(tmp_path: Path, kind: str) -> None:
    archive = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape" if kind == "path" else "evidence.json", "{}")
    digest = sha256(archive.read_bytes()).hexdigest()
    metadata = tmp_path / "metadata.json"
    write_json(
        metadata,
        {
            "id": 1 if kind == "metadata" else 456,
            "name": "expected",
            "expired": False,
            "workflow_run": {"id": 123},
        },
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/part3_stage2_extract_artifact.py"),
            "--metadata",
            str(metadata),
            "--archive",
            str(archive),
            "--expected-artifact-id",
            "456",
            "--expected-run-id",
            "123",
            "--expected-name",
            "expected",
            "--expected-archive-sha256",
            "0" * 64 if kind == "digest" else digest,
            "--output",
            str(tmp_path / "extracted"),
        ],
        check=False,
    )
    assert result.returncode != 0
