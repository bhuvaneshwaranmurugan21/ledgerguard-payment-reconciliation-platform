"""Read-only local entry point for Part 2 Stage 5 settlement reconciliation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation import (
    AdmissionRejected,
    admit_bundle,
    load_local_object_bytes,
    parse_strict_json,
    reconcile_settlements,
)


def _object(raw: bytes) -> dict[str, Any]:
    value = parse_strict_json(raw)
    if not isinstance(value, dict):
        raise AdmissionRejected("SCHEMA_VIOLATION", "manifest must be a JSON object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        policy_bytes = arguments.policy.read_bytes()
        manifest_bytes = arguments.manifest.read_bytes()
        object_bytes = load_local_object_bytes(_object(manifest_bytes), arguments.input_root)
        admitted = admit_bundle(
            arguments.repository,
            policy_bytes,
            manifest_bytes,
            object_bytes,
        )
        reconciled = reconcile_settlements(admitted)
    except OSError as error:
        rejected = AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "input document unavailable")
        print(json.dumps(rejected.as_dict(), sort_keys=True, separators=(",", ":")))
        raise SystemExit(2) from error
    except AdmissionRejected as error:
        print(json.dumps(error.as_dict(), sort_keys=True, separators=(",", ":")))
        raise SystemExit(2) from error
    result = {
        "outcome": "SETTLEMENT_RECONCILIATION_CANDIDATE",
        "run_id": reconciled.run_id,
        "policy_version": reconciled.policy_version,
        "policy_sha256": reconciled.policy_sha256,
        "manifest_sha256": reconciled.manifest_sha256,
        "status": reconciled.status,
        "reason_codes": list(reconciled.reason_codes),
        "settlement_candidate_count": len(reconciled.candidates),
        "settlement_candidates": [candidate.value() for candidate in reconciled.candidates],
        "bank_allocation_count": len(reconciled.bank_allocations),
        "bank_allocations": [allocation.value() for allocation in reconciled.bank_allocations],
        "settlement_state_sha256": reconciled.state.semantic_digest(),
        "semantic_digest": reconciled.semantic_digest(),
        "authoritative_proof": False,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
