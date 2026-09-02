from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.foundation import (
    FoundationError,
    canonical_json_bytes,
    canonical_sha256,
    canonical_timestamp,
    derive_contract_id,
    parse_contract_json,
)
from ledgerguard.part1 import reproduce_stage3
from ledgerguard_correction_c4 import materialize_stage5_view

ACTIVE_ROOT = Path(__file__).resolve().parents[1]
_STAGE5_TEMPORARY = tempfile.TemporaryDirectory(prefix="ledgerguard-coherence-tests-")
ROOT = materialize_stage5_view(ACTIVE_ROOT, Path(_STAGE5_TEMPORARY.name) / "repository")
PROFILE: dict[str, Any] = json.loads(
    (ROOT / "spec/contract-coherence-v1.json").read_text(encoding="utf-8")
)
VECTORS: dict[str, Any] = json.loads(
    (ROOT / "spec/contract-coherence-vectors-v1.json").read_text(encoding="utf-8")
)
TIMESTAMP_FIELDS = set(PROFILE["canonicalization"]["timestamp_fields"])


def test_coh_t001_strict_json_rejects_noncanonical_numbers() -> None:
    for number in VECTORS["invalid_json_numbers"]:
        with pytest.raises(FoundationError):
            parse_contract_json('{"amount_minor":' + number + "}")
    assert parse_contract_json('{"amount_minor":1}')["amount_minor"] == 1


def test_coh_t002_strict_json_rejects_ambiguous_keys_encoding_and_unicode() -> None:
    with pytest.raises(FoundationError, match="duplicate"):
        parse_contract_json('{"amount_minor":1,"amount_minor":2}')
    with pytest.raises(FoundationError, match="collision"):
        parse_contract_json('{"Caf\\u00e9":1,"Cafe\\u0301":2}')
    with pytest.raises(FoundationError, match="BOM"):
        parse_contract_json('\ufeff{"amount_minor":1}')
    with pytest.raises(FoundationError, match="surrogate"):
        parse_contract_json('{"merchant_id":"\\ud800"}')
    parsed = parse_contract_json('{"flag":true,"amount_minor":1}')
    assert type(parsed["flag"]) is bool
    assert type(parsed["amount_minor"]) is int


def test_coh_t003_canonical_json_is_compact_sorted_nfc_utf8() -> None:
    first = {"z": "Cafe\u0301", "a": 1}
    second = {"a": 1, "z": "Caf\u00e9"}
    expected = '{"a":1,"z":"Caf\u00e9"}'.encode()
    assert canonical_json_bytes(first) == expected
    assert canonical_json_bytes(second) == expected


def test_coh_t004_timestamps_are_calendar_valid_offset_aware_and_deterministic() -> None:
    for vector in VECTORS["timestamp_vectors"]:
        assert canonical_timestamp(vector["input"]) == vector["expected"]
    for value in VECTORS["invalid_timestamps"]:
        with pytest.raises(FoundationError):
            canonical_timestamp(value)


def test_coh_t005_source_digest_scope_has_golden_bytes_and_replay_semantics() -> None:
    vector = VECTORS["source_digest"]
    scope = set(PROFILE["digest_scopes"]["source_payload_sha256"]["exclude"])
    record = vector["record"]
    canonical = canonical_json_bytes(
        {key: item for key, item in record.items() if key not in scope}, TIMESTAMP_FIELDS
    )
    assert canonical.decode() == vector["expected_canonical_json"]
    assert sha256(canonical).hexdigest() == vector["expected_sha256"]
    replay = dict(record, **vector["equivalent_redelivery"])
    conflict = dict(record, **vector["conflicting_redelivery"])
    assert (
        canonical_sha256(replay, excluded_fields=scope, timestamp_fields=TIMESTAMP_FIELDS)
        == vector["expected_sha256"]
    )
    assert (
        canonical_sha256(conflict, excluded_fields=scope, timestamp_fields=TIMESTAMP_FIELDS)
        != vector["expected_sha256"]
    )


def test_coh_t006_policy_manifest_proof_and_case_digests_are_golden() -> None:
    chain = VECTORS["policy_manifest_proof_case_chain"]
    cases = (
        ("policy_sha256", "policy", "expected_policy_sha256"),
        ("manifest_sha256", "manifest", "expected_manifest_sha256"),
        ("proof_sha256", "proof", "expected_proof_sha256"),
        ("case_revision_sha256", "case_revision_one", "expected_case_revision_one_sha256"),
        ("case_revision_sha256", "case_revision_two", "expected_case_revision_two_sha256"),
    )
    for scope_name, value_name, expected_name in cases:
        scope = set(PROFILE["digest_scopes"][scope_name]["exclude"])
        assert (
            canonical_sha256(
                chain[value_name], excluded_fields=scope, timestamp_fields=TIMESTAMP_FIELDS
            )
            == chain[expected_name]
        )


