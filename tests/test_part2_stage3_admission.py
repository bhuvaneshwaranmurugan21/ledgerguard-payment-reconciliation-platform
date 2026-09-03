from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar

import pytest

import ledgerguard.reconciliation.contracts as contracts_module
from ledgerguard.reconciliation import (
    AdmissionRejected,
    AdmissionState,
    AdmittedRecord,
    ContractRegistry,
    admit_bundle,
    business_digest,
    canonical_json_bytes,
    canonical_sha256,
    canonical_timestamp,
    checked_abs,
    checked_add,
    checked_i64,
    checked_subtract,
    load_local_object_bytes,
    normalize_bank_reference,
    parse_strict_json,
    settlement_key,
    source_identity,
    transaction_key,
)
from ledgerguard.reconciliation.admission import (
    _currency_domain,
    _journal_admission,
    _record_key,
    _secure_local_path,
    _state_maps,
    _verify_cross_record_invariants,
    _verify_manifest,
    _verify_policy,
    object_locator,
    parse_json_lines,
)
from ledgerguard.reconciliation.arithmetic import (
    MAX_I64,
    MIN_I64,
    checked_multiply_sign,
    checked_sum,
)
from ledgerguard.reconciliation.canonical import normalize_json
from ledgerguard.reconciliation.errors import ADMISSION_REASONS
from ledgerguard_reference_oracle import (
    business_digest as oracle_business_digest,
)
from ledgerguard_reference_oracle import (
    canonical_json_bytes as oracle_canonical_json_bytes,
)
from ledgerguard_reference_oracle import (
    canonical_timestamp as oracle_canonical_timestamp,
)
from ledgerguard_reference_oracle import checked_abs as oracle_checked_abs
from ledgerguard_reference_oracle import checked_add as oracle_checked_add
from ledgerguard_reference_oracle import checked_i64 as oracle_checked_i64
from ledgerguard_reference_oracle import checked_subtract as oracle_checked_subtract
from ledgerguard_reference_oracle import source_identity as oracle_source_identity

ROOT = Path(__file__).resolve().parents[1]
COHERENCE = json.loads((ROOT / "spec/contract-coherence-vectors-v1.json").read_text())


def expect_rejection(reason: str, function: Any, *args: Any, **kwargs: Any) -> AdmissionRejected:
    with pytest.raises(AdmissionRejected) as caught:
        function(*args, **kwargs)
    assert caught.value.reason == reason
    assert caught.value.authoritative_proof is False
    return caught.value


def signed_record(record: dict[str, Any]) -> dict[str, Any]:
    value = normalize_json(record)
    assert isinstance(value, dict)
    value["payload_sha256"] = business_digest(value)
    return value


def processor_event(**updates: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": "2.0",
        "source_record_id": "event-1",
        "source_batch_id": "batch-1",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_type": "CAPTURE",
        "amount_minor": 100,
        "currency": "INR",
        "occurred_at": "2026-09-01T01:00:00Z",
        "received_at": "2026-09-01T01:01:00Z",
    }
    record.update(updates)
    return signed_record(record)


def processor_settlement(**updates: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": "2.0",
        "source_record_id": "settlement-record-1",
        "source_batch_id": "batch-1",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "settlement_id": "settlement-1",
        "settlement_cycle": "cycle-1",
        "currency": "INR",
        "gross_minor": 100,
        "fee_minor": 5,
        "refund_minor": 0,
        "chargeback_minor": 0,
        "reserve_minor": 0,
        "reported_net_minor": 95,
        "occurred_at": "2026-09-01T02:00:00Z",
        "received_at": "2026-09-01T02:01:00Z",
    }
    record.update(updates)
    return signed_record(record)


def journal(**updates: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": "2.0",
        "journal_id": "journal-1",
        "source_batch_id": "batch-1",
        "ledger_system": "ledger-a",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "entry_type": "CAPTURE",
        "currency": "INR",
        "effective_at": "2026-09-01T01:00:00Z",
        "received_at": "2026-09-01T01:02:00Z",
        "postings": [
            {
                "line_id": "line-1",
                "account_role": "PROCESSOR_CLEARING",
                "side": "DEBIT",
                "amount_minor": 100,
            },
            {
                "line_id": "line-2",
                "account_role": "MERCHANT_PAYABLE",
                "side": "CREDIT",
                "amount_minor": 100,
            },
        ],
    }
    record.update(updates)
    return signed_record(record)


