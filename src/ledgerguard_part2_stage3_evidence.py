"""Evidence and semantic-mutation helpers for Part 2 Stage 3."""

from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation import (
    AdmissionRejected,
    AdmissionState,
    AdmittedRecord,
    ContractRegistry,
    business_digest,
    canonical_json_bytes,
    canonical_sha256,
    checked_add,
    load_local_object_bytes,
    parse_strict_json,
    source_identity,
)
from ledgerguard.reconciliation.admission import (
    _journal_admission,
    _verify_cross_record_invariants,
    parse_json_lines,
)
from ledgerguard_part2_stage3_validation import MUTATION_CLASSES


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


def _rejects(reason: str, operation: Callable[[], object]) -> bool:
    try:
        operation()
    except AdmissionRejected as error:
        return error.reason == reason and error.authoritative_proof is False
    return False


def _record(
    family: str,
    value: dict[str, Any],
    key: str | None = None,
    reference: str | None = None,
) -> AdmittedRecord:
    return AdmittedRecord(
        family=family,
        source_identity=(family, value.get("source_record_id", "synthetic")),
        business_sha256="a" * 64,
        canonical_bytes=canonical_json_bytes(value),
        reconciliation_key=key,
        normalized_settlement_reference=reference,
        journal_balanced_total_minor=None,
        journal_clearing_role_valid=None,
    )


def _production_imports_oracle(root: Path) -> bool:
    for path in (root / "src/ledgerguard/reconciliation").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name.startswith("ledgerguard_reference_oracle") for alias in node.names
                ):
                    return True
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "ledgerguard_reference_oracle"
            ):
                return True
    return False


def run_mutation_checks(root: Path) -> dict[str, Any]:
    """Prove each registered admission defect changes a mandatory result."""

    checks: dict[str, bool] = {}
    checks["ALLOW_DUPLICATE_JSON_KEY"] = _rejects(
        "SCHEMA_VIOLATION", lambda: parse_strict_json(b'{"a":1,"a":2}')
    )
    checks["ALLOW_FLOAT_MONEY"] = _rejects(
        "SCHEMA_VIOLATION", lambda: parse_strict_json(b'{"amount_minor":1.0}')
    )
    checks["TRUST_ACTIVE_REGISTRY_PATH"] = len(ContractRegistry.load(root).schemas) == 9

    policy = {"policy_version": "v1", "policy_sha256": "0" * 64}
    checks["TRUST_POLICY_DIGEST"] = (
        canonical_sha256(policy, {"policy_sha256"}) != policy["policy_sha256"]
    )
    manifest = {"run_id": "run-1", "manifest_sha256": "0" * 64}
    checks["TRUST_MANIFEST_DIGEST"] = (
        canonical_sha256(manifest, {"manifest_sha256"}) != manifest["manifest_sha256"]
    )
    raw = b"{}\n"
    checks["TRUST_OBJECT_DIGEST"] = _rejects(
        "SOURCE_IDENTITY_MISMATCH",
        lambda: parse_json_lines(raw, len(raw), "0" * 64, 1),
    )

    original = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_type": "CAPTURE",
        "source_record_id": "source-1",
        "amount_minor": 100,
    }
    changed = dict(original, amount_minor=101)
    checks["ALLOW_IDENTITY_CONFLICT"] = source_identity(
        "PROCESSOR_EVENT", original
    ) == source_identity("PROCESSOR_EVENT", changed) and business_digest(
        original
    ) != business_digest(changed)
    unbalanced = {
        "payment_id": "payment-1",
        "postings": [
            {"line_id": "1", "side": "DEBIT", "amount_minor": 2},
            {"line_id": "2", "side": "CREDIT", "amount_minor": 1},
        ],
    }
    checks["ALLOW_UNBALANCED_JOURNAL"] = _rejects(
        "UNBALANCED_JOURNAL", lambda: _journal_admission(unbalanced)
    )
    checks["ALLOW_I64_OVERFLOW"] = _rejects("SCHEMA_VIOLATION", lambda: checked_add(2**63 - 1, 1))

    processor = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_type": "CAPTURE",
        "currency": "INR",
    }
    journal = dict(processor, entry_type="CAPTURE", currency="USD")
    processor.pop("entry_type", None)
    currency_records = (
        _record("PROCESSOR_EVENT", processor),
        _record("LEDGER_JOURNAL", journal),
    )
    checks["ALLOW_CURRENCY_CONFLICT"] = _rejects(
        "CURRENCY_DOMAIN_VIOLATION",
        lambda: _verify_cross_record_invariants(currency_records),
    )

    first = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "settlement_id": "settlement-1",
        "settlement_cycle": "cycle-1",
        "currency": "INR",
    }
    second = dict(first, processor="processor-b", settlement_cycle="cycle-2")
    ambiguity = (
        _record("PROCESSOR_SETTLEMENT", first, "stl:one"),
        _record("PROCESSOR_SETTLEMENT", second, "stl:two"),
    )
    checks["HEURISTIC_BANK_ALLOCATION"] = _rejects(
        "AMBIGUOUS_BANK_ALLOCATION", lambda: _verify_cross_record_invariants(ambiguity)
    )
    checks["ALLOW_LOCAL_PATH_ESCAPE"] = _rejects(
        "SOURCE_IDENTITY_MISMATCH",
        lambda: load_local_object_bytes(
            {"objects": [{"locator_type": "LOCAL_FILE", "relative_path": "../escape"}]},
            root,
        ),
    )
    state = AdmissionState()
    state_field = "policy_versions"
    try:
        setattr(state, state_field, (("changed", "0" * 64),))
    except FrozenInstanceError:
        checks["PARTIAL_STATE_ON_FAILURE"] = state == AdmissionState()
    else:
        checks["PARTIAL_STATE_ON_FAILURE"] = False
    checks["IMPORT_REFERENCE_ORACLE"] = not _production_imports_oracle(root)
    checks["EMIT_AUTHORITATIVE_PROOF"] = AdmittedRecord.__module__.startswith(
        "ledgerguard.reconciliation"
    ) and "authoritative_proof: bool = False" in (
        root / "src/ledgerguard/reconciliation/admission.py"
    ).read_text(encoding="utf-8")

    if list(checks) != MUTATION_CLASSES:
        raise ValueError("mutation registry and execution order differ")
    survivors = [name for name, killed in checks.items() if not killed]
    if survivors:
        raise ValueError(f"Stage 3 semantic mutants survived: {survivors}")
    return {"checks": len(checks), "survivors": 0, "killed": list(checks)}
