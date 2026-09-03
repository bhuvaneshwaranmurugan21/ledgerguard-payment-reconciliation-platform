"""Atomic production admission for policy-bound reconciliation input bundles."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from .arithmetic import checked_add, checked_i64
from .canonical import (
    business_digest,
    canonical_json_bytes,
    canonical_sha256,
    parse_strict_json,
)
from .contracts import MANIFEST_FAMILY_CONTRACTS, ContractRegistry
from .errors import AdmissionRejected
from .identity import (
    normalize_bank_reference,
    settlement_key,
    source_identity,
    transaction_key,
)

REQUIRED_MANIFEST_FAMILIES = frozenset(MANIFEST_FAMILY_CONTRACTS)
TRANSACTION_ENTRY_TYPES = frozenset({"CAPTURE", "REFUND", "CHARGEBACK", "REVERSAL"})


@dataclass(frozen=True, order=True)
class SourceStateEntry:
    identity: tuple[str, ...]
    business_sha256: str


@dataclass(frozen=True)
class AdmissionState:
    policy_versions: tuple[tuple[str, str], ...] = ()
    run_manifests: tuple[tuple[str, str], ...] = ()
    source_records: tuple[SourceStateEntry, ...] = ()


@dataclass(frozen=True)
class AdmittedRecord:
    family: str
    source_identity: tuple[str, ...]
    business_sha256: str
    canonical_bytes: bytes
    reconciliation_key: str | None
    normalized_settlement_reference: str | None
    journal_balanced_total_minor: int | None
    journal_clearing_role_valid: bool | None

    def value(self) -> dict[str, Any]:
        decoded = json.loads(self.canonical_bytes)
        if not isinstance(decoded, dict):
            raise RuntimeError("admitted record bytes are not an object")
        return decoded


@dataclass(frozen=True)
class AdmittedBatch:
    run_id: str
    policy_version: str
    policy_sha256: str
    manifest_sha256: str
    policy_canonical_bytes: bytes
    manifest_canonical_bytes: bytes
    records: tuple[AdmittedRecord, ...]
    replay_count: int
    state: AdmissionState
    authoritative_proof: bool = False

    def semantic_digest(self) -> str:
        payload = {
            "run_id": self.run_id,
            "policy_version": self.policy_version,
            "policy_sha256": self.policy_sha256,
            "manifest_sha256": self.manifest_sha256,
            "records": [
                {
                    "family": record.family,
                    "source_identity": list(record.source_identity),
                    "business_sha256": record.business_sha256,
                    "reconciliation_key": record.reconciliation_key,
                    "normalized_settlement_reference": record.normalized_settlement_reference,
                    "journal_balanced_total_minor": record.journal_balanced_total_minor,
                    "journal_clearing_role_valid": record.journal_clearing_role_valid,
                }
                for record in self.records
            ],
            "replay_count": self.replay_count,
            "authoritative_proof": False,
        }
        return sha256(canonical_json_bytes(payload)).hexdigest()


def _require_object(value: Any, detail: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdmissionRejected("SCHEMA_VIOLATION", detail)
    return value


def _parse_document(raw: bytes, detail: str) -> dict[str, Any]:
    return _require_object(parse_strict_json(raw), detail)


def _verify_policy(
    registry: ContractRegistry,
    policy: dict[str, Any],
    prior: Mapping[str, str],
) -> tuple[str, dict[str, str]]:
    registry.validate("RECONCILIATION_POLICY", policy)
    digest = canonical_sha256(policy, {"policy_sha256"})
    if policy.get("policy_sha256") != digest:
        raise AdmissionRejected("POLICY_MISMATCH", "policy digest mismatch")
    version = policy["policy_version"]
    previous = prior.get(version)
    if previous is not None and previous != digest:
        raise AdmissionRejected("POLICY_MISMATCH", "policy version reused with changed digest")
    candidate = dict(prior)
    candidate[version] = digest
    seen: set[tuple[str, str]] = set()
    for row in policy["settlement_rules"]["permitted_bank_accounts"]:
        key = (row["merchant_id"], row["currency"])
        if key in seen:
            raise AdmissionRejected("POLICY_MISMATCH", "duplicate permitted-account domain")
        seen.add(key)
    return digest, candidate


def _verify_manifest(
    registry: ContractRegistry,
    manifest: dict[str, Any],
    policy: dict[str, Any],
    policy_digest: str,
    prior: Mapping[str, str],
) -> tuple[str, dict[str, str]]:
    registry.validate("RUN_MANIFEST", manifest)
    digest = canonical_sha256(manifest, {"manifest_sha256"})
    if manifest.get("manifest_sha256") != digest:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "manifest digest mismatch")
    if manifest.get("policy_version") != policy.get("policy_version"):
        raise AdmissionRejected("POLICY_MISMATCH", "manifest policy version mismatch")
    if manifest.get("policy_sha256") != policy_digest:
        raise AdmissionRejected("POLICY_MISMATCH", "manifest policy digest mismatch")
    families = {item["family"] for item in manifest["objects"]}
    if families != REQUIRED_MANIFEST_FAMILIES:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "manifest family set mismatch")
    run_id = manifest["run_id"]
    previous = prior.get(run_id)
    if previous is not None and previous != digest:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "run identifier reused")
    candidate = dict(prior)
    candidate[run_id] = digest
    return digest, candidate


def object_locator(item: Mapping[str, Any]) -> str:
    locator_type = item.get("locator_type")
    if locator_type == "LOCAL_FILE":
        relative = item.get("relative_path")
        if not isinstance(relative, str):
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "missing local locator")
        return f"local:{relative}"
    if locator_type == "S3_OBJECT":
        uri = item.get("s3_uri")
        version = item.get("version_id")
        if not isinstance(uri, str) or not isinstance(version, str):
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "missing S3 locator identity")
        return f"s3:{uri}#{version}"
    raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "unknown locator type")


def parse_json_lines(
    raw: bytes,
    expected_size: object,
    expected_sha256: object,
    expected_count: object,
) -> list[dict[str, Any]]:
    size = checked_i64(expected_size)
    count = checked_i64(expected_count)
    if size <= 0 or count < 0:
        raise AdmissionRejected("SCHEMA_VIOLATION", "invalid source object bounds")
    if not isinstance(expected_sha256, str):
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "object digest identity")
    if len(raw) != size:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "object byte-size mismatch")
    if sha256(raw).hexdigest() != expected_sha256:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "object digest mismatch")
    if b"\r" in raw:
        raise AdmissionRejected("SCHEMA_VIOLATION", "source object requires LF framing")
    if count == 0:
        if raw != b"\n":
            raise AdmissionRejected(
                "SOURCE_IDENTITY_MISMATCH", "zero-record object requires one LF byte"
            )
        return []
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if any(not line for line in lines):
        raise AdmissionRejected("SCHEMA_VIOLATION", "empty JSON Lines record")
    if len(lines) != count:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "object record-count mismatch")
    records = [_parse_document(line, "source record must be a JSON object") for line in lines]
    return records


def _journal_admission(record: Mapping[str, Any]) -> tuple[int, bool]:
    postings = record.get("postings")
    if (
        not isinstance(postings, Sequence)
        or isinstance(postings, (str, bytes))
        or len(postings) < 2
    ):
        raise AdmissionRejected("UNBALANCED_JOURNAL", "at least two postings required")
    debit = 0
    credit = 0
    line_ids: set[str] = set()
    clearing_count = 0
    for posting in postings:
        if not isinstance(posting, Mapping):
            raise AdmissionRejected("UNBALANCED_JOURNAL", "posting must be an object")
        line_id = posting.get("line_id")
        if not isinstance(line_id, str) or not line_id or line_id in line_ids:
            raise AdmissionRejected("UNBALANCED_JOURNAL", "duplicate or missing line identifier")
        line_ids.add(line_id)
        amount = checked_i64(posting.get("amount_minor"))
        if amount <= 0:
            raise AdmissionRejected("UNBALANCED_JOURNAL", "posting amount must be positive")
        side = posting.get("side")
        if side == "DEBIT":
            debit = checked_add(debit, amount)
        elif side == "CREDIT":
            credit = checked_add(credit, amount)
        else:
            raise AdmissionRejected("UNBALANCED_JOURNAL", "invalid posting side")
        if posting.get("account_role") == "PROCESSOR_CLEARING":
            clearing_count += 1
    if debit <= 0 or debit != credit:
        raise AdmissionRejected("UNBALANCED_JOURNAL", "journal is not balanced")
    transaction = "payment_id" in record
    settlement = "settlement_id" in record and "settlement_cycle" in record
    if transaction == settlement:
        raise AdmissionRejected("UNBALANCED_JOURNAL", "exactly one business key required")
    return debit, clearing_count == 1


def _record_key(family: str, record: Mapping[str, Any]) -> str | None:
    if family == "PROCESSOR_EVENT":
        return transaction_key(
            {
                "processor": record["processor"],
                "merchant_id": record["merchant_id"],
                "payment_id": record["payment_id"],
                "event_class": record["event_type"],
                "currency": record["currency"],
            }
        )
    if family == "PROCESSOR_SETTLEMENT":
        return settlement_key(
            {
                "processor": record["processor"],
                "merchant_id": record["merchant_id"],
                "settlement_id": record["settlement_id"],
                "settlement_cycle": record["settlement_cycle"],
                "currency": record["currency"],
            }
        )
    if family == "LEDGER_JOURNAL":
        if record["entry_type"] in TRANSACTION_ENTRY_TYPES:
            return transaction_key(
                {
                    "processor": record["processor"],
                    "merchant_id": record["merchant_id"],
                    "payment_id": record["payment_id"],
                    "event_class": record["entry_type"],
                    "currency": record["currency"],
                }
            )
        return settlement_key(
            {
                "processor": record["processor"],
                "merchant_id": record["merchant_id"],
                "settlement_id": record["settlement_id"],
                "settlement_cycle": record["settlement_cycle"],
                "currency": record["currency"],
            }
        )
    return None


def _currency_domain(family: str, record: Mapping[str, Any]) -> tuple[str, ...] | None:
    if family == "PROCESSOR_EVENT":
        return (
            "TRANSACTION",
            record["processor"],
            record["merchant_id"],
            record["payment_id"],
            record["event_type"],
        )
    if family == "PROCESSOR_SETTLEMENT":
        return (
            "SETTLEMENT",
            record["processor"],
            record["merchant_id"],
            record["settlement_id"],
            record["settlement_cycle"],
        )
    if family == "LEDGER_JOURNAL":
        if record["entry_type"] in TRANSACTION_ENTRY_TYPES:
            return (
                "TRANSACTION",
                record["processor"],
                record["merchant_id"],
                record["payment_id"],
                record["entry_type"],
            )
        return (
            "SETTLEMENT",
            record["processor"],
            record["merchant_id"],
            record["settlement_id"],
            record["settlement_cycle"],
        )
    return None


def _verify_cross_record_invariants(records: Sequence[AdmittedRecord]) -> None:
    currencies: dict[tuple[str, ...], str] = {}
    settlement_domains: dict[tuple[str, str, str], tuple[str, str]] = {}
    reference_targets: dict[tuple[str, str, str], set[str]] = {}
    decoded = [(record, record.value()) for record in records]
    for admitted, value in decoded:
        domain = _currency_domain(admitted.family, value)
        if domain is not None:
            currency = value["currency"]
            prior = currencies.get(domain)
            if prior is not None and prior != currency:
                raise AdmissionRejected("CURRENCY_DOMAIN_VIOLATION", "grain currency conflict")
            currencies[domain] = currency
        if admitted.family == "PROCESSOR_SETTLEMENT":
            uniqueness = (value["merchant_id"], value["currency"], value["settlement_id"])
            target = (value["processor"], value["settlement_cycle"])
            prior_target = settlement_domains.get(uniqueness)
            if prior_target is not None and prior_target != target:
                raise AdmissionRejected(
                    "AMBIGUOUS_BANK_ALLOCATION", "settlement identifier is not unique"
                )
            settlement_domains[uniqueness] = target
            lookup = (
                value["merchant_id"],
                value["currency"],
                normalize_bank_reference(value["settlement_id"]) or "",
            )
            reference_targets.setdefault(lookup, set()).add(admitted.reconciliation_key or "")
    for admitted, value in decoded:
        if admitted.family != "BANK_ENTRY" or admitted.normalized_settlement_reference is None:
            continue
        lookup = (
            value["merchant_id"],
            value["currency"],
            admitted.normalized_settlement_reference,
        )
        if len(reference_targets.get(lookup, set())) > 1:
            raise AdmissionRejected(
                "AMBIGUOUS_BANK_ALLOCATION", "bank reference has multiple settlement targets"
            )


def _state_maps(
    prior_state: AdmissionState,
) -> tuple[dict[str, str], dict[str, str], dict[tuple[str, ...], str]]:
    return (
        dict(prior_state.policy_versions),
        dict(prior_state.run_manifests),
        {entry.identity: entry.business_sha256 for entry in prior_state.source_records},
    )


def admit_bundle(
    repository: Path,
    policy_bytes: bytes,
    manifest_bytes: bytes,
    object_bytes: Mapping[str, bytes],
    prior_state: AdmissionState | None = None,
) -> AdmittedBatch:
    """Admit one complete bundle without mutating prior state or emitting proof output."""

    registry = ContractRegistry.load(repository)
    policy = _parse_document(policy_bytes, "policy must be a JSON object")
    manifest = _parse_document(manifest_bytes, "manifest must be a JSON object")
    prior = prior_state or AdmissionState()
    policy_prior, manifest_prior, source_prior = _state_maps(prior)
    policy_digest, policy_candidate = _verify_policy(registry, policy, policy_prior)
    manifest_digest, manifest_candidate = _verify_manifest(
        registry, manifest, policy, policy_digest, manifest_prior
    )
    declared: dict[str, Mapping[str, Any]] = {}
    for item in manifest["objects"]:
        locator = object_locator(item)
        if locator in declared:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "duplicate object locator")
        declared[locator] = item
    if set(object_bytes) != set(declared):
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "supplied object set mismatch")

    admitted_by_identity: dict[tuple[str, ...], AdmittedRecord] = {}
    candidate_sources = dict(source_prior)
    replay_count = 0
    for locator in sorted(declared):
        item = declared[locator]
        contract_family = MANIFEST_FAMILY_CONTRACTS[item["family"]]
        values = parse_json_lines(
            object_bytes[locator], item["size_bytes"], item["sha256"], item["record_count"]
        )
        for value in values:
            registry.validate(contract_family, value)
            digest = business_digest(value)
            if value.get("payload_sha256") != digest:
                raise AdmissionRejected(
                    "SOURCE_IDENTITY_MISMATCH", "source payload digest mismatch"
                )
            identity = source_identity(contract_family, value)
            previous = candidate_sources.get(identity)
            if previous is not None and previous != digest:
                raise AdmissionRejected("IDENTITY_CONFLICT", "source identity reused")
            if previous == digest:
                replay_count += 1
                continue
            balanced_total: int | None = None
            role_valid: bool | None = None
            if contract_family == "LEDGER_JOURNAL":
                balanced_total, role_valid = _journal_admission(value)
            candidate_sources[identity] = digest
            admitted_by_identity[identity] = AdmittedRecord(
                family=contract_family,
                source_identity=identity,
                business_sha256=digest,
                canonical_bytes=canonical_json_bytes(value),
                reconciliation_key=_record_key(contract_family, value),
                normalized_settlement_reference=(
                    normalize_bank_reference(value.get("settlement_reference"))
                    if contract_family == "BANK_ENTRY"
                    else None
                ),
                journal_balanced_total_minor=balanced_total,
                journal_clearing_role_valid=role_valid,
            )
    records = tuple(admitted_by_identity[key] for key in sorted(admitted_by_identity))
    _verify_cross_record_invariants(records)
    state = AdmissionState(
        policy_versions=tuple(sorted(policy_candidate.items())),
        run_manifests=tuple(sorted(manifest_candidate.items())),
        source_records=tuple(
            SourceStateEntry(identity, digest)
            for identity, digest in sorted(candidate_sources.items())
        ),
    )
    return AdmittedBatch(
        run_id=manifest["run_id"],
        policy_version=policy["policy_version"],
        policy_sha256=policy_digest,
        manifest_sha256=manifest_digest,
        policy_canonical_bytes=canonical_json_bytes(policy),
        manifest_canonical_bytes=canonical_json_bytes(manifest),
        records=records,
        replay_count=replay_count,
        state=state,
    )


def _secure_local_path(input_root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "unsafe local path")
    try:
        root = input_root.resolve(strict=True)
        candidate = root
        for part in pure.parts:
            candidate /= part
            if candidate.is_symlink():
                raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "symlinked local path")
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise AdmissionRejected(
            "SOURCE_IDENTITY_MISMATCH", "local path cannot be resolved"
        ) from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "escaped local path") from error
    if not resolved.is_file():
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "local object is not a file")
    return resolved


def load_local_object_bytes(manifest: Mapping[str, Any], input_root: Path) -> dict[str, bytes]:
    """Read each local manifest object exactly once from a confined input root."""

    result: dict[str, bytes] = {}
    objects = manifest.get("objects")
    if not isinstance(objects, list):
        raise AdmissionRejected("SCHEMA_VIOLATION", "manifest objects must be an array")
    for item in objects:
        if not isinstance(item, Mapping):
            raise AdmissionRejected("SCHEMA_VIOLATION", "manifest object must be an object")
        if item.get("locator_type") != "LOCAL_FILE":
            raise AdmissionRejected(
                "SOURCE_IDENTITY_MISMATCH", "local execution requires local objects"
            )
        relative = item.get("relative_path")
        if not isinstance(relative, str):
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "missing relative path")
        locator = object_locator(item)
        if locator in result:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "duplicate local locator")
        path = _secure_local_path(input_root, relative)
        try:
            result[locator] = path.read_bytes()
        except OSError as error:
            raise AdmissionRejected(
                "SOURCE_IDENTITY_MISMATCH", "local object cannot be read"
            ) from error
    return result
