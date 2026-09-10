from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

import ledgerguard.stage3.campaign as campaign
import ledgerguard.stage3.expectations as expectations
import ledgerguard.stage3.runtime_admission as admission
from ledgerguard.reconciliation.contracts import ContractRegistry
from ledgerguard.stage3.canonical import canonical_bytes, canonical_digest, normalize
from ledgerguard.stage3.errors import Stage3Rejected
from ledgerguard.stage3.generator import _csv_line, _Writer, generate_profile
from ledgerguard.stage3.paths import S3Location, _overlap, parse_s3_uri, validate_job_paths
from ledgerguard.stage3.profiles import get_profile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "d0fb01392f7f975909229f418c13a9c73ba8395e"


@pytest.fixture()
def small_asset(tmp_path: Path) -> Path:
    root = tmp_path / "asset"
    generate_profile(get_profile("correctness-small"), root, SOURCE_COMMIT)
    return root


def _write(path: Path, value: Any) -> None:
    path.write_bytes(canonical_bytes(value) + b"\n")


def _resign(value: dict[str, Any], field: str) -> None:
    value[field] = canonical_digest({key: item for key, item in value.items() if key != field})


def test_canonical_rejects_controls_non_text_keys_and_nfc_key_collisions() -> None:
    with pytest.raises(Stage3Rejected, match="control character"):
        normalize("bad\nvalue")
    with pytest.raises(Stage3Rejected, match="non-string object key"):
        normalize({1: "value"})
    with pytest.raises(Stage3Rejected, match="normalized duplicate key"):
        normalize({"é": 1, "e\u0301": 2})


def test_generator_writer_empty_close_csv_quoting_and_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = _Writer(tmp_path, "PROCESSOR_EVENTS", "raw", "jsonl", 1)
    writer.close()
    assert writer.descriptors == []
    assert _csv_line({"field": 'a,"b"'}, ("field",)) == b'"a,""b"""\n'

    def fail(*args: object, **kwargs: object) -> dict[tuple[str, str], _Writer]:
        raise OSError("injected write failure")

    monkeypatch.setattr("ledgerguard.stage3.generator._writers", fail)
    with pytest.raises(OSError, match="injected write failure"):
        generate_profile(get_profile("correctness-small"), tmp_path / "failed", SOURCE_COMMIT)


