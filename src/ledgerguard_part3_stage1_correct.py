"""Local, manifest-bound correction through normal admission and atomic finalization."""

from __future__ import annotations

import argparse
from pathlib import Path

from ledgerguard.reconciliation import (
    AdmissionRejected,
    FinalizationRejected,
    FinalizationStore,
    admit_bundle,
    load_local_object_bytes,
    reconcile_settlements,
    reconcile_transactions,
)
from ledgerguard_part2_stage6 import _emit, _object


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("repository", "policy", "manifest", "input-root", "store", "correction"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("attempt-id", "expected-head", "created-at"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    try:
        store = FinalizationStore(args.repository, args.store)
    except OSError as error:
        _emit(FinalizationRejected("local finalization store unavailable").as_dict())
        raise SystemExit(3) from error
    try:
        admission, transactions, settlements = store.load_states()
        policy_bytes, manifest_bytes = args.policy.read_bytes(), args.manifest.read_bytes()
        manifest = _object(manifest_bytes)
        objects = load_local_object_bytes(manifest, args.input_root)
        correction = _object(args.correction.read_bytes())
        inputs = {
            "policy": _object(policy_bytes),
            "manifest": manifest,
            "objects": {name: raw.decode("utf-8") for name, raw in objects.items()},
        }
        admitted = admit_bundle(
            args.repository, policy_bytes, manifest_bytes, objects, prior_state=admission
        )
        receipt = store.recover_attempt(
            attempt_id=args.attempt_id,
            expected_head=args.expected_head,
            created_at=args.created_at,
            run_id=admitted.run_id,
            policy_version=admitted.policy_version,
            policy_sha256=admitted.policy_sha256,
            manifest_sha256=admitted.manifest_sha256,
            correction=correction,
            correction_inputs=inputs,
        )
        if receipt is None:
            receipt = store.finalize(
                attempt_id=args.attempt_id,
                expected_head=args.expected_head,
                created_at=args.created_at,
                transaction_batch=reconcile_transactions(admitted, transactions),
                settlement_batch=reconcile_settlements(admitted, settlements),
                correction=correction,
                correction_inputs=inputs,
            )
    except (OSError, UnicodeError) as error:
        _emit(
            AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "correction input unavailable").as_dict()
        )
        raise SystemExit(2) from error
    except AdmissionRejected as error:
        _emit(error.as_dict())
        raise SystemExit(2) from error
    except FinalizationRejected as error:
        _emit(error.as_dict())
        raise SystemExit(3) from error
    _emit(receipt.value())


if __name__ == "__main__":
    main()
