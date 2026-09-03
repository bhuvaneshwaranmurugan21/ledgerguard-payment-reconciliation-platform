from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import ledgerguard_reference_oracle.canonical as canonical_module
import ledgerguard_reference_oracle.oracle as oracle_module
from ledgerguard_part2_stage2 import Stage2Error, validate_stage2
from ledgerguard_part2_stage2_evidence import parse_junit_counts, run_mutation_checks
from ledgerguard_reference_oracle import (
    AdmissionRejected,
    business_digest,
    canonical_json_bytes,
    canonical_sha256,
    canonical_timestamp,
    case_id,
    checked_abs,
    checked_add,
    checked_i64,
    checked_subtract,
    classify_replay,
    evaluate_capture_capacity,
    evaluate_settlement,
    evaluate_transaction,
    expected_failure_outcome,
    next_revision,
    parse_strict_json,
    proof_id,
    settlement_key,
    source_identity,
    transaction_key,
    validate_journal,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads((ROOT / "spec/financial-examples-v1.json").read_text())
VECTORS = json.loads((ROOT / "spec/contract-coherence-vectors-v1.json").read_text())


def _copy(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"),
    )
    return destination


def _mutate_json(root: Path, relative: str, callback: Callable[[dict[str, Any]], None]) -> None:
    path = root / relative
    value = json.loads(path.read_text())
    callback(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def test_p2s2_t001_candidate_is_complete_and_deterministic() -> None:
    first = validate_stage2(ROOT)
    second = validate_stage2(ROOT)
    assert first == second
    assert first["stage_state"] == "PART2_STAGE2_REFERENCE_ORACLE_VERIFIED_CANDIDATE"
    assert first["stage1_baseline"] == {
        "commit": "95b7e2a1c6a1dd758a8ce43c73bdea80117b6d91",
        "tree": "668e2e89473b026d9857d162fb9e45a3c8f465a1",
        "parent": "3ef17666e3fe3bc655ba1c8733beb3cb00acdbec",
    }
    assert first["oracle"]["frozen_examples"] == 11
    assert first["oracle"]["invariants"] == 18
    assert first["oracle"]["scenarios"] == 21
    assert first["oracle"]["authoritative_proofs_emitted"] == 0
    assert first["aws_execution"] is False


@pytest.mark.parametrize("case", EXAMPLES["transaction_cases"], ids=lambda row: row["name"])
def test_p2s2_t002_frozen_transaction_examples(case: dict[str, Any]) -> None:
    assert evaluate_transaction(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", EXAMPLES["settlement_cases"], ids=lambda row: row["name"])
def test_p2s2_t003_frozen_settlement_examples(case: dict[str, Any]) -> None:
    assert evaluate_settlement(case["input"]) == case["expected"]


def test_p2s2_t004_checked_int64_boundaries_fail_closed() -> None:
    assert checked_i64(-(2**63)) == -(2**63)
    assert checked_i64(2**63 - 1) == 2**63 - 1
    assert checked_add(2**63 - 1, 0) == 2**63 - 1
    assert checked_subtract(-(2**63), 0) == -(2**63)
    for operation, values in (
        (checked_i64, (True,)),
        (checked_i64, (1.0,)),
        (checked_i64, (2**63,)),
        (checked_i64, (-(2**63) - 1,)),
        (checked_add, (2**63 - 1, 1)),
        (checked_subtract, (-(2**63), 1)),
        (checked_abs, (-(2**63),)),
    ):
        with pytest.raises(AdmissionRejected, match="SCHEMA_VIOLATION"):
            operation(*values)


def test_p2s2_t005_canonical_source_digest_and_replay_goldens() -> None:
    vector = VECTORS["source_digest"]
    assert (
        canonical_json_bytes(
            {
                key: value
                for key, value in vector["record"].items()
                if key not in {"payload_sha256", "received_at", "source_batch_id"}
            }
        ).decode()
        == vector["expected_canonical_json"]
    )
    assert business_digest(vector["record"]) == vector["expected_sha256"]
    replay = dict(vector["record"], **vector["equivalent_redelivery"])
    conflict = dict(vector["record"], **vector["conflicting_redelivery"])
    assert classify_replay("PROCESSOR_EVENT", vector["record"], replay) == "IDENTICAL_REPLAY"
    assert classify_replay("PROCESSOR_EVENT", vector["record"], conflict) == "IDENTITY_CONFLICT"
    assert source_identity("PROCESSOR_EVENT", vector["record"]) == (
        "PROCESSOR_EVENT",
        "processor-a",
        "capture-1",
    )


def test_p2s2_t006_strict_json_and_timestamp_vectors() -> None:
    for row in VECTORS["timestamp_vectors"]:
        assert canonical_timestamp(row["input"]) == row["expected"]
    for value in VECTORS["invalid_timestamps"]:
        with pytest.raises(AdmissionRejected):
            canonical_timestamp(value)
    for value in VECTORS["invalid_json_numbers"]:
        with pytest.raises(AdmissionRejected):
            parse_strict_json('{"value":' + value + "}")
    with pytest.raises(AdmissionRejected, match="duplicate JSON key"):
        parse_strict_json('{"x":1,"x":2}')
    with pytest.raises(AdmissionRejected, match="NFC key collision"):
        parse_strict_json('{"é":1,"é":2}')
    with pytest.raises(AdmissionRejected, match="UTF-8 BOM"):
        parse_strict_json('\ufeff{"x":1}')


def test_p2s2_t007_all_derived_identity_goldens() -> None:
    assert (
        transaction_key(VECTORS["transaction_key"]["components"])
        == VECTORS["transaction_key"]["expected_key"]
    )
    assert (
        settlement_key(VECTORS["settlement_key"]["components"])
        == VECTORS["settlement_key"]["expected_key"]
    )
    chain = VECTORS["policy_manifest_proof_case_chain"]
    proof = chain["proof"]
    assert (
        proof_id(
            {
                key: proof[key]
                for key in (
                    "grain",
                    "reconciliation_key",
                    "revision",
                    "source_manifest_sha256",
                    "policy_sha256",
                )
            }
        )
        == chain["expected_proof_id"]
    )
    case = chain["case_revision_one"]
    assert (
        case_id(
            {
                key: case[key]
                for key in ("grain", "reconciliation_key", "initial_exception_proof_id")
            }
        )
        == chain["expected_case_id"]
    )


def test_p2s2_t008_all_binding_chain_digest_goldens() -> None:
    chain = VECTORS["policy_manifest_proof_case_chain"]
    for value_name, digest_field, expected_name in (
        ("policy", "policy_sha256", "expected_policy_sha256"),
        ("manifest", "manifest_sha256", "expected_manifest_sha256"),
        ("proof", "proof_sha256", "expected_proof_sha256"),
        ("case_revision_one", "case_revision_sha256", "expected_case_revision_one_sha256"),
        ("case_revision_two", "case_revision_sha256", "expected_case_revision_two_sha256"),
    ):
        assert canonical_sha256(chain[value_name], {digest_field}) == chain[expected_name]


def test_p2s2_t009_reference_capacity_and_revision_expectations() -> None:
    capacity = EXAMPLES["capture_capacity_case"]
    assert (
        evaluate_capture_capacity(capacity["captured_minor"], capacity["negative_applied_minor"])
        == capacity["expected"]
    )
    assert evaluate_capture_capacity(10_000, 10_000) == {
        "remaining_capacity_minor": 0,
        "status": "VALID",
        "reason_codes": [],
    }
    assert next_revision(1, "a" * 64) == {"revision": 2, "prior_revision_sha256": "a" * 64}


def test_p2s2_t010_journal_admission_and_wrong_role_are_distinct() -> None:
    valid = {
        "processor": "processor-a",
        "entry_type": "CAPTURE",
        "currency": "INR",
        "payment_id": "payment-1",
        "postings": [
            {
                "line_id": "1",
                "account_role": "PROCESSOR_CLEARING",
                "side": "DEBIT",
                "amount_minor": 100,
            },
            {
                "line_id": "2",
                "account_role": "MERCHANT_PAYABLE",
                "side": "CREDIT",
                "amount_minor": 100,
            },
        ],
    }
    assert validate_journal(valid)["financial_reason_codes"] == []
    wrong_role = deepcopy(valid)
    wrong_role["postings"][0]["account_role"] = "BANK_CASH"
    assert validate_journal(wrong_role)["financial_reason_codes"] == ["INVALID_ACCOUNT_ROLE"]
    unbalanced = deepcopy(valid)
    unbalanced["postings"][1]["amount_minor"] = 99
    with pytest.raises(AdmissionRejected, match="UNBALANCED_JOURNAL"):
        validate_journal(unbalanced)


def test_p2s2_t011_exact_allocation_is_permutation_invariant() -> None:
    case = EXAMPLES["settlement_cases"][0]
    permuted = deepcopy(case["input"])
    permuted["bank_entries"].reverse()
    assert evaluate_settlement(permuted) == case["expected"]
    changed_case = deepcopy(case["input"])
    changed_case["bank_entries"][0]["settlement_reference"] = "Settlement-1"
    result = evaluate_settlement(changed_case)
    assert result["allocated_bank_count"] == 1
    assert result["unallocated_bank_count"] == 1
    assert "UNALLOCATED_BANK_MOVEMENT" in result["reason_codes"]


def test_p2s2_t012_tolerance_never_hides_semantic_failure() -> None:
    formula = deepcopy(EXAMPLES["settlement_cases"][4]["input"])
    formula["tolerance_minor"] = 2**63 - 1
    assert evaluate_settlement(formula)["status"] == "EXCEPTION"
    wrong_role = deepcopy(EXAMPLES["transaction_cases"][2]["input"])
    wrong_role["tolerance_minor"] = 2**63 - 1
    assert evaluate_transaction(wrong_role)["status"] == "EXCEPTION"


def test_p2s2_t013_missing_evidence_is_not_collapsed_to_zero() -> None:
    transaction = deepcopy(EXAMPLES["transaction_cases"][0]["input"])
    transaction.update(processor_amount_minor=0, ledger_amount_minor=0, processor_record_count=0)
    result = evaluate_transaction(transaction)
    assert result["status"] == "EXCEPTION"
    assert result["reason_codes"] == ["MISSING_PROCESSOR_ACTIVITY"]
    zero_settlement = EXAMPLES["settlement_cases"][1]
    assert evaluate_settlement(zero_settlement["input"]) == zero_settlement["expected"]


def test_p2s2_t014_failure_ownership_never_emits_partial_authority() -> None:
    assert expected_failure_outcome("ADMISSION", "SCHEMA_VIOLATION")["authoritative_proof"] is False
    assert expected_failure_outcome("EXECUTION", "EXECUTION_FAILURE") == {
        "outcome": "NO_AUTHORITATIVE_PARTIAL_PROOF",
        "authoritative_proof": False,
        "reason_codes": ["EXECUTION_FAILURE"],
    }
    assert expected_failure_outcome("FINANCIAL", "INVALID_ACCOUNT_ROLE")["outcome"] == (
        "EXCEPTION_PROOF_EXPECTED"
    )


def test_p2s2_t015_ambiguous_allocation_rejects_without_proof() -> None:
    ambiguous = EXAMPLES["ambiguous_bank_allocation_case"]
    source = deepcopy(EXAMPLES["settlement_cases"][0]["input"])
    source["settlement_reference"] = ambiguous["bank_reference"]
    source["candidate_settlement_references"] = ambiguous["candidate_settlement_references"]
    assert evaluate_settlement(source) == {
        "outcome": "ADMISSION_REJECTED",
        "authoritative_proof": False,
        "reason_codes": ["AMBIGUOUS_BANK_ALLOCATION"],
    }


def test_p2s2_t016_duplicate_bank_identity_is_not_double_counted() -> None:
    source = deepcopy(EXAMPLES["settlement_cases"][0]["input"])
    source["bank_entries"].append(deepcopy(source["bank_entries"][0]))
    result = evaluate_settlement(source)
    assert result["bank_minor"] == 80_000
    assert result["allocated_bank_count"] == 2
    assert "DUPLICATE_BANK_MOVEMENT" in result["reason_codes"]


def test_p2s2_t017_oracle_import_boundary_is_enforced(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    path = root / "src/ledgerguard_reference_oracle/oracle.py"
    path.write_text("import pyspark\n" + path.read_text())
    with pytest.raises(Stage2Error, match="forbidden runtime"):
        validate_stage2(root)


def test_p2s2_t018_production_reverse_import_is_enforced(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    path = root / "src/ledgerguard/__init__.py"
    path.write_text(path.read_text() + "\nimport ledgerguard_reference_oracle\n")
    with pytest.raises(Stage2Error, match="production imports"):
        validate_stage2(root)


def test_p2s2_t019_authority_mutation_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    path = root / "spec/financial-semantics-v1.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(Stage2Error, match="authority digest differs"):
        validate_stage2(root)


def test_p2s2_t020_non_owned_master_gate_claim_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "contracts/part2-stage2-reference-oracle-v1.json",
        lambda value: value["master_part2_completion_gates"].update(
            {"spark_parity_verified": "PASS"}
        ),
    )
    with pytest.raises(Stage2Error, match="non-Stage-2 master gate claimed"):
        validate_stage2(root)


def test_p2s2_t021_traceability_gap_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage2-traceability-v1.json",
        lambda value: value["traceability"].pop(),
    )
    with pytest.raises(Stage2Error, match="traceability inventory differs"):
        validate_stage2(root)


def test_p2s2_t022_all_targeted_mutation_classes_are_owned() -> None:
    vectors = json.loads((ROOT / "spec/part2-stage2-oracle-vectors-v1.json").read_text())
    assert vectors["mutation_classes"] == [
        "TRANSACTION_SIGN_REVERSAL",
        "TRUST_REPORTED_SETTLEMENT_NET",
        "DROP_TRANSACTION_EVENT_CLASS",
        "INCLUDE_TRANSPORT_DIGEST_FIELDS",
        "ALLOW_NEGATIVE_REFERENCE_CHAIN",
        "DISABLE_CAPTURE_CAPACITY",
        "HEURISTIC_BANK_ALLOCATION",
        "ALLOW_BANK_DOUBLE_USE",
        "COLLAPSE_MISSING_TO_ZERO",
        "TOLERATE_SEMANTIC_FAILURE",
        "UNCHECKED_INTEGER_AGGREGATION",
        "FINALIZE_PROOF_AFTER_FAILURE",
    ]


def test_p2s2_t023_canonical_defensive_paths_fail_closed() -> None:
    assert parse_strict_json('{"ok":[true,null,1]}') == {"ok": [True, None, 1]}
    with pytest.raises(AdmissionRejected, match="SCHEMA_VIOLATION"):
        parse_strict_json("{")
    for value, message in (
        ("\ud800", "surrogate"),
        (1.0, "floating-point"),
        ({1: "value"}, "non-string"),
        ({"é": 1, "é": 2}, "NFC key collision"),
        ({1, 2}, "unsupported value"),
    ):
        with pytest.raises(AdmissionRejected, match=message):
            canonical_json_bytes(value)
    with pytest.raises(AdmissionRejected, match="unknown source family"):
        source_identity("UNKNOWN", {})
    with pytest.raises(AdmissionRejected, match="missing processor"):
        source_identity("PROCESSOR_EVENT", {"source_record_id": "record"})
    first = VECTORS["source_digest"]["record"]
    second = dict(first, source_record_id="capture-2")
    assert classify_replay("PROCESSOR_EVENT", first, second) == "DISTINCT_IDENTITY"


def test_p2s2_t024_transaction_defensive_and_mismatch_paths() -> None:
    base = deepcopy(EXAMPLES["transaction_cases"][0]["input"])
    mutations = [
        ("event_type", "UNKNOWN", "SCHEMA_VIOLATION"),
        ("processor_currency", "EUR", "SCHEMA_VIOLATION"),
        ("ledger_currency", "EUR", "SCHEMA_VIOLATION"),
        ("ledger_side", "LEFT", "SCHEMA_VIOLATION"),
        ("tolerance_minor", -1, "POLICY_MISMATCH"),
    ]
    for field, value, reason in mutations:
        source = dict(base, **{field: value})
        assert evaluate_transaction(source)["reason_codes"] == [reason]
    missing_text = dict(base)
    missing_text.pop("event_type")
    assert evaluate_transaction(missing_text)["reason_codes"] == ["SCHEMA_VIOLATION"]
    capture_reference = dict(base, has_reference=True)
    assert evaluate_transaction(capture_reference)["reason_codes"] == ["UNRESOLVED_REFERENCE"]
    over_applied = deepcopy(EXAMPLES["transaction_cases"][1]["input"])
    over_applied["over_applied_reference"] = True
    assert evaluate_transaction(over_applied)["reason_codes"] == ["OVER_APPLIED_REFERENCE"]
    both_missing = dict(base, processor_record_count=0, ledger_journal_count=0)
    assert evaluate_transaction(both_missing)["reason_codes"] == [
        "MISSING_LEDGER_MOVEMENT",
        "MISSING_PROCESSOR_ACTIVITY",
    ]
    mismatch = dict(base, ledger_amount_minor=99)
    assert evaluate_transaction(mismatch)["reason_codes"] == ["PROCESSOR_LEDGER_MISMATCH"]


def test_p2s2_t025_internal_status_and_reason_guards() -> None:
    with pytest.raises(oracle_module.OracleError, match="unknown financial"):
        oracle_module._reason_list({"NOT_A_REASON"})
    with pytest.raises(oracle_module.OracleError, match="above tolerance"):
        oracle_module._status(2, 1, set())
    with pytest.raises(AdmissionRejected, match="SCHEMA_VIOLATION"):
        oracle_module.checked_nonnegative(-1)
    with pytest.raises(oracle_module.OracleError, match="unknown failure owner"):
        expected_failure_outcome("UNKNOWN", "EXECUTION_FAILURE")
    with pytest.raises(oracle_module.OracleError, match="previous digest"):
        next_revision(1, "short")
    with pytest.raises(oracle_module.OracleError, match="previous digest"):
        next_revision(1, "g" * 64)


def test_p2s2_t026_settlement_admission_defensive_paths() -> None:
    base = deepcopy(EXAMPLES["settlement_cases"][0]["input"])
    cases: list[tuple[dict[str, Any], str]] = []
    cases.append((dict(base, ledger_side="LEFT"), "SCHEMA_VIOLATION"))
    cases.append((dict(base, settlement_reference=" "), "SCHEMA_VIOLATION"))
    cases.append((dict(base, candidate_settlement_references="not-a-list"), "SCHEMA_VIOLATION"))
    cases.append((dict(base, candidate_settlement_references=[]), "AMBIGUOUS_BANK_ALLOCATION"))
    cases.append((dict(base, permitted_bank_account_ids="not-a-list"), "POLICY_MISMATCH"))
    cases.append((dict(base, bank_entries="not-a-list"), "SCHEMA_VIOLATION"))
    cases.append((dict(base, bank_entries=[1]), "SCHEMA_VIOLATION"))
    missing_identity = deepcopy(base)
    missing_identity["bank_entries"][0].pop("bank_record_id")
    cases.append((missing_identity, "SCHEMA_VIOLATION"))
    invalid_direction = deepcopy(base)
    invalid_direction["bank_entries"][0]["direction"] = "LEFT"
    cases.append((invalid_direction, "SCHEMA_VIOLATION"))
    for source, reason in cases:
        assert evaluate_settlement(source)["reason_codes"] == [reason]


def test_p2s2_t027_settlement_financial_reason_and_delta_paths() -> None:
    base = deepcopy(EXAMPLES["settlement_cases"][0]["input"])
    invalid_account = deepcopy(base)
    invalid_account["bank_entries"][0]["bank_account_id"] = "blocked"
    assert "INVALID_BANK_ACCOUNT" in evaluate_settlement(invalid_account)["reason_codes"]

    missing_processor = dict(base, processor_settlement_count=0)
    assert "MISSING_PROCESSOR_ACTIVITY" in evaluate_settlement(missing_processor)["reason_codes"]

    missing_ledger = dict(base, ledger_journal_count=0, ledger_side=None, ledger_amount_minor=0)
    assert "MISSING_LEDGER_MOVEMENT" in evaluate_settlement(missing_ledger)["reason_codes"]

    processor_ledger = dict(base, ledger_amount_minor=79_999, tolerance_minor=0)
    assert evaluate_settlement(processor_ledger)["reason_codes"] == [
        "PROCESSOR_LEDGER_MISMATCH",
        "LEDGER_BANK_MISMATCH",
    ]

    processor_bank = deepcopy(base)
    processor_bank["bank_entries"][1]["amount_minor"] = 29_999
    assert evaluate_settlement(processor_bank)["reason_codes"] == [
        "PROCESSOR_BANK_MISMATCH",
        "LEDGER_BANK_MISMATCH",
    ]

    equal_ledger_bank = deepcopy(base)
    equal_ledger_bank["ledger_amount_minor"] = 79_999
    equal_ledger_bank["bank_entries"][1]["amount_minor"] = 29_999
    assert evaluate_settlement(equal_ledger_bank)["reason_codes"] == [
        "PROCESSOR_LEDGER_MISMATCH",
        "PROCESSOR_BANK_MISMATCH",
    ]

    all_mismatch = deepcopy(base)
    all_mismatch["ledger_amount_minor"] = 79_998
    all_mismatch["bank_entries"][1]["amount_minor"] = 29_999
    assert evaluate_settlement(all_mismatch)["reason_codes"] == [
        "PROCESSOR_LEDGER_MISMATCH",
        "PROCESSOR_BANK_MISMATCH",
        "LEDGER_BANK_MISMATCH",
    ]


def test_p2s2_t028_journal_defensive_paths() -> None:
    valid = {
        "processor": "processor-a",
        "entry_type": "SETTLEMENT",
        "currency": "INR",
        "settlement_id": "settlement-1",
        "settlement_cycle": "2026-09-01",
        "postings": [
            {
                "line_id": "1",
                "account_role": "PROCESSOR_CLEARING",
                "side": "DEBIT",
                "amount_minor": 100,
            },
            {
                "line_id": "2",
                "account_role": "BANK_CASH",
                "side": "CREDIT",
                "amount_minor": 100,
            },
        ],
    }
    assert validate_journal(valid)["admitted"] is True
    invalid_rows: list[tuple[dict[str, Any], str]] = []
    invalid_rows.append((dict(valid, processor=""), "SCHEMA_VIOLATION"))
    invalid_rows.append((dict(valid, postings=[]), "UNBALANCED_JOURNAL"))
    invalid_rows.append((dict(valid, postings=[1, 2]), "UNBALANCED_JOURNAL"))
    duplicate_line = deepcopy(valid)
    duplicate_line["postings"][1]["line_id"] = "1"
    invalid_rows.append((duplicate_line, "UNBALANCED_JOURNAL"))
    zero_amount = deepcopy(valid)
    zero_amount["postings"][0]["amount_minor"] = 0
    invalid_rows.append((zero_amount, "UNBALANCED_JOURNAL"))
    invalid_side = deepcopy(valid)
    invalid_side["postings"][0]["side"] = "LEFT"
    invalid_rows.append((invalid_side, "UNBALANCED_JOURNAL"))
    mixed_currency = deepcopy(valid)
    mixed_currency["postings"][0]["currency"] = "USD"
    invalid_rows.append((mixed_currency, "UNBALANCED_JOURNAL"))
    both_keys = dict(valid, payment_id="payment-1")
    invalid_rows.append((both_keys, "UNBALANCED_JOURNAL"))
    no_keys = deepcopy(valid)
    no_keys.pop("settlement_id")
    no_keys.pop("settlement_cycle")
    invalid_rows.append((no_keys, "UNBALANCED_JOURNAL"))
    for journal, reason in invalid_rows:
        with pytest.raises(AdmissionRejected, match=reason):
            validate_journal(journal)


def test_p2s2_t029_canonical_normalization_handles_all_json_types() -> None:
    value = {
        "z": [None, True, 1, "é"],
        "created_at": "2026-09-01T01:00:00.120000Z",
        "nested": {"b": 2, "a": 1},
    }
    assert canonical_json_bytes(value).decode() == (
        '{"created_at":"2026-09-01T01:00:00.12Z","nested":{"a":1,"b":2},"z":[null,true,1,"é"]}'
    )
    assert canonical_module.canonical_sha256({"x": 1}) == canonical_module.canonical_sha256(
        {"x": 1}, set()
    )


def test_p2s2_t030_all_semantic_mutants_are_killed() -> None:
    result = run_mutation_checks(ROOT)
    assert result["checks"] == 12
    assert result["survivors"] == 0
    assert len(result["killed"]) == 12


def test_p2s2_t031_ci_evidence_schema_is_closed() -> None:
    schema = json.loads((ROOT / "spec/part2-stage2-ci-evidence-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    valid = {
        "schema_version": "1.0",
        "repository": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
        "commit_sha": "a" * 40,
        "checked_out_sha": "a" * 40,
        "base_sha": "b" * 40,
        "workflow_run_id": "1",
        "workflow_run_attempt": "1",
        "pull_request_number": 11,
        "pull_request_draft": True,
        "python_version": "3.11.13",
        "clean_run_count": 2,
        "deterministic_equal": True,
        "deterministic_payload_sha256": "c" * 64,
        "stage2_candidate_digest": "d" * 64,
        "wheel_sha256": "e" * 64,
        "test_counts": {"tests": 300, "failures": 0, "errors": 0, "skipped": 0},
        "coverage_percent": 100.0,
        "mutation_checks": 12,
        "mutation_survivors": 0,
        "aws_execution": False,
        "aws_api_called": False,
        "aws_workflow_dispatched": False,
        "infrastructure_mutation": False,
        "production_reconciliation_executed": False,
        "authoritative_proof_persisted": False,
        "merge_authorized": False,
    }
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(valid)) == []
    for field in (
        "aws_execution",
        "aws_api_called",
        "aws_workflow_dispatched",
        "infrastructure_mutation",
        "production_reconciliation_executed",
        "authoritative_proof_persisted",
        "merge_authorized",
    ):
        missing = dict(valid)
        missing.pop(field)
        assert list(validator.iter_errors(missing))
        contradicted = dict(valid)
        contradicted[field] = True
        assert list(validator.iter_errors(contradicted))
    valid["unknown"] = True
    assert list(validator.iter_errors(valid))


def test_p2s2_t032_junit_counts_do_not_double_count(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuites tests="999"><testsuite tests="3" failures="1" errors="0" skipped="1"/>'
        '<testsuite tests="2" failures="0" errors="1" skipped="0"/></testsuites>'
    )
    assert parse_junit_counts(report) == {"tests": 5, "failures": 1, "errors": 1, "skipped": 1}


def test_p2s2_t033_unhashed_or_nonminimal_lock_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    lock = root / "requirements/part2-stage2-py311.lock"
    lock.write_text(lock.read_text() + "\npyspark==3.5.6 --hash=sha256:" + "a" * 64 + "\n")
    with pytest.raises(Stage2Error, match="not minimal"):
        validate_stage2(root)


def test_p2s2_t034_candidate_rejects_premature_part_completion(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    status = root / "PROJECT_STATUS.md"
    status.write_text(status.read_text() + "\nLOCAL_RECONCILIATION_VERIFIED\n")
    with pytest.raises(Stage2Error, match="completion claimed early"):
        validate_stage2(root)