def test_generator_propagates_midstream_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(self: _Writer, raw: bytes) -> None:
        raise OSError("midstream write failure")

    monkeypatch.setattr(_Writer, "add", fail)
    with pytest.raises(OSError, match="midstream write failure"):
        generate_profile(get_profile("correctness-small"), tmp_path / "failed", SOURCE_COMMIT)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"not-json\n", "invalid JSON document"),
        (b"[]\n", "document is not an object"),
    ],
)
def test_expectation_document_rejections(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "document.json"
    path.write_bytes(content)
    with pytest.raises(Stage3Rejected, match=message):
        expectations._load_object(path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\n", "invalid JSONL framing"),
        (b"{}", "invalid JSONL framing"),
        (b"{}\r\n", "invalid JSONL framing"),
        (b"not-json\n", "invalid JSONL"),
        (b"[]\n", "payload digest"),
        (b"{}\n", "payload digest"),
    ],
)
def test_expectation_jsonl_rejections(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_bytes(content)
    with pytest.raises(Stage3Rejected, match=message):
        list(expectations._json_rows([path]))


def test_expectation_csv_header_width_and_digest_rejections(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    path.write_text("wrong\nvalue\n", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="header mismatch"):
        list(expectations._csv_rows([path], "BANK_ENTRIES"))
    fields = expectations.CSV_FIELDS["BANK_ENTRIES"]
    path.write_text(",".join(fields) + "\n" + ",".join("x" for _ in fields[:-1]) + "\n")
    with pytest.raises(Stage3Rejected, match="width mismatch"):
        list(expectations._csv_rows([path], "BANK_ENTRIES"))
    row = {name: "x" for name in fields}
    row["amount_minor"] = "1"
    row["payload_sha256"] = "0" * 64
    path.write_text(",".join(fields) + "\n" + ",".join(row[name] for name in fields) + "\n")
    with pytest.raises(Stage3Rejected, match="CSV payload digest"):
        list(expectations._csv_rows([path], "BANK_ENTRIES"))


def test_expectation_missing_path_and_normalization_differences(tmp_path: Path) -> None:
    with pytest.raises(Stage3Rejected, match="missing raw"):
        expectations._paths(tmp_path, "raw", "PROCESSOR_EVENTS", "jsonl")
    raw_dir = tmp_path / "raw/processor-events"
    canonical_dir = tmp_path / "canonical/processor-events"
    raw_dir.mkdir(parents=True)
    canonical_dir.mkdir(parents=True)
    first = {"source_record_id": "one"}
    first["payload_sha256"] = canonical_digest(first)
    second = {"source_record_id": "two"}
    second["payload_sha256"] = canonical_digest(second)
    _write(raw_dir / "part.jsonl", first)
    _write(canonical_dir / "part.jsonl", second)
    with pytest.raises(Stage3Rejected, match="row differs"):
        expectations._compare_raw_canonical(tmp_path, "PROCESSOR_EVENTS")
    _write(canonical_dir / "extra.jsonl", second)
    _write(raw_dir / "part.jsonl", second)
    with pytest.raises(Stage3Rejected, match="row count differs"):
        expectations._compare_raw_canonical(tmp_path, "PROCESSOR_EVENTS")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_completion", "completion marker unavailable"),
        ("manifest_digest", "asset manifest digest mismatch"),
        ("files_type", "file inventory unavailable"),
        ("inventory_row", "invalid inventory row"),
        ("inventory_duplicate", "unsafe or duplicate inventory path"),
        ("counts", "construction count mismatch"),
    ],
)
def test_asset_envelope_failure_matrix(small_asset: Path, mutation: str, message: str) -> None:
    if mutation == "missing_completion":
        (small_asset / "COMPLETED.json").unlink()
    elif mutation == "manifest_digest":
        asset = json.loads((small_asset / "asset-manifest.json").read_text())
        asset["run_id"] = "changed"
        _write(small_asset / "asset-manifest.json", asset)
    elif mutation == "counts":
        value = json.loads((small_asset / "expectations.json").read_text())
        value["counts"]["BANK_ENTRIES"] += 1
        _resign(value, "expectations_sha256")
        _write(small_asset / "expectations.json", value)
        asset = json.loads((small_asset / "asset-manifest.json").read_text())
        for row in asset["files"]:
            if row["path"] == "expectations.json":
                row["size_bytes"] = (small_asset / "expectations.json").stat().st_size
                row["sha256"] = expectations._file_identity(small_asset / "expectations.json")[1]
        _resign(asset, "asset_manifest_sha256")
        _write(small_asset / "asset-manifest.json", asset)
        completion = json.loads((small_asset / "COMPLETED.json").read_text())
        completion["asset_manifest_sha256"] = asset["asset_manifest_sha256"]
        _write(small_asset / "COMPLETED.json", completion)
    else:
        asset = json.loads((small_asset / "asset-manifest.json").read_text())
        if mutation == "files_type":
            asset["files"] = "invalid"
        elif mutation == "inventory_row":
            asset["files"][0] = "invalid"
        else:
            asset["files"][1]["path"] = asset["files"][0]["path"]
        _resign(asset, "asset_manifest_sha256")
        _write(small_asset / "asset-manifest.json", asset)
        completion = json.loads((small_asset / "COMPLETED.json").read_text())
        completion["asset_manifest_sha256"] = asset["asset_manifest_sha256"]
        _write(small_asset / "COMPLETED.json", completion)
    with pytest.raises(Stage3Rejected, match=message):
        expectations.verify_assets(small_asset)