def test_coh_t007_all_frozen_identities_match_golden_vectors() -> None:
    identities = PROFILE["identity_derivations"]
    for vector_name in ("transaction_key", "settlement_key"):
        vector = VECTORS[vector_name]
        identity = identities[vector_name]
        assert (
            canonical_json_bytes(vector["components"]).decode() == vector["expected_canonical_json"]
        )
        assert (
            derive_contract_id(identity["prefix"], vector["components"]) == vector["expected_key"]
        )

    chain = VECTORS["policy_manifest_proof_case_chain"]
    proof = chain["proof"]
    proof_identity = identities["proof_id"]
    proof_components = {field: proof[field] for field in proof_identity["fields"]}
    assert (
        derive_contract_id(proof_identity["prefix"], proof_components) == chain["expected_proof_id"]
    )
    case = chain["case_revision_one"]
    case_identity = identities["case_id"]
    case_components = {field: case[field] for field in case_identity["fields"]}
    assert derive_contract_id(case_identity["prefix"], case_components) == chain["expected_case_id"]


def test_coh_t008_manifest_families_bind_exact_active_contract_ids() -> None:
    active = json.loads((ROOT / "contracts/active-contract-set-v1.json").read_text())
    by_family = {item["family"]: item["id"] for item in active["contracts"]}
    assert PROFILE["manifest_family_contracts"] == {
        "PROCESSOR_EVENTS": by_family["PROCESSOR_EVENT"],
        "PROCESSOR_SETTLEMENTS": by_family["PROCESSOR_SETTLEMENT"],
        "LEDGER_JOURNALS": by_family["LEDGER_JOURNAL"],
        "BANK_ENTRIES": by_family["BANK_ENTRY"],
    }


def test_coh_t009_binding_chain_is_validated_by_the_independent_oracle() -> None:
    result = reproduce_stage3(ROOT)
    assert result["stage"] == 3
    assert result["stage_state"] == "PART1_CONTRACT_COHERENCE_VALIDATED"
    assert result["aws_execution"] is False


def test_coh_t010_every_active_reference_fragment_resolves() -> None:
    result = reproduce_stage3(ROOT)
    evidence = json.loads((ROOT / "evidence/part1-stage3-local.json").read_text())
    assert evidence["local_validation"]["reference_fragment_count"] == 131
    assert len(result["active_schema_digests"]) == 9


def test_coh_t011_cross_contract_domains_are_exact_sets() -> None:
    common = json.loads((ROOT / "contracts/v2/common-v2.schema.json").read_text())["$defs"]
    semantics = json.loads((ROOT / "spec/financial-semantics-v1.json").read_text())
    assert set(common["supportedCurrency"]["enum"]) == set(
        semantics["money"]["supported_currency_exponents"]
    )
    assert set(common["eventType"]["enum"]) == set(semantics["transaction"]["processor_sign"])
    assert set(common["financialReason"]["enum"]) == set(
        semantics["failure_ownership"]["FINANCIAL_EXCEPTION"]
    )


def test_coh_t012_case_revision_two_binds_the_immediate_predecessor_digest() -> None:
    chain = VECTORS["policy_manifest_proof_case_chain"]
    first = chain["case_revision_one"]
    second = chain["case_revision_two"]
    scope = set(PROFILE["digest_scopes"]["case_revision_sha256"]["exclude"])
    first_digest = canonical_sha256(first, excluded_fields=scope, timestamp_fields=TIMESTAMP_FIELDS)
    assert second["prior_case_revision_id"] == first_digest
    assert second["revision"] == first["revision"] + 1


def test_binding_chain_mutation_changes_the_bound_digest() -> None:
    chain = VECTORS["policy_manifest_proof_case_chain"]
    policy = deepcopy(chain["policy"])
    original = canonical_sha256(policy, excluded_fields={"policy_sha256"})
    policy["currency_rules"]["INR"]["transaction_tolerance_minor"] = 1
    assert canonical_sha256(policy, excluded_fields={"policy_sha256"}) != original