def bank_entry(**updates: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": "2.0",
        "bank_record_id": "bank-1",
        "source_batch_id": "batch-1",
        "bank_account_id": "bank-account-1",
        "merchant_id": "merchant-1",
        "settlement_reference": "  settlement-1  ",
        "direction": "CREDIT",
        "amount_minor": 95,
        "currency": "INR",
        "value_at": "2026-09-01T03:00:00Z",
        "received_at": "2026-09-01T03:01:00Z",
    }
    record.update(updates)
    return signed_record(record)


def policy() -> dict[str, Any]:
    return deepcopy(COHERENCE["policy_manifest_proof_case_chain"]["policy"])


def json_lines(records: list[dict[str, Any]]) -> bytes:
    return b"\n".join(canonical_json_bytes(record) for record in records) + b"\n"


def build_bundle(
    families: dict[str, list[dict[str, Any]]] | None = None,
    policy_value: dict[str, Any] | None = None,
    run_id: str = "run-0001",
) -> tuple[bytes, bytes, dict[str, bytes], dict[str, Any]]:
    records = families or {
        "PROCESSOR_EVENTS": [processor_event()],
        "PROCESSOR_SETTLEMENTS": [processor_settlement()],
        "LEDGER_JOURNALS": [journal()],
        "BANK_ENTRIES": [bank_entry()],
    }
    admitted_policy = policy_value or policy()
    objects: list[dict[str, Any]] = []
    supplied: dict[str, bytes] = {}
    for family, rows in records.items():
        relative = family.lower().replace("_", "-") + ".jsonl"
        raw = json_lines(rows)
        descriptor = {
            "family": family,
            "schema_version": "2.0",
            "locator_type": "LOCAL_FILE",
            "relative_path": relative,
            "size_bytes": len(raw),
            "record_count": len(rows),
            "sha256": sha256(raw).hexdigest(),
        }
        objects.append(descriptor)
        supplied[f"local:{relative}"] = raw
    manifest: dict[str, Any] = {
        "schema_version": "2.0",
        "run_id": run_id,
        "source_commit": "a" * 40,
        "policy_version": admitted_policy["policy_version"],
        "policy_sha256": admitted_policy["policy_sha256"],
        "created_at": "2026-09-01T00:00:00Z",
        "objects": objects,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest, {"manifest_sha256"})
    return (
        canonical_json_bytes(admitted_policy),
        canonical_json_bytes(manifest),
        supplied,
        manifest,
    )


def test_p2s3_t001_happy_bundle_is_immutable_deterministic_and_proof_free() -> None:
    policy_bytes, manifest_bytes, supplied, _ = build_bundle()
    first = admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied)
    second = admit_bundle(ROOT, policy_bytes, manifest_bytes, dict(reversed(supplied.items())))
    assert len(first.records) == 4
    assert first.replay_count == 0
    assert first.authoritative_proof is False
    assert first.semantic_digest() == second.semantic_digest()
    assert first.state == second.state
    transaction_records = [
        row
        for row in first.records
        if row.reconciliation_key and row.reconciliation_key.startswith("txn:")
    ]
    settlement_records = [
        row
        for row in first.records
        if row.reconciliation_key and row.reconciliation_key.startswith("stl:")
    ]
    assert len(transaction_records) == 2
    assert len(settlement_records) == 1
    admitted_journal = next(row for row in first.records if row.family == "LEDGER_JOURNAL")
    assert admitted_journal.journal_balanced_total_minor == 100
    assert admitted_journal.journal_clearing_role_valid is True
    admitted_bank = next(row for row in first.records if row.family == "BANK_ENTRY")
    assert admitted_bank.reconciliation_key is None
    assert admitted_bank.normalized_settlement_reference == "settlement-1"
    value = admitted_bank.value()
    value["amount_minor"] = 1
    assert admitted_bank.value()["amount_minor"] == 95


def test_p2s3_t002_strict_json_and_normalization_boundaries() -> None:
    for raw in (
        b'{"amount":1.0}',
        b'{"amount":1e2}',
        b'{"amount":NaN}',
        b'{"a":1,"a":2}',
        b'{"e\xcc\x81":1,"\xc3\xa9":2}',
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'{"amount":9223372036854775808}',
        b'{"unterminated":',
    ):
        expect_rejection("SCHEMA_VIOLATION", parse_strict_json, raw)
    expect_rejection("SCHEMA_VIOLATION", canonical_json_bytes, {"value": "\ud800"})
    expect_rejection("SCHEMA_VIOLATION", canonical_json_bytes, {"value": 1.5})
    expect_rejection("SCHEMA_VIOLATION", canonical_json_bytes, {1: "value"})
    expect_rejection("SCHEMA_VIOLATION", canonical_json_bytes, {"e\u0301": 1, "é": 2})
    expect_rejection("SCHEMA_VIOLATION", canonical_json_bytes, {"value": {1, 2}})
    assert canonical_json_bytes(
        {"value": "e\u0301", "items": [None, True, 1]}
    ) == canonical_json_bytes({"items": [None, True, 1], "value": "é"})