@pytest.mark.parametrize(
    ("family", "mutator", "message"),
    [
        (
            "PROCESSOR_SETTLEMENTS",
            lambda rows: [*rows[:-1], dict(rows[-1], reported_net_minor=0)],
            "settlement formula mismatch",
        ),
        (
            "LEDGER_JOURNALS",
            lambda rows: [
                dict(
                    rows[0],
                    postings=[dict(item, account_role="OTHER") for item in rows[0]["postings"]],
                ),
                *rows[1:],
            ],
            "clearing role count",
        ),
        (
            "LEDGER_JOURNALS",
            lambda rows: [
                dict(
                    rows[0],
                    postings=[
                        dict(item, amount_minor=int(item["amount_minor"]) + 1)
                        for item in rows[0]["postings"]
                    ],
                ),
                *rows[1:],
            ],
            "transaction total",
        ),
        (
            "BANK_ENTRIES",
            lambda rows: [dict(rows[0], amount_minor=int(rows[0]["amount_minor"]) + 1), *rows[1:]],
            "settlement total",
        ),
    ],
)
def test_independent_financial_readback_detects_faults(
    small_asset: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    mutator: Any,
    message: str,
) -> None:
    original = expectations._json_rows
    values: dict[str, list[dict[str, Any]]] = {}
    for name in expectations.FAMILIES:
        paths = expectations._paths(small_asset, "canonical", name, "jsonl")
        values[name] = list(original(paths))
    values[family] = mutator(values[family])
    monkeypatch.setattr(
        expectations,
        "_compare_raw_canonical",
        lambda root, name: json.loads((root / "expectations.json").read_text())["counts"][name],
    )

    def rows(paths: list[Path]) -> Any:
        directory = paths[0].parent.name
        name = next(
            candidate
            for candidate in expectations.FAMILIES
            if candidate.lower().replace("_", "-") == directory
        )
        return iter(values[name])

    monkeypatch.setattr(expectations, "_json_rows", rows)
    with pytest.raises(Stage3Rejected, match=message):
        expectations.verify_assets(small_asset)


def test_runtime_private_reader_and_path_failure_matrix(tmp_path: Path) -> None:
    with pytest.raises(Stage3Rejected, match="invalid document"):
        admission._document(tmp_path / "missing.json")
    value = tmp_path / "value.json"
    value.write_text("{}", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="noncanonical document"):
        admission._document(value)
    with pytest.raises(Stage3Rejected, match="relative path is not text"):
        admission._relative(tmp_path, 1)
    for relative in ("/absolute", "../escape", "missing"):
        with pytest.raises(Stage3Rejected, match=r"unsafe relative path|source object unavailable"):
            admission._relative(tmp_path, relative)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\n", "invalid JSONL framing"),
        (b"not-json\n", "invalid JSON"),
        (b'{"b":1,"a":2}\n', "noncanonical JSONL"),
    ],
)
def test_runtime_json_reader_rejections(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "source.jsonl"
    path.write_bytes(content)
    with pytest.raises(Stage3Rejected, match=message):
        list(admission._json_records(path))


def test_runtime_csv_reader_and_record_validation_rejections(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_text("wrong\nvalue\n", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="header mismatch"):
        list(admission._csv_records(path, "BANK_ENTRIES"))
    fields = admission.CSV_FIELDS["BANK_ENTRIES"]
    path.write_text(",".join(fields) + "\n" + ",".join("x" for _ in fields[:-1]) + "\n")
    with pytest.raises(Stage3Rejected, match="row width mismatch"):
        list(admission._csv_records(path, "BANK_ENTRIES"))
    with pytest.raises(Stage3Rejected, match="wrong format"):
        admission._validate_records(ContractRegistry.load(ROOT), "BANK_ENTRIES", "JSONL", path)
    invalid = {"schema_version": "2.0"}
    invalid["payload_sha256"] = canonical_digest(invalid)
    json_path = tmp_path / "invalid.jsonl"
    _write(json_path, invalid)
    with pytest.raises(Stage3Rejected, match="SCHEMA_VIOLATION"):
        admission._validate_records(
            ContractRegistry.load(ROOT), "PROCESSOR_EVENTS", "JSONL_CANONICAL_LF", json_path
        )
    invalid["payload_sha256"] = "0" * 64
    _write(json_path, invalid)
    with pytest.raises(Stage3Rejected, match="payload digest"):
        admission._validate_records(
            ContractRegistry.load(ROOT), "PROCESSOR_EVENTS", "JSONL_CANONICAL_LF", json_path
        )


def test_runtime_bundle_document_binding_failure_matrix(small_asset: Path) -> None:
    cases = (
        ("policy.json", "policy_version", "changed", "policy or manifest"),
        ("run-manifest.json", "source_commit", "0" * 40, "manifest digest"),
        ("source-bundle.json", "dataset_id", "changed", "source-bundle digest"),
    )
    for index, (name, field, value, message) in enumerate(cases):
        target = small_asset.parent / f"case-{index}"
        generate_profile(get_profile("correctness-small"), target, SOURCE_COMMIT)
        document = json.loads((target / name).read_text())
        document[field] = value
        _write(target / name, document)
        with pytest.raises(Stage3Rejected, match=message):
            admission.admit_runtime_bundle(ROOT, target)
    target = small_asset.parent / "policy-digest"
    generate_profile(get_profile("correctness-small"), target, SOURCE_COMMIT)
    policy = json.loads((target / "policy.json").read_text())
    policy["currency_rules"]["INR"]["transaction_tolerance_minor"] = 1
    _write(target / "policy.json", policy)
    with pytest.raises(Stage3Rejected, match="POLICY_MISMATCH"):
        admission.admit_runtime_bundle(ROOT, target)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("binding", "document binding"),
        ("objects_type", "source objects unavailable"),
        ("invalid_row", "invalid source object"),
        ("duplicate", "duplicate source path"),
        ("count", "object count"),
        ("missing_family", "source family set incomplete"),
    ],
)
def test_runtime_source_bundle_failure_matrix(
    small_asset: Path, mutation: str, message: str
) -> None:
    source = json.loads((small_asset / "source-bundle.json").read_text())
    if mutation == "binding":
        source["policy_sha256"] = "0" * 64
    elif mutation == "objects_type":
        source["objects"] = "invalid"
    elif mutation == "invalid_row":
        source["objects"][0] = "invalid"
    elif mutation == "duplicate":
        source["objects"][1]["relative_path"] = source["objects"][0]["relative_path"]
    elif mutation == "count":
        source["objects"][0]["record_count"] += 1
    else:
        source["objects"] = [row for row in source["objects"] if row["family"] != "BANK_ENTRIES"]
    _resign(source, "source_bundle_sha256")
    _write(small_asset / "source-bundle.json", source)
    with pytest.raises(Stage3Rejected, match=message):
        admission.admit_runtime_bundle(ROOT, small_asset)


