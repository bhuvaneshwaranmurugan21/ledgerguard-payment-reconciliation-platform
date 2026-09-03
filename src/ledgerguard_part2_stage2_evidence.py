"""Evidence and semantic-mutation helpers for Part 2 Stage 2."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any

from ledgerguard_reference_oracle import (
    AdmissionRejected,
    business_digest,
    canonical_sha256,
    checked_add,
    evaluate_capture_capacity,
    evaluate_settlement,
    evaluate_transaction,
    expected_failure_outcome,
    transaction_key,
)


def parse_junit_counts(report: Path) -> dict[str, int]:
    """Aggregate direct JUnit suites without double-counting wrapper totals."""

    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("./testsuite"))
    if not suites:
        raise ValueError("JUnit report contains no test suites")
    counts = {
        name: sum(int(suite.attrib.get(name, 0)) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }
    if counts["tests"] < counts["failures"] + counts["errors"] + counts["skipped"]:
        raise ValueError("JUnit report counts are inconsistent")
    return counts


def run_mutation_checks(root: Path) -> dict[str, Any]:
    """Prove that each registered semantic defect changes a required outcome."""

    examples = json.loads((root / "spec/financial-examples-v1.json").read_text())
    vectors = json.loads((root / "spec/contract-coherence-vectors-v1.json").read_text())
    checks: dict[str, bool] = {}

    refund = examples["transaction_cases"][1]
    checks["TRANSACTION_SIGN_REVERSAL"] = (
        evaluate_transaction(refund["input"])["processor_minor"]
        != refund["input"]["processor_amount_minor"]
    )

    formula = examples["settlement_cases"][4]
    checks["TRUST_REPORTED_SETTLEMENT_NET"] = (
        evaluate_settlement(formula["input"])["processor_net_minor"]
        != formula["input"]["reported_net_minor"]
    )

    components = vectors["transaction_key"]["components"]
    changed_class = dict(components, event_class="REFUND")
    checks["DROP_TRANSACTION_EVENT_CLASS"] = transaction_key(components) != transaction_key(
        changed_class
    )

    digest_vector = vectors["source_digest"]
    replay = dict(digest_vector["record"], **digest_vector["equivalent_redelivery"])
    checks["INCLUDE_TRANSPORT_DIGEST_FIELDS"] = business_digest(replay) == digest_vector[
        "expected_sha256"
    ] and canonical_sha256(replay) != canonical_sha256(digest_vector["record"])

    negative_chain = deepcopy(examples["transaction_cases"][1]["input"])
    negative_chain["reference_targets_negative"] = True
    checks["ALLOW_NEGATIVE_REFERENCE_CHAIN"] = (
        "UNRESOLVED_REFERENCE" in evaluate_transaction(negative_chain)["reason_codes"]
    )

    capacity = examples["capture_capacity_case"]
    checks["DISABLE_CAPTURE_CAPACITY"] = evaluate_capture_capacity(
        capacity["captured_minor"], capacity["negative_applied_minor"]
    )["reason_codes"] == ["OVER_APPLIED_REFERENCE"]

    unknown = examples["settlement_cases"][5]
    checks["HEURISTIC_BANK_ALLOCATION"] = (
        evaluate_settlement(unknown["input"])["allocated_bank_count"] == 0
    )

    duplicate = deepcopy(examples["settlement_cases"][0]["input"])
    duplicate["bank_entries"].append(deepcopy(duplicate["bank_entries"][0]))
    duplicate_result = evaluate_settlement(duplicate)
    checks["ALLOW_BANK_DOUBLE_USE"] = (
        duplicate_result["bank_minor"] == 80_000
        and "DUPLICATE_BANK_MOVEMENT" in duplicate_result["reason_codes"]
    )

    missing = deepcopy(examples["transaction_cases"][0]["input"])
    missing.update(processor_amount_minor=0, ledger_amount_minor=0, processor_record_count=0)
    checks["COLLAPSE_MISSING_TO_ZERO"] = evaluate_transaction(missing)["reason_codes"] == [
        "MISSING_PROCESSOR_ACTIVITY"
    ]

    high_tolerance = deepcopy(formula["input"])
    high_tolerance["tolerance_minor"] = 2**63 - 1
    checks["TOLERATE_SEMANTIC_FAILURE"] = (
        evaluate_settlement(high_tolerance)["status"] == "EXCEPTION"
    )

    try:
        checked_add(2**63 - 1, 1)
    except AdmissionRejected:
        checks["UNCHECKED_INTEGER_AGGREGATION"] = True
    else:
        checks["UNCHECKED_INTEGER_AGGREGATION"] = False

    checks["FINALIZE_PROOF_AFTER_FAILURE"] = (
        expected_failure_outcome("EXECUTION", "EXECUTION_FAILURE")["authoritative_proof"] is False
    )

    expected = json.loads((root / "spec/part2-stage2-oracle-vectors-v1.json").read_text())[
        "mutation_classes"
    ]
    if list(checks) != expected:
        raise ValueError("mutation registry and execution order differ")
    survivors = [name for name, killed in checks.items() if not killed]
    if survivors:
        raise ValueError(f"Stage 2 semantic mutants survived: {survivors}")
    return {"checks": len(checks), "survivors": 0, "killed": list(checks)}