def test_p2s3_t003_timestamps_match_frozen_vectors() -> None:
    for vector in COHERENCE["timestamp_vectors"]:
        assert canonical_timestamp(vector["input"]) == vector["expected"]
    for value in COHERENCE["invalid_timestamps"]:
        expect_rejection("SCHEMA_VIOLATION", canonical_timestamp, value)
    expect_rejection("SCHEMA_VIOLATION", canonical_timestamp, "2026-09-01 00:00:00Z")


def test_p2s3_t004_checked_arithmetic_boundaries() -> None:
    assert checked_i64(MIN_I64) == MIN_I64
    assert checked_i64(MAX_I64) == MAX_I64
    assert checked_add(MAX_I64, 0) == MAX_I64
    assert checked_subtract(7, 9) == -2
    assert checked_abs(-7) == 7
    assert checked_multiply_sign(7, -1) == -7
    assert checked_sum([1, 2, 3]) == 6
    expect_rejection("SCHEMA_VIOLATION", checked_i64, True)
    expect_rejection("SCHEMA_VIOLATION", checked_i64, MAX_I64 + 1)
    expect_rejection("SCHEMA_VIOLATION", checked_add, MAX_I64, 1)
    expect_rejection("SCHEMA_VIOLATION", checked_subtract, MIN_I64, 1)
    expect_rejection("SCHEMA_VIOLATION", checked_abs, MIN_I64)
    expect_rejection("POLICY_MISMATCH", checked_multiply_sign, 7, 0)


def test_p2s3_t005_oracle_differential_for_owned_overlap() -> None:
    source = normalize_json(COHERENCE["source_digest"]["record"])
    assert isinstance(source, dict)
    assert canonical_json_bytes(source) == oracle_canonical_json_bytes(source)
    assert business_digest(source) == oracle_business_digest(source)
    assert source_identity("PROCESSOR_EVENT", source) == oracle_source_identity(
        "PROCESSOR_EVENT", source
    )
    value = "2026-09-01T06:30:00+05:30"
    assert canonical_timestamp(value) == oracle_canonical_timestamp(value)
    assert checked_i64(MAX_I64) == oracle_checked_i64(MAX_I64)
    assert checked_add(7, 9) == oracle_checked_add(7, 9)
    assert checked_subtract(7, 9) == oracle_checked_subtract(7, 9)
    assert checked_abs(-7) == oracle_checked_abs(-7)


def test_p2s3_t006_active_registry_and_schema_errors() -> None:
    registry = ContractRegistry.load(ROOT)
    assert len(registry.schemas) == 9
    registry.validate("PROCESSOR_EVENT", processor_event())
    invalid = processor_event(amount_minor=0)
    expect_rejection("SCHEMA_VIOLATION", registry.validate, "PROCESSOR_EVENT", invalid)
    expect_rejection("SCHEMA_VIOLATION", registry.validate, "UNKNOWN", {})


def copy_contracts(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(ROOT / "contracts", repository / "contracts")
    return repository


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def trust_registry(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        contracts_module, "ACTIVE_REGISTRY_SHA256", sha256(path.read_bytes()).hexdigest()
    )


def test_p2s3_t007_registry_mutations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, tmp_path / "missing")

    repository = copy_contracts(tmp_path / "authority")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    registry["state"] = "MUTATED"
    write_json(registry_path, registry)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "registry-json")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry_path.write_bytes(b"{")
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "registry-scalar")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry_path.write_bytes(b"[]")
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "count")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    registry["contracts"].pop()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "digest")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    trust_registry(monkeypatch, registry_path)
    schema_path = repository / "contracts/v2/common-v2.schema.json"
    schema_path.write_text(schema_path.read_text() + " ")
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "id")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    row = registry["contracts"][0]
    schema_path = repository / row["path"]
    schema = json.loads(schema_path.read_text())
    schema["$id"] = "urn:wrong"
    write_json(schema_path, schema)
    row["sha256"] = sha256(schema_path.read_bytes()).hexdigest()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "dialect")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    row = registry["contracts"][0]
    schema_path = repository / row["path"]
    schema = json.loads(schema_path.read_text())
    schema["$schema"] = "https://json-schema.org/draft/2019-09/schema"
    write_json(schema_path, schema)
    row["sha256"] = sha256(schema_path.read_bytes()).hexdigest()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)