def test_path_confinement_remaining_failure_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Stage3Rejected, match="NFC text"):
        parse_s3_uri("s3://bucket/e\u0301")
    with pytest.raises(Stage3Rejected, match="NFC text"):
        parse_s3_uri(cast(str, 1))
    assert _overlap(S3Location("a-bucket", ("a",)), S3Location("other-bucket", ("a",))) is False
    assert _overlap(S3Location("a-bucket", ("a",)), S3Location("a-bucket", ("a", "b")))
    valid = (
        "ledgerguard-bucket",
        "run-00000001",
        "attempt-00000001",
        "s3://ledgerguard-bucket/runs/run-00000001/inputs",
        "s3://ledgerguard-bucket/runs/run-00000001/attempts/attempt-00000001/candidates",
        "s3://ledgerguard-bucket/runs/run-00000001/attempts/attempt-00000001/evidence",
    )
    cases = (
        (("BAD", *valid[1:]), "workload bucket"),
        ((valid[0], "x", *valid[2:]), "run and attempt"),
        ((*valid[:3], "s3://ledgerguard-bucket/runs/other/inputs", *valid[4:]), "input prefix"),
        (
            (
                *valid[:4],
                "s3://ledgerguard-bucket/runs/run-00000001/attempts/other/candidates",
                valid[5],
            ),
            "candidate prefix",
        ),
        (
            (*valid[:5], "s3://ledgerguard-bucket/runs/run-00000001/attempts/other/evidence"),
            "evidence prefix",
        ),
    )
    for arguments, message in cases:
        with pytest.raises(Stage3Rejected, match=message):
            validate_job_paths(*arguments)
    monkeypatch.setattr("ledgerguard.stage3.paths._overlap", lambda left, right: True)
    with pytest.raises(Stage3Rejected, match="prefixes overlap"):
        validate_job_paths(*valid)


