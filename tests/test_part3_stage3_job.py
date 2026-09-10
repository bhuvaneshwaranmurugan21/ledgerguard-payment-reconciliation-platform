from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from pyspark.sql import DataFrame, SparkSession

import ledgerguard.stage3.job as job
from ledgerguard.reconciliation.contracts import ContractRegistry
from ledgerguard.stage3.arguments import JobArguments
from ledgerguard.stage3.canonical import canonical_digest
from ledgerguard.stage3.errors import Stage3Rejected
from ledgerguard.stage3.generator import generate_profile
from ledgerguard.stage3.profiles import get_profile
from ledgerguard.stage3.runtime_admission import RuntimeInputs, admit_runtime_bundle
from ledgerguard.stage3.spark_pipeline import MaterializationResult, SparkCandidates

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "d0fb01392f7f975909229f418c13a9c73ba8395e"


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    session = (
        SparkSession.builder.master("local[2]")
        .appName("ledgerguard-part3-stage3-job-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.ansi.enabled", "true")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture()
def small_asset(tmp_path: Path) -> Path:
    root = tmp_path / "asset"
    generate_profile(get_profile("correctness-small"), root, SOURCE_COMMIT)
    return root


def _arguments() -> JobArguments:
    bucket = "ledgerguard-bucket"
    run_id = "run-00000001"
    attempt_id = "attempt-00000001"
    return JobArguments(
        run_id,
        attempt_id,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        f"s3://{bucket}/runs/{run_id}/inputs",
        f"s3://{bucket}/runs/{run_id}/attempts/{attempt_id}/candidates",
        f"s3://{bucket}/runs/{run_id}/attempts/{attempt_id}/evidence",
        "control-00000001",
        SOURCE_COMMIT,
        "4" * 40,
        "5" * 64,
        bucket,
    )


def _argv(arguments: JobArguments) -> list[str]:
    values = {
        "run-id": arguments.run_id,
        "attempt-id": arguments.attempt_id,
        "policy-sha256": arguments.policy_sha256,
        "source-bundle-sha256": arguments.source_bundle_sha256,
        "manifest-sha256": arguments.manifest_sha256,
        "input-prefix": arguments.input_prefix,
        "candidate-output-prefix": arguments.candidate_output_prefix,
        "evidence-prefix": arguments.evidence_prefix,
        "control-record-identity": arguments.control_record_identity,
        "source-commit": arguments.source_commit,
        "source-tree": arguments.source_tree,
        "runtime-package-sha256": arguments.runtime_package_sha256,
        "workload-bucket": arguments.workload_bucket,
    }
    return [item for name, value in values.items() for item in (f"--{name}", value)]


def test_spark_factory_enforces_exact_runtime(
    spark: SparkSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert job._spark() is spark
    current_version = sys.version_info
    monkeypatch.setattr(job.sys, "version_info", (3, 10, 0))
    with pytest.raises(Stage3Rejected, match=r"Python 3\.11"):
        job._spark()
    monkeypatch.setattr(job.sys, "version_info", current_version)
    monkeypatch.setattr("pyspark.__version__", "0.0.0")
    with pytest.raises(Stage3Rejected, match=r"Spark 3\.5\.6"):
        job._spark()


def test_binary_document_and_source_identity_use_exact_single_object(
    spark: SparkSession, tmp_path: Path
) -> None:
    path = tmp_path / "document.json"
    path.write_text('{"value":1}\n', encoding="utf-8")
    assert job._read_document(spark, str(path)) == {"value": 1}
    size, digest = job._source_identity(spark, str(path))
    assert size == path.stat().st_size
    assert len(digest) == 64
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="invalid document"):
        job._read_document(spark, str(path))
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="not an object"):
        job._read_document(spark, str(path))
    directory = tmp_path / "many"
    directory.mkdir()
    (directory / "one.json").write_text("{}", encoding="utf-8")
    (directory / "two.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="not singular"):
        job._read_document(spark, str(directory / "*.json"))
    with pytest.raises(Stage3Rejected, match="not singular"):
        job._source_identity(spark, str(directory / "*.json"))


def _managed_fixture(small_asset: Path) -> tuple[JobArguments, dict[str, dict[str, Any]]]:
    policy = json.loads((small_asset / "policy.json").read_text())
    manifest = json.loads((small_asset / "run-manifest.json").read_text())
    source = json.loads((small_asset / "source-bundle.json").read_text())
    arguments = replace(
        _arguments(),
        run_id=manifest["run_id"],
        policy_sha256=policy["policy_sha256"],
        manifest_sha256=manifest["manifest_sha256"],
        source_bundle_sha256=source["source_bundle_sha256"],
    )
    return arguments, {"policy": policy, "run-manifest": manifest, "source-bundle": source}


def _patch_managed(
    monkeypatch: pytest.MonkeyPatch,
    documents: dict[str, dict[str, Any]],
    source: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        job,
        "_read_document",
        lambda spark, uri: next(
            value for name, value in documents.items() if uri.endswith(name + ".json")
        ),
    )
    identities = {
        row["relative_path"]: (row["size_bytes"], row["sha256"])
        for row in source.get("objects", [])
        if isinstance(row, dict) and "relative_path" in row
    }
    monkeypatch.setattr(
        job,
        "_source_identity",
        lambda spark, uri: next(value for name, value in identities.items() if uri.endswith(name)),
    )
    monkeypatch.setattr(
        job.ContractRegistry,
        "load_packaged",
        classmethod(lambda cls: ContractRegistry.load(ROOT)),
    )


def test_managed_inputs_bind_documents_files_and_all_families(
    small_asset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments, documents = _managed_fixture(small_asset)
    _patch_managed(monkeypatch, documents, documents["source-bundle"])
    result = job._managed_inputs(object(), arguments)
    assert result.manifest["source_commit"] == SOURCE_COMMIT
    assert set(result.raw_paths) == {
        "PROCESSOR_EVENTS",
        "PROCESSOR_SETTLEMENTS",
        "LEDGER_JOURNALS",
        "BANK_ENTRIES",
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("digest", "policy_sha256"),
        ("run", "run_id"),
        ("commit", "source_commit"),
        ("binding", "document binding"),
        ("objects", "source objects unavailable"),
        ("row", "invalid source object"),
        ("unsafe", "unsafe source object path"),
        ("family", "unknown source family"),
        ("identity", "source object"),
        ("incomplete", "source family set incomplete"),
    ],
)
def test_managed_input_failure_matrix(
    small_asset: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    arguments, documents = _managed_fixture(small_asset)
    source = documents["source-bundle"]
    if mutation == "digest":
        arguments = replace(arguments, policy_sha256="0" * 64)
    elif mutation == "run":
        arguments = replace(arguments, run_id="run-different")
    elif mutation == "commit":
        arguments = replace(arguments, source_commit="0" * 40)
    elif mutation == "binding":
        source["policy_sha256"] = "0" * 64
        source["source_bundle_sha256"] = canonical_digest(
            {key: value for key, value in source.items() if key != "source_bundle_sha256"}
        )
        arguments = replace(arguments, source_bundle_sha256=source["source_bundle_sha256"])
    elif mutation == "objects":
        source["objects"] = "invalid"
        source["source_bundle_sha256"] = canonical_digest(
            {key: value for key, value in source.items() if key != "source_bundle_sha256"}
        )
        arguments = replace(arguments, source_bundle_sha256=source["source_bundle_sha256"])
    elif mutation == "row":
        source["objects"][0] = "invalid"
    elif mutation == "unsafe":
        source["objects"][0]["relative_path"] = "../escape"
    elif mutation == "family":
        source["objects"][0]["family"] = "UNKNOWN"
    elif mutation == "incomplete":
        source["objects"] = [row for row in source["objects"] if row["family"] != "BANK_ENTRIES"]
    if mutation in {"row", "unsafe", "family", "incomplete"}:
        source["source_bundle_sha256"] = canonical_digest(
            {key: value for key, value in source.items() if key != "source_bundle_sha256"}
        )
        arguments = replace(arguments, source_bundle_sha256=source["source_bundle_sha256"])
    _patch_managed(monkeypatch, documents, source)
    if mutation == "identity":
        monkeypatch.setattr(job, "_source_identity", lambda spark, uri: (0, "0" * 64))
    with pytest.raises(Stage3Rejected, match=message):
        job._managed_inputs(object(), arguments)


def test_run_local_and_main_wiring_stop_spark_on_success_and_failure(
    small_asset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = admit_runtime_bundle(ROOT, small_asset)

    class FakeSpark:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    fake = FakeSpark()
    frame = cast(DataFrame, object())
    candidates = SparkCandidates(frame, frame, frame)
    materialized = MaterializationResult(tmp_path, 16, 4, 5, "1" * 64, "2" * 64)
    monkeypatch.setattr(job, "_spark", lambda: fake)
    monkeypatch.setattr(job, "admit_runtime_bundle", lambda repository, root: inputs)
    monkeypatch.setattr(job, "reconcile_sources", lambda spark, value: candidates)
    monkeypatch.setattr(job, "materialize_candidates", lambda *args: materialized)
    result = job.run_local(ROOT, small_asset, tmp_path / "candidate")
    assert result["transaction_count"] == 16
    assert result["authoritative_proof"] is False
    assert fake.stopped

    fake.stopped = False
    arguments = _arguments()
    monkeypatch.setattr(job, "_managed_inputs", lambda spark, value: inputs)
    called: list[tuple[object, ...]] = []
    monkeypatch.setattr(job, "materialize_candidates_uri", lambda *args: called.append(args))
    assert job.main(_argv(arguments)) == 0
    assert called and called[0][2] == arguments.run_id
    assert fake.stopped

    fake.stopped = False

    def fail(spark: object, value: RuntimeInputs) -> SparkCandidates:
        raise Stage3Rejected("INJECTED", "failure")

    monkeypatch.setattr(job, "reconcile_sources", fail)
    with pytest.raises(Stage3Rejected, match="INJECTED"):
        job.main(_argv(arguments))
    assert fake.stopped