def test_p2s3_t008_duplicate_registry_identity_and_remote_ref_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = copy_contracts(tmp_path / "duplicate")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    first, second = registry["contracts"][:2]
    second_path = repository / second["path"]
    schema = json.loads(second_path.read_text())
    second["id"] = first["id"]
    schema["$id"] = first["id"]
    write_json(second_path, schema)
    second["sha256"] = sha256(second_path.read_bytes()).hexdigest()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)


def test_p2s3_t008b_registry_row_and_family_defenses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = copy_contracts(tmp_path / "row")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    registry["contracts"][0] = "invalid"
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "schema-missing")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    row = registry["contracts"][0]
    (repository / row["path"]).unlink()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "schema-json")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    row = registry["contracts"][0]
    schema_path = repository / row["path"]
    schema_path.write_bytes(b"{")
    row["sha256"] = sha256(schema_path.read_bytes()).hexdigest()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "schema-scalar")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    row = registry["contracts"][0]
    schema_path = repository / row["path"]
    schema_path.write_bytes(b"[]")
    row["sha256"] = sha256(schema_path.read_bytes()).hexdigest()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "schema-invalid")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    row = registry["contracts"][0]
    schema_path = repository / row["path"]
    schema = json.loads(schema_path.read_text())
    schema["type"] = 1
    write_json(schema_path, schema)
    row["sha256"] = sha256(schema_path.read_bytes()).hexdigest()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "identity")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    registry["contracts"][0]["family"] = None
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "family")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    registry["contracts"][0]["family"] = "UNKNOWN"
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)

    repository = copy_contracts(tmp_path / "reference")
    registry_path = repository / "contracts/active-contract-set-v1.json"
    registry = json.loads(registry_path.read_text())
    row = next(item for item in registry["contracts"] if item["family"] == "BANK_ENTRY")
    schema_path = repository / row["path"]
    schema = json.loads(schema_path.read_text())
    schema["properties"]["amount_minor"]["$ref"] = "https://invalid.example/schema"
    write_json(schema_path, schema)
    row["sha256"] = sha256(schema_path.read_bytes()).hexdigest()
    write_json(registry_path, registry)
    trust_registry(monkeypatch, registry_path)
    expect_rejection("SCHEMA_VIOLATION", ContractRegistry.load, repository)


def test_p2s3_t009_policy_and_manifest_bindings() -> None:
    registry = ContractRegistry.load(ROOT)
    admitted_policy = policy()
    digest, policy_state = _verify_policy(registry, admitted_policy, {})
    assert policy_state == {"v1": digest}
    assert _verify_policy(registry, admitted_policy, policy_state)[1] == policy_state
    changed = deepcopy(admitted_policy)
    changed["currency_rules"]["INR"]["transaction_tolerance_minor"] = 1
    changed["policy_sha256"] = canonical_sha256(changed, {"policy_sha256"})
    expect_rejection("POLICY_MISMATCH", _verify_policy, registry, changed, policy_state)
    bad_digest = deepcopy(admitted_policy)
    bad_digest["policy_sha256"] = "0" * 64
    expect_rejection("POLICY_MISMATCH", _verify_policy, registry, bad_digest, {})
    duplicate_domain = deepcopy(admitted_policy)
    duplicate_domain["settlement_rules"]["permitted_bank_accounts"].append(
        {
            "merchant_id": "merchant-1",
            "currency": "INR",
            "bank_account_ids": ["bank-account-2"],
        }
    )
    duplicate_domain["policy_sha256"] = canonical_sha256(duplicate_domain, {"policy_sha256"})
    expect_rejection("POLICY_MISMATCH", _verify_policy, registry, duplicate_domain, {})

    _, manifest_bytes, _, manifest = build_bundle()
    normalized_manifest = parse_strict_json(manifest_bytes)
    assert isinstance(normalized_manifest, dict)
    manifest_digest, state = _verify_manifest(
        registry, normalized_manifest, admitted_policy, digest, {}
    )
    assert state == {"run-0001": manifest_digest}
    changed_manifest = deepcopy(normalized_manifest)
    changed_manifest["created_at"] = "2026-09-01T00:00:01Z"
    changed_manifest["manifest_sha256"] = canonical_sha256(changed_manifest, {"manifest_sha256"})
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH",
        _verify_manifest,
        registry,
        changed_manifest,
        admitted_policy,
        digest,
        state,
    )
    malformed = deepcopy(manifest)
    malformed["manifest_sha256"] = "0" * 64
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH",
        _verify_manifest,
        registry,
        malformed,
        admitted_policy,
        digest,
        {},
    )
    wrong_version = deepcopy(manifest)
    wrong_version["policy_version"] = "v2"
    wrong_version["manifest_sha256"] = canonical_sha256(wrong_version, {"manifest_sha256"})
    expect_rejection(
        "POLICY_MISMATCH",
        _verify_manifest,
        registry,
        wrong_version,
        admitted_policy,
        digest,
        {},
    )
    wrong_digest = deepcopy(manifest)
    wrong_digest["policy_sha256"] = "0" * 64
    wrong_digest["manifest_sha256"] = canonical_sha256(wrong_digest, {"manifest_sha256"})
    expect_rejection(
        "POLICY_MISMATCH",
        _verify_manifest,
        registry,
        wrong_digest,
        admitted_policy,
        digest,
        {},
    )


