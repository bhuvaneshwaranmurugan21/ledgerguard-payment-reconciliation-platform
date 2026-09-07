"""Strict append-only source-correction provenance and causal validation."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from .admission import AdmittedRecord, _verify_policy
from .canonical import canonical_json_bytes, canonical_sha256, parse_strict_json
from .contracts import ContractRegistry
from .errors import AdmissionRejected


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", detail)


def correction_digest(value: Mapping[str, Any]) -> str:
    """Separate correction identities from every accepted domain identity scope."""
    return canonical_sha256(
        {
            "domain": "ledgerguard.correction-provenance.v1",
            "payload": {key: item for key, item in value.items() if key != "correction_sha256"},
        }
    )


def normalize_correction(repository: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the companion without extending the accepted domain registry."""
    normalized = cast(dict[str, Any], parse_strict_json(canonical_json_bytes(value)))
    schema = json.loads(
        (repository / "contracts/part3/correction-provenance-v1.schema.json").read_text()
    )
    errors = list(Draft202012Validator(schema).iter_errors(normalized))
    if errors:
        raise AdmissionRejected("SCHEMA_VIOLATION", f"correction provenance: {errors[0].message}")
    require(
        normalized["correction_sha256"] == correction_digest(normalized),
        "correction digest differs",
    )
    items = cast(list[dict[str, Any]], normalized["items"])
    keys = [item["reconciliation_key"] for item in items]
    require(keys == sorted(set(keys)), "correction keys must be unique and sorted")
    for item in items:
        for field in ("original_sources", "corrective_sources"):
            rows = cast(list[dict[str, Any]], item[field])
            identities = [tuple(row["identity"]) for row in rows]
            require(
                identities == sorted(set(identities)),
                "correction sources must be unique and sorted",
            )
    return normalized


def validate_inputs(
    inputs: Mapping[str, Any], correction: Mapping[str, Any]
) -> tuple[bytes, bytes, dict[str, bytes]]:
    """Keep the actual source bytes in the request so readback can re-admit them."""
    require(isinstance(inputs, Mapping), "correction input must be an object")
    require(
        set(inputs) == {"policy", "manifest", "objects", "object_encoding"},
        "correction input inventory differs",
    )
    require(inputs["object_encoding"] == "base64", "correction object encoding differs")
    policy, manifest, objects = inputs["policy"], inputs["manifest"], inputs["objects"]
    require(
        isinstance(policy, Mapping) and isinstance(manifest, Mapping), "correction documents differ"
    )
    require(isinstance(objects, Mapping) and bool(objects), "correction objects unavailable")
    require(
        all(isinstance(k, str) and isinstance(v, str) for k, v in objects.items()),
        "correction object bytes must be base64 strings",
    )
    require(policy.get("policy_sha256") == correction["policy_sha256"], "correction policy differs")
    require(
        manifest.get("manifest_sha256") == correction["manifest_sha256"],
        "correction manifest differs",
    )
    decoded = {}
    for key, raw in objects.items():
        try:
            value = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error) as error:
            raise AdmissionRejected(
                "SOURCE_IDENTITY_MISMATCH", "invalid base64 correction object"
            ) from error
        require(base64.b64encode(value).decode("ascii") == raw, "noncanonical base64 object")
        decoded[key] = value
    return (
        canonical_json_bytes(policy),
        canonical_json_bytes(manifest),
        decoded,
    )


def validate_relationship(
    registry: ContractRegistry,
    item: Mapping[str, Any],
    prior_proof: Mapping[str, Any],
    prior_case: Mapping[str, Any],
    before: Sequence[AdmittedRecord],
    after: Sequence[AdmittedRecord],
    current_candidate: Mapping[str, Any],
    predecessor_policy_candidate: Mapping[str, Any],
) -> None:
    """A linked journal adjustment must reduce a real same-grain discrepancy."""
    key = str(item["reconciliation_key"])
    require(prior_case["status"] == "OPEN", "correction requires an open predecessor case")
    require(
        item["prior_proof_id"] == prior_proof["proof_id"]
        and item["prior_case_revision_sha256"] == prior_case["case_revision_sha256"]
        and item["initial_exception_proof_id"] == prior_case["initial_exception_proof_id"],
        "correction predecessor differs",
    )
    require(prior_proof["reconciliation_key"] == key, "correction grain differs")
    prior_policy = dict(item["prior_policy"])
    _verify_policy(registry, prior_policy, {})
    require(
        prior_policy["policy_sha256"] == prior_proof["policy_sha256"],
        "correction predecessor policy differs",
    )
    original = {record.source_identity: record for record in before}
    updated = {record.source_identity: record for record in after}
    for identity, record in original.items():
        require(
            identity in updated and updated[identity].business_sha256 == record.business_sha256,
            "correction removes or replaces immutable source",
        )
    for field, inventory in (("original_sources", original), ("corrective_sources", updated)):
        for row in cast(Sequence[Mapping[str, Any]], item[field]):
            identity = tuple(row["identity"])
            require(identity in inventory, "correction source is missing")
            record = inventory[identity]
            require(
                record.family == "LEDGER_JOURNAL"
                and record.reconciliation_key == key
                and record.business_sha256 == row["business_sha256"],
                "correction source scope or digest differs",
            )
    declared = {tuple(row["identity"]) for row in item["corrective_sources"]}
    # Bank records acquire their settlement scope through allocation, not their raw key.
    # Candidate lineage therefore closes the causation check over allocated bank arrivals too.
    lineage = {tuple(identity) for identity in current_candidate["source_identities"]}
    actual = {identity for identity in lineage if identity not in original}
    require(declared == actual and declared.isdisjoint(original), "correction additions differ")
    # A journal correction cannot use a same-grain late event to manufacture causation.
    require(
        all(updated[identity].family == "LEDGER_JOURNAL" for identity in actual),
        "correction has ambiguous same-grain additions",
    )
    prior_difference = prior_proof["totals"]["difference_minor"]
    effective = predecessor_policy_candidate["totals"]["difference_minor"]
    require(0 <= effective < prior_difference, "correction does not reduce predecessor discrepancy")
    if current_candidate["status"] != "EXCEPTION":
        require(
            predecessor_policy_candidate["status"] != "EXCEPTION",
            "policy change rather than source correction resolves the exception",
        )