def test_campaign_private_boundaries_and_failure_classification(tmp_path: Path) -> None:
    empty = tmp_path / "canonical/processor-events"
    empty.mkdir(parents=True)
    with pytest.raises(Stage3Rejected, match="empty family"):
        campaign._canonical_rows(tmp_path, "PROCESSOR_EVENTS")
    (empty / "part.jsonl").write_text("[]\n", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="non-object row"):
        campaign._canonical_rows(tmp_path, "PROCESSOR_EVENTS")
    samples = {
        "PROCESSOR_EVENTS": {"processor": "p", "source_record_id": "1", "payload_sha256": "a"},
        "PROCESSOR_SETTLEMENTS": {"processor": "p", "source_record_id": "1", "payload_sha256": "a"},
        "LEDGER_JOURNALS": {"ledger_system": "l", "journal_id": "1", "payload_sha256": "a"},
        "BANK_ENTRIES": {"bank_account_id": "b", "bank_record_id": "1", "payload_sha256": "a"},
    }
    for family, row in samples.items():
        assert len(campaign._deduplicate([row, dict(row)], family)) == 1
        with pytest.raises(Stage3Rejected, match="IDENTITY_CONFLICT"):
            campaign._deduplicate([row, dict(row, payload_sha256="b")], family)


def test_campaign_detects_seeded_property_faults(
    small_asset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_digest = campaign._multiset_digest
    calls = iter(("a", "b"))
    monkeypatch.setattr(campaign, "_multiset_digest", lambda rows: next(calls))
    with pytest.raises(Stage3Rejected, match="ordering changed"):
        campaign.run_campaign(small_asset)
    monkeypatch.setattr(campaign, "_multiset_digest", original_digest)


def test_campaign_detects_partition_replay_and_conflict_control_failures(
    small_asset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_digest = campaign._multiset_digest
    values = iter(("same", "same", "different"))
    monkeypatch.setattr(campaign, "_multiset_digest", lambda rows: next(values))
    with pytest.raises(Stage3Rejected, match="partitioning changed"):
        campaign.run_campaign(small_asset)
    monkeypatch.setattr(campaign, "_multiset_digest", original_digest)

    monkeypatch.setattr(campaign, "_deduplicate", lambda rows, family: [])
    with pytest.raises(Stage3Rejected, match="replay was not idempotent"):
        campaign.run_campaign(small_asset)


def test_campaign_rejects_missing_or_wrong_conflict_classification(
    small_asset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual = campaign._deduplicate
    def missing(rows: list[dict[str, Any]], family: str) -> list[dict[str, Any]]:
        return actual(rows[:-1], family)

    monkeypatch.setattr(campaign, "_deduplicate", missing)
    with pytest.raises(Stage3Rejected, match="identity conflict was accepted"):
        campaign.run_campaign(small_asset)

    calls = 0

    def wrong(rows: list[dict[str, Any]], family: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return actual(rows, family)
        raise Stage3Rejected("OTHER", "wrong class")

    monkeypatch.setattr(campaign, "_deduplicate", wrong)
    with pytest.raises(Stage3Rejected, match="OTHER"):
        campaign.run_campaign(small_asset)


@pytest.mark.parametrize(
    ("family", "mutator", "message"),
    [
        (
            "PROCESSOR_EVENTS",
            lambda rows: [dict(row, merchant_id="only") for row in rows],
            "merchant isolation",
        ),
        ("BANK_ENTRIES", lambda rows: rows[1:], "split deposit"),
        (
            "PROCESSOR_EVENTS",
            lambda rows: [dict(row, currency="EUR") for row in rows],
            "currency coverage",
        ),
        ("LEDGER_JOURNALS", lambda rows: rows[1:], "source presence"),
        (
            "PROCESSOR_EVENTS",
            lambda rows: [
                dict(row, amount_minor=10**12) if row["event_type"] != "CAPTURE" else row
                for row in rows
            ],
            "negative reference",
        ),
        (
            "PROCESSOR_SETTLEMENTS",
            lambda rows: [*rows[:-1], dict(rows[-1], reported_net_minor=0)],
            "settlement formula",
        ),
    ],
)
def test_campaign_semantic_fault_matrix(
    small_asset: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    mutator: Any,
    message: str,
) -> None:
    original = campaign._canonical_rows
    mutated = mutator(original(small_asset, family))
    monkeypatch.setattr(
        campaign,
        "_canonical_rows",
        lambda root, requested: mutated if requested == family else original(root, requested),
    )
    with pytest.raises(Stage3Rejected, match=message):
        campaign.run_campaign(small_asset)