class SchemaBypassRegistry:
    family_ids: ClassVar[dict[str, str]] = {
        "PROCESSOR_EVENT": "event",
        "PROCESSOR_SETTLEMENT": "settlement",
        "LEDGER_JOURNAL": "journal",
        "BANK_ENTRY": "bank",
    }

    def validate(self, family: str, value: Any) -> None:
        del family, value


def test_p2s3_t010_manifest_family_defense() -> None:
    admitted_policy = policy()
    _, _, _, manifest = build_bundle()
    manifest["objects"].pop()
    manifest["manifest_sha256"] = canonical_sha256(manifest, {"manifest_sha256"})
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH",
        _verify_manifest,
        SchemaBypassRegistry(),
        manifest,
        admitted_policy,
        admitted_policy["policy_sha256"],
        {},
    )


def test_p2s3_t011_object_locator_and_json_lines_boundaries() -> None:
    local = {"locator_type": "LOCAL_FILE", "relative_path": "a.jsonl"}
    s3 = {"locator_type": "S3_OBJECT", "s3_uri": "s3://bucket/key", "version_id": "v1"}
    assert object_locator(local) == "local:a.jsonl"
    assert object_locator(s3) == "s3:s3://bucket/key#v1"
    expect_rejection("SOURCE_IDENTITY_MISMATCH", object_locator, {"locator_type": "LOCAL_FILE"})
    expect_rejection("SOURCE_IDENTITY_MISMATCH", object_locator, {"locator_type": "S3_OBJECT"})
    expect_rejection("SOURCE_IDENTITY_MISMATCH", object_locator, {"locator_type": "OTHER"})
    raw = b'{"a":1}\n{"a":2}\n'
    digest = sha256(raw).hexdigest()
    assert parse_json_lines(raw, len(raw), digest, 2) == [{"a": 1}, {"a": 2}]
    empty = b"\n"
    assert parse_json_lines(empty, 1, sha256(empty).hexdigest(), 0) == []
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH", parse_json_lines, b"{}\n", 3, sha256(b"{}\n").hexdigest(), 0
    )
    for reason, args in (
        ("SCHEMA_VIOLATION", (raw, 0, digest, 2)),
        ("SCHEMA_VIOLATION", (raw, len(raw), digest, -1)),
        ("SOURCE_IDENTITY_MISMATCH", (raw, len(raw), None, 2)),
        ("SOURCE_IDENTITY_MISMATCH", (raw, len(raw) + 1, digest, 2)),
        ("SOURCE_IDENTITY_MISMATCH", (raw, len(raw), "0" * 64, 2)),
        ("SOURCE_IDENTITY_MISMATCH", (raw, len(raw), digest, 3)),
    ):
        expect_rejection(reason, parse_json_lines, *args)
    crlf = b'{"a":1}\r\n'
    expect_rejection(
        "SCHEMA_VIOLATION", parse_json_lines, crlf, len(crlf), sha256(crlf).hexdigest(), 1
    )
    blank = b'{"a":1}\n\n{"a":2}'
    expect_rejection(
        "SCHEMA_VIOLATION", parse_json_lines, blank, len(blank), sha256(blank).hexdigest(), 3
    )
    scalar = b"1"
    expect_rejection("SCHEMA_VIOLATION", parse_json_lines, scalar, 1, sha256(scalar).hexdigest(), 1)


def test_p2s3_t012_replay_conflict_and_prior_state_atomicity() -> None:
    duplicate = processor_event(source_batch_id="batch-2", received_at="2026-09-02T01:00:00Z")
    families = {
        "PROCESSOR_EVENTS": [processor_event(), duplicate],
        "PROCESSOR_SETTLEMENTS": [processor_settlement()],
        "LEDGER_JOURNALS": [journal()],
        "BANK_ENTRIES": [bank_entry()],
    }
    policy_bytes, manifest_bytes, supplied, _ = build_bundle(families)
    first = admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied)
    assert first.replay_count == 1
    second = admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied, first.state)
    assert second.replay_count == 5
    assert len(second.records) == 0
    prior = first.state
    conflict = processor_event(amount_minor=101)
    families["PROCESSOR_EVENTS"] = [conflict]
    policy_bytes, manifest_bytes, supplied, _ = build_bundle(families, run_id="run-0002")
    expect_rejection(
        "IDENTITY_CONFLICT", admit_bundle, ROOT, policy_bytes, manifest_bytes, supplied, prior
    )
    assert prior == first.state


