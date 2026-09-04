"""Evidence and semantic-mutation helpers for Part 2 Stage 6."""

from __future__ import annotations

import json
import tempfile
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation import (
    FinalizationReceipt,
    FinalizationRejected,
    FinalizationStore,
    TransactionCandidate,
    TransactionKey,
    TransactionReconciliationBatch,
    TransactionState,
    canonical_json_bytes,
)
from ledgerguard_part2_stage6_validation import MUTATION_CLASSES


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


def _candidate(status: str = "MATCHED") -> TransactionCandidate:
    key = TransactionKey("processor-a", "merchant-1", "payment-1", "CAPTURE", "INR")
    return TransactionCandidate(
        reconciliation_key=key.reconciliation_key,
        key_components=key,
        processor_minor=100,
        ledger_minor=100 if status == "MATCHED" else 90,
        processor_ledger_delta_minor=0 if status == "MATCHED" else 10,
        difference_minor=0 if status == "MATCHED" else 10,
        processor_record_count=1,
        ledger_journal_count=1,
        status=status,
        reason_codes=() if status == "MATCHED" else ("PROCESSOR_LEDGER_MISMATCH",),
        source_identities=(
            ("LEDGER_JOURNAL", "ledger-a", "journal-1"),
            ("PROCESSOR_EVENT", "processor-a", "event-1"),
        ),
    )


def _batch(
    status: str = "MATCHED", run_id: str = "run-stage6-001"
) -> TransactionReconciliationBatch:
    return TransactionReconciliationBatch(
        run_id=run_id,
        policy_version="v1",
        policy_sha256="a" * 64,
        manifest_sha256=sha256(run_id.encode()).hexdigest(),
        candidates=(_candidate(status),),
        state=TransactionState(),
    )


def _finalize(
    store: FinalizationStore,
    *,
    attempt: str = "attempt-stage6-001",
    expected: str | None = None,
    status: str = "MATCHED",
    run_id: str = "run-stage6-001",
) -> FinalizationReceipt:
    return store.finalize(
        attempt_id=attempt,
        expected_head=expected,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=_batch(status, run_id),
    )


def _rejects(action: Any, text: str) -> bool:
    try:
        action()
    except FinalizationRejected as error:
        return text in error.detail and not error.authoritative_proof
    return False


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "finalization.lock"
    }


