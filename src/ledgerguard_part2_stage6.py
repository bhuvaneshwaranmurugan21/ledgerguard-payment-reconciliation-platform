"""Local entry point for atomic Part 2 Stage 6 proof finalization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation import (
    AdmissionRejected,
    FinalizationRejected,
    FinalizationStore,
    admit_bundle,
    load_local_object_bytes,
    parse_strict_json,
    reconcile_settlements,
    reconcile_transactions,
)


def _object(raw: bytes) -> dict[str, Any]:
    value = parse_strict_json(raw)
    if not isinstance(value, dict):
        raise AdmissionRejected("SCHEMA_VIOLATION", "manifest must be a JSON object")
    return value


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--created-at", required=True)
    arguments = parser.parse_args()
    try:
        store = FinalizationStore(arguments.repository, arguments.store)
    except OSError as error:
        store_rejected = FinalizationRejected("local finalization store unavailable")
        _emit(store_rejected.as_dict())
        raise SystemExit(3) from error
    try:
        admission_state, transaction_state, settlement_state = store.load_states()
        policy_bytes = arguments.policy.read_bytes()
        manifest_bytes = arguments.manifest.read_bytes()
        object_bytes = load_local_object_bytes(_object(manifest_bytes), arguments.input_root)
        admitted = admit_bundle(
            arguments.repository,
            policy_bytes,
            manifest_bytes,
            object_bytes,
            prior_state=admission_state,
        )
        expected_head = None if arguments.expected_head == "NONE" else arguments.expected_head
        receipt = store.recover_attempt(
            attempt_id=arguments.attempt_id,
            expected_head=expected_head,
            created_at=arguments.created_at,
            run_id=admitted.run_id,
            policy_version=admitted.policy_version,
            policy_sha256=admitted.policy_sha256,
            manifest_sha256=admitted.manifest_sha256,
        )
        if receipt is None:
            transactions = reconcile_transactions(admitted, transaction_state)
            settlements = reconcile_settlements(admitted, settlement_state)
            receipt = store.finalize(
                attempt_id=arguments.attempt_id,
                expected_head=expected_head,
                created_at=arguments.created_at,
                transaction_batch=transactions,
                settlement_batch=settlements,
            )
    except OSError as error:
        input_rejected = AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "input document unavailable")
        _emit(input_rejected.as_dict())
        raise SystemExit(2) from error
    except AdmissionRejected as error:
        _emit(error.as_dict())
        raise SystemExit(2) from error
    except FinalizationRejected as error:
        _emit(error.as_dict())
        raise SystemExit(3) from error
    result = receipt.value()
    result.update(
        {
            "outcome": "AUTHORITATIVE_PROOFS_FINALIZED",
            "authoritative_proof": True,
            "proof_count": len(receipt.proofs),
            "case_revision_count": len(receipt.cases),
        }
    )
    _emit(result)


if __name__ == "__main__":
    main()