def test_p2s3_t013_source_and_payload_identity_failures() -> None:
    record = processor_event()
    expect_rejection("SOURCE_IDENTITY_MISMATCH", source_identity, "UNKNOWN", record)
    missing = deepcopy(record)
    missing.pop("processor")
    expect_rejection("SOURCE_IDENTITY_MISMATCH", source_identity, "PROCESSOR_EVENT", missing)
    bad = processor_event()
    bad["payload_sha256"] = "0" * 64
    families = {
        "PROCESSOR_EVENTS": [bad],
        "PROCESSOR_SETTLEMENTS": [processor_settlement()],
        "LEDGER_JOURNALS": [journal()],
        "BANK_ENTRIES": [bank_entry()],
    }
    policy_bytes, manifest_bytes, supplied, _ = build_bundle(families)
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH", admit_bundle, ROOT, policy_bytes, manifest_bytes, supplied
    )


def test_p2s3_t014_journal_admission_defenses() -> None:
    assert _journal_admission(journal()) == (100, True)
    wrong_role = journal()
    wrong_role["postings"][0]["account_role"] = "BANK_CASH"
    assert _journal_admission(wrong_role) == (100, False)
    expect_rejection("UNBALANCED_JOURNAL", _journal_admission, {"postings": []})
    expect_rejection("UNBALANCED_JOURNAL", _journal_admission, {"postings": [1, 2]})
    duplicate = journal()
    duplicate["postings"][1]["line_id"] = "line-1"
    expect_rejection("UNBALANCED_JOURNAL", _journal_admission, duplicate)
    zero = journal()
    zero["postings"][0]["amount_minor"] = 0
    expect_rejection("UNBALANCED_JOURNAL", _journal_admission, zero)
    side = journal()
    side["postings"][0]["side"] = "LEFT"
    expect_rejection("UNBALANCED_JOURNAL", _journal_admission, side)
    unbalanced = journal()
    unbalanced["postings"][1]["amount_minor"] = 99
    expect_rejection("UNBALANCED_JOURNAL", _journal_admission, unbalanced)
    no_key = journal()
    no_key.pop("payment_id")
    expect_rejection("UNBALANCED_JOURNAL", _journal_admission, no_key)
    overflow = journal()
    overflow["postings"] = [
        {
            "line_id": "1",
            "account_role": "PROCESSOR_CLEARING",
            "side": "DEBIT",
            "amount_minor": MAX_I64,
        },
        {"line_id": "2", "account_role": "MERCHANT_PAYABLE", "side": "DEBIT", "amount_minor": 1},
        {
            "line_id": "3",
            "account_role": "MERCHANT_PAYABLE",
            "side": "CREDIT",
            "amount_minor": MAX_I64,
        },
    ]
    expect_rejection("SCHEMA_VIOLATION", _journal_admission, overflow)


def test_p2s3_t015_currency_conflict_and_settlement_ambiguity() -> None:
    families = {
        "PROCESSOR_EVENTS": [processor_event(currency="INR")],
        "PROCESSOR_SETTLEMENTS": [processor_settlement()],
        "LEDGER_JOURNALS": [journal(currency="USD")],
        "BANK_ENTRIES": [bank_entry()],
    }
    policy_bytes, manifest_bytes, supplied, _ = build_bundle(families)
    expect_rejection(
        "CURRENCY_DOMAIN_VIOLATION", admit_bundle, ROOT, policy_bytes, manifest_bytes, supplied
    )
    families = {
        "PROCESSOR_EVENTS": [processor_event()],
        "PROCESSOR_SETTLEMENTS": [
            processor_settlement(),
            processor_settlement(
                source_record_id="settlement-record-2",
                processor="processor-b",
                settlement_cycle="cycle-2",
            ),
        ],
        "LEDGER_JOURNALS": [journal()],
        "BANK_ENTRIES": [bank_entry()],
    }
    policy_bytes, manifest_bytes, supplied, _ = build_bundle(families)
    expect_rejection(
        "AMBIGUOUS_BANK_ALLOCATION", admit_bundle, ROOT, policy_bytes, manifest_bytes, supplied
    )