def run_mutation_checks(repository: Path) -> dict[str, Any]:
    """Exercise the semantic guards that must kill every registered Stage 6 mutant."""

    source = (repository / "src/ledgerguard/reconciliation/finalization.py").read_text()
    checks: dict[str, bool] = {}
    checks["PUBLISH_HEAD_BEFORE_OBJECTS"] = source.index(
        'if fault_point == "after_objects"'
    ) < source.index("self._replace_head(commit_sha256)")
    checks["PUBLISH_HEAD_BEFORE_COMMIT"] = source.index(
        'self._write_immutable(self.root / "commits"'
    ) < source.index("self._replace_head(commit_sha256)")
    with tempfile.TemporaryDirectory(prefix="ledgerguard-stage6-mutations-") as temporary:
        root = Path(temporary)
        store = FinalizationStore(repository, root / "store")
        first = _finalize(store)
        head = store.read_head()
        checks["ALLOW_STALE_EXPECTED_HEAD"] = (
            _rejects(
                lambda: _finalize(
                    store,
                    attempt="attempt-stage6-002",
                    status="MATCHED",
                    run_id="run-stage6-002",
                ),
                "stale authoritative control head",
            )
            and store.read_head() == head
        )
        checks["ALLOW_MULTIPLE_CONCURRENT_WINNERS"] = (
            "fcntl.flock(lock.fileno(), fcntl.LOCK_EX)" in source
        )

        proof_path = store.root / "objects" / f"{first.proofs[0].object_sha256}.json"
        checks["OVERWRITE_IMMUTABLE_OBJECT"] = _rejects(
            lambda: store._write_immutable(proof_path, b"different"), "immutable path conflict"
        )
        checks["TRUST_OBJECT_PATH_WITHOUT_DIGEST"] = _rejects(
            lambda: store.read_proof("0" * 64), "persisted object unavailable"
        )
        pretty = json.dumps(json.loads(proof_path.read_text()), indent=2).encode()
        pretty_digest = sha256(pretty).hexdigest()
        (store.root / "objects" / f"{pretty_digest}.json").write_bytes(pretty)
        checks["TRUST_NONCANONICAL_OBJECT"] = _rejects(
            lambda: store.read_proof(pretty_digest), "not canonical"
        )
        invalid = json.loads(proof_path.read_text())
        invalid["status"] = "UNKNOWN"
        invalid["proof_sha256"] = sha256(b"invalid").hexdigest()
        invalid_raw = canonical_json_bytes(invalid)
        invalid_digest = sha256(invalid_raw).hexdigest()
        (store.root / "objects" / f"{invalid_digest}.json").write_bytes(invalid_raw)
        checks["TRUST_PROOF_WITHOUT_SCHEMA"] = _rejects(
            lambda: store.read_proof(invalid_digest), "violates its contract"
        )
        wrong_self = json.loads(proof_path.read_text())
        wrong_self["proof_sha256"] = "0" * 64
        wrong_raw = canonical_json_bytes(wrong_self)
        wrong_digest = sha256(wrong_raw).hexdigest()
        (store.root / "objects" / f"{wrong_digest}.json").write_bytes(wrong_raw)
        checks["DROP_PROOF_SELF_DIGEST_CHECK"] = _rejects(
            lambda: store.read_proof(wrong_digest), "self-digest mismatch"
        )

        second = _finalize(
            store,
            attempt="attempt-stage6-003",
            expected=first.commit_sha256,
            status="EXCEPTION",
            run_id="run-stage6-003",
        )
        proof2 = store.read_proof(second.proofs[0].object_sha256)
        case2 = store.read_case_revision(second.cases[0].object_sha256)
        proof1 = store.read_proof(first.proofs[0].object_sha256)
        checks["DROP_PROOF_PREDECESSOR"] = proof2["prior_proof_id"] == proof1["proof_id"]
        checks["REWRITE_PROOF_REVISION"] = (proof1["revision"], proof2["revision"]) == (1, 2)
        checks["DROP_EXCEPTION_CASE"] = case2["status"] == "OPEN"
        checks["CREATE_CASE_FOR_INITIAL_MATCH"] = not first.cases

        third = _finalize(
            store,
            attempt="attempt-stage6-004",
            expected=second.commit_sha256,
            status="MATCHED",
            run_id="run-stage6-004",
        )
        case3 = store.read_case_revision(third.cases[0].object_sha256)
        checks["DROP_CASE_PREDECESSOR"] = (
            case3["prior_case_revision_id"] == case2["case_revision_sha256"]
            and case3["case_id"] == case2["case_id"]
        )
        checks["FAIL_TO_RESOLVE_LATE_MATCH"] = case3["status"] == "RESOLVED_BY_LATE_DATA"

        execution = FinalizationRejected("storage failed")
        checks["MISCLASSIFY_STORAGE_FAILURE_AS_FINANCIAL"] = (
            execution.ownership == "EXECUTION" and execution.reason == "EXECUTION_FAILURE"
        )
        checks["RETURN_PARTIAL_AUTHORITY_ON_FAILURE"] = (
            execution.as_dict()["outcome"] == "NO_AUTHORITATIVE_PARTIAL_PROOF"
            and execution.as_dict()["authoritative_proof"] is False
        )
        checks["REUSE_ATTEMPT_WITH_DIFFERENT_REQUEST"] = _rejects(
            lambda: _finalize(store, status="EXCEPTION"), "different request"
        )
        object_count = len(list((store.root / "objects").glob("*.json")))
        checks["DUPLICATE_EXACT_RETRY"] = (
            _finalize(store) == first
            and len(list((store.root / "objects").glob("*.json"))) == object_count
        )
        checks["LOSE_HISTORICAL_RETRY"] = _finalize(store) == first
        first_outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
        first_outcome.unlink()
        checks["LOSE_AFTER_HEAD_RECOVERY"] = _finalize(store) == first and first_outcome.exists()
        request = json.loads((store.root / "attempts/attempt-stage6-004/request.json").read_text())
        checks["DROP_PERSISTED_RECONCILIATION_STATE"] = (
            "state" in request["transaction_batch"]
            and "state_sha256" in request["transaction_batch"]
        )
        checks["ALLOW_PRIOR_HISTORY_REMOVAL"] = (
            "reconciliation history removed" in source and "source identity reused" in source
        )

        left = FinalizationStore(repository, root / "left")
        right = FinalizationStore(repository, root / "right")
        _finalize(left)
        _finalize(right)
        checks["NONDETERMINISTIC_FINALIZATION_BYTES"] = _files(left.root) == _files(right.root)

    if list(checks) != MUTATION_CLASSES:
        raise ValueError("mutation registry and execution order differ")
    survivors = [name for name, killed in checks.items() if not killed]
    if survivors:
        raise ValueError(f"Stage 6 semantic mutants survived: {survivors}")
    return {"checks": len(checks), "survivors": 0, "killed": list(checks)}