def test_p2s3_t016_identity_components_and_reference_rules() -> None:
    transaction = COHERENCE["transaction_key"]
    settlement = COHERENCE["settlement_key"]
    assert transaction_key(transaction["components"]) == transaction["expected_key"]
    assert settlement_key(settlement["components"]) == settlement["expected_key"]
    expect_rejection("SOURCE_IDENTITY_MISMATCH", transaction_key, {"processor": "a"})
    expect_rejection("SOURCE_IDENTITY_MISMATCH", settlement_key, {"processor": "a"})
    assert normalize_bank_reference("  settle-e\u0301.1  ") == "settle-é.1"
    assert normalize_bank_reference("Settle-1") != normalize_bank_reference("settle-1")
    assert normalize_bank_reference(None) is None
    expect_rejection("SCHEMA_VIOLATION", normalize_bank_reference, 1)


def admitted_record(
    family: str,
    value: dict[str, Any],
    key: str | None = None,
    reference: str | None = None,
) -> AdmittedRecord:
    return AdmittedRecord(
        family=family,
        source_identity=(family, str(len(value))),
        business_sha256="a" * 64,
        canonical_bytes=canonical_json_bytes(value),
        reconciliation_key=key,
        normalized_settlement_reference=reference,
        journal_balanced_total_minor=None,
        journal_clearing_role_valid=None,
    )


def test_p2s3_t016b_settlement_journal_and_ambiguity_defenses() -> None:
    settlement_journal = journal(entry_type="SETTLEMENT")
    settlement_journal.pop("payment_id")
    settlement_journal["settlement_id"] = "settlement-1"
    settlement_journal["settlement_cycle"] = "cycle-1"
    assert _record_key("LEDGER_JOURNAL", settlement_journal).startswith("stl:")
    assert _currency_domain("LEDGER_JOURNAL", settlement_journal)[0] == "SETTLEMENT"
    assert _record_key("BANK_ENTRY", bank_entry()) is None
    assert _currency_domain("BANK_ENTRY", bank_entry()) is None

    first = {
        "merchant_id": "merchant-1",
        "currency": "INR",
        "settlement_id": "settlement-1",
        "processor": "processor-a",
        "settlement_cycle": "cycle-1",
    }
    second = dict(first, settlement_id=" settlement-1 ", processor="processor-b")
    bank = {"merchant_id": "merchant-1", "currency": "INR"}
    records = (
        admitted_record("PROCESSOR_SETTLEMENT", first, "stl:first"),
        admitted_record("PROCESSOR_SETTLEMENT", second, "stl:second"),
        admitted_record("BANK_ENTRY", bank, reference="settlement-1"),
    )
    expect_rejection("AMBIGUOUS_BANK_ALLOCATION", _verify_cross_record_invariants, records)


def test_p2s3_t016c_admitted_record_bytes_remain_defensive() -> None:
    invalid = admitted_record("BANK_ENTRY", {})
    object.__setattr__(invalid, "canonical_bytes", b"[]")
    with pytest.raises(RuntimeError, match="not an object"):
        invalid.value()


def test_p2s3_t017_bundle_and_object_set_failures() -> None:
    policy_bytes, manifest_bytes, supplied, manifest = build_bundle()
    expect_rejection("SCHEMA_VIOLATION", admit_bundle, ROOT, b"[]", manifest_bytes, supplied)
    expect_rejection("SCHEMA_VIOLATION", admit_bundle, ROOT, policy_bytes, b"[]", supplied)
    missing = dict(supplied)
    missing.pop(next(iter(missing)))
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH", admit_bundle, ROOT, policy_bytes, manifest_bytes, missing
    )
    extra = dict(supplied, **{"local:extra.jsonl": b"{}\n"})
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH", admit_bundle, ROOT, policy_bytes, manifest_bytes, extra
    )
    duplicate = deepcopy(manifest)
    duplicate["objects"].append(deepcopy(duplicate["objects"][0]))
    duplicate["manifest_sha256"] = canonical_sha256(duplicate, {"manifest_sha256"})
    expect_rejection(
        "SOURCE_IDENTITY_MISMATCH",
        admit_bundle,
        ROOT,
        policy_bytes,
        canonical_json_bytes(duplicate),
        supplied,
    )


def test_p2s3_t018_local_loader_confinement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_bytes, manifest_bytes, supplied, manifest = build_bundle()
    del policy_bytes, manifest_bytes
    for descriptor in manifest["objects"]:
        relative = descriptor["relative_path"]
        path = tmp_path / relative
        path.write_bytes(supplied[f"local:{relative}"])
    assert load_local_object_bytes(manifest, tmp_path) == supplied
    expect_rejection("SOURCE_IDENTITY_MISMATCH", _secure_local_path, tmp_path, "../escape")
    expect_rejection("SOURCE_IDENTITY_MISMATCH", _secure_local_path, tmp_path, "missing.jsonl")
    directory = tmp_path / "directory"
    directory.mkdir()
    expect_rejection("SOURCE_IDENTITY_MISMATCH", _secure_local_path, tmp_path, "directory")
    target = tmp_path / manifest["objects"][0]["relative_path"]
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    expect_rejection("SOURCE_IDENTITY_MISMATCH", _secure_local_path, tmp_path, "link.jsonl")
    expect_rejection("SCHEMA_VIOLATION", load_local_object_bytes, {"objects": "bad"}, tmp_path)
    expect_rejection("SCHEMA_VIOLATION", load_local_object_bytes, {"objects": [1]}, tmp_path)
    s3_manifest = {"objects": [{"locator_type": "S3_OBJECT"}]}
    expect_rejection("SOURCE_IDENTITY_MISMATCH", load_local_object_bytes, s3_manifest, tmp_path)
    missing_path = {"objects": [{"locator_type": "LOCAL_FILE"}]}
    expect_rejection("SOURCE_IDENTITY_MISMATCH", load_local_object_bytes, missing_path, tmp_path)
    duplicated = deepcopy(manifest)
    duplicated["objects"].append(deepcopy(duplicated["objects"][0]))
    expect_rejection("SOURCE_IDENTITY_MISMATCH", load_local_object_bytes, duplicated, tmp_path)

    safe = tmp_path / "safe.jsonl"
    safe.write_text("{}\n")
    outside = tmp_path.parent / "outside.jsonl"
    outside.write_text("{}\n")
    original_resolve = Path.resolve

    def escaped_resolve(path: Path, strict: bool = False) -> Path:
        if path == tmp_path:
            return tmp_path
        if path == safe:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", escaped_resolve)
    expect_rejection("SOURCE_IDENTITY_MISMATCH", _secure_local_path, tmp_path, "safe.jsonl")


def test_p2s3_t018b_local_loader_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "input.jsonl"
    target.write_text("{}\n")
    manifest = {"objects": [{"locator_type": "LOCAL_FILE", "relative_path": "input.jsonl"}]}

    def unreadable(path: Path) -> bytes:
        del path
        raise OSError("simulated stable read failure")

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    expect_rejection("SOURCE_IDENTITY_MISMATCH", load_local_object_bytes, manifest, tmp_path)


def test_p2s3_t019_state_mapping_and_error_serialization() -> None:
    state = AdmissionState(
        policy_versions=(("v1", "a" * 64),),
        run_manifests=(("run-1", "b" * 64),),
    )
    assert _state_maps(state) == ({"v1": "a" * 64}, {"run-1": "b" * 64}, {})
    error = AdmissionRejected("POLICY_MISMATCH", "changed", "/policy")
    assert error.as_dict() == {
        "outcome": "ADMISSION_REJECTED",
        "reason_code": "POLICY_MISMATCH",
        "detail": "changed",
        "path": "/policy",
        "authoritative_proof": False,
    }
    with pytest.raises(ValueError, match="unknown admission reason"):
        AdmissionRejected("UNKNOWN", "bad")
    assert len(ADMISSION_REASONS) == 7


def test_p2s3_t020_production_never_imports_oracle() -> None:
    imports: set[str] = set()
    for path in (ROOT / "src/ledgerguard/reconciliation").glob("*.py"):
        tree = ast.parse(path.read_text())
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imports.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
    assert not any(name.startswith("ledgerguard_reference_oracle") for name in imports)


def test_p2s3_t021_hash_seed_determinism() -> None:
    script = """
import json, os
from pathlib import Path
from tests.test_part2_stage3_admission import build_bundle
from ledgerguard.reconciliation import admit_bundle
root=Path(os.environ['LEDGERGUARD_ROOT'])
p,m,o,_=build_bundle()
b=admit_bundle(root,p,m,o)
result={'digest':b.semantic_digest(),'records':[r.source_identity for r in b.records]}
print(json.dumps(result,sort_keys=True,separators=(',',':')))
"""
    outputs = []
    for seed in ("101", "202"):
        environment = dict(os.environ, PYTHONHASHSEED=seed, LEDGERGUARD_ROOT=str(ROOT))
        outputs.append(
            subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, env=environment)
        )
    assert outputs[0] == outputs[1]


def test_p2s3_t022_claim_boundary_is_admission_only() -> None:
    source = (ROOT / "src/ledgerguard/reconciliation/admission.py").read_text()
    forbidden = ("boto3", "pyspark", "dynamodb", "put_item", "proof_id", "case_id")
    assert not any(token in source.lower() for token in forbidden)
    assert "authoritative_proof: bool = False" in source
