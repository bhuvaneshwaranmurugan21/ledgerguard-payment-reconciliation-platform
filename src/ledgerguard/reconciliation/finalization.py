"""Atomic local finalization of immutable reconciliation proofs and case revisions."""

from __future__ import annotations

import fcntl
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Never, cast

from .admission import AdmissionState, AdmittedRecord, SourceStateEntry
from .canonical import (
    business_digest,
    canonical_json_bytes,
    canonical_sha256,
    canonical_timestamp,
    parse_strict_json,
)
from .contracts import ContractRegistry
from .errors import AdmissionRejected
from .identity import case_id, proof_id, source_identity
from .settlement import SettlementCandidate, SettlementReconciliationBatch, SettlementState
from .transaction import TransactionCandidate, TransactionReconciliationBatch, TransactionState

IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FAULT_POINTS = frozenset({"after_attempt", "after_objects", "after_commit", "after_head"})


class FinalizationRejected(RuntimeError):
    """An execution failure that cannot authorize partial proof state."""

    ownership = "EXECUTION"
    reason = "EXECUTION_FAILURE"
    authoritative_proof = False

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.reason}: {detail}")
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": "NO_AUTHORITATIVE_PARTIAL_PROOF",
            "ownership": self.ownership,
            "reason_code": self.reason,
            "detail": self.detail,
            "authoritative_proof": False,
        }


@dataclass(frozen=True, order=True)
class ProofReference:
    reconciliation_key: str
    proof_id: str
    proof_sha256: str
    object_sha256: str
    revision: int


@dataclass(frozen=True, order=True)
class CaseReference:
    reconciliation_key: str
    case_id: str
    case_revision_sha256: str
    object_sha256: str
    revision: int


@dataclass(frozen=True)
class FinalizationReceipt:
    attempt_id: str
    request_sha256: str
    commit_sha256: str
    proofs: tuple[ProofReference, ...]
    cases: tuple[CaseReference, ...]

    def value(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "attempt_id": self.attempt_id,
            "request_sha256": self.request_sha256,
            "commit_sha256": self.commit_sha256,
            "proofs": [
                {
                    "reconciliation_key": reference.reconciliation_key,
                    "proof_id": reference.proof_id,
                    "proof_sha256": reference.proof_sha256,
                    "object_sha256": reference.object_sha256,
                    "revision": reference.revision,
                }
                for reference in self.proofs
            ],
            "cases": [
                {
                    "reconciliation_key": reference.reconciliation_key,
                    "case_id": reference.case_id,
                    "case_revision_sha256": reference.case_revision_sha256,
                    "object_sha256": reference.object_sha256,
                    "revision": reference.revision,
                }
                for reference in self.cases
            ],
        }


Candidate = TransactionCandidate | SettlementCandidate


def _reject(detail: str) -> Never:
    raise FinalizationRejected(detail)


def _sha256(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _candidate_value(candidate: Candidate) -> dict[str, Any]:
    value = candidate.value()
    if candidate.authoritative_proof is not False or value.get("authoritative_proof") is not False:
        raise AdmissionRejected("SCHEMA_VIOLATION", "candidate authority boundary differs")
    return value


def _record_payload(record: AdmittedRecord) -> dict[str, Any]:
    return {
        "family": record.family,
        "source_identity": list(record.source_identity),
        "business_sha256": record.business_sha256,
        "value": record.value(),
        "reconciliation_key": record.reconciliation_key,
        "normalized_settlement_reference": record.normalized_settlement_reference,
        "journal_balanced_total_minor": record.journal_balanced_total_minor,
        "journal_clearing_role_valid": record.journal_clearing_role_valid,
        "identical_replay": record.identical_replay,
        "prior_state_replay": record.prior_state_replay,
    }


def _state_payload(state: TransactionState | SettlementState) -> dict[str, Any]:
    value: dict[str, Any] = {
        "records": [_record_payload(record) for record in state.records],
    }
    if isinstance(state, SettlementState):
        value["duplicate_bank_identities"] = [
            list(identity) for identity in state.duplicate_bank_identities
        ]
    return value


def _batch_payload(
    batch: TransactionReconciliationBatch | SettlementReconciliationBatch,
) -> dict[str, Any]:
    candidates = sorted(
        (_candidate_value(candidate) for candidate in batch.candidates),
        key=lambda value: str(value["reconciliation_key"]),
    )
    payload: dict[str, Any] = {
        "run_id": batch.run_id,
        "policy_version": batch.policy_version,
        "policy_sha256": batch.policy_sha256,
        "manifest_sha256": batch.manifest_sha256,
        "semantic_sha256": batch.semantic_digest(),
        "candidates": candidates,
        "state": _state_payload(batch.state),
    }
    if isinstance(batch, SettlementReconciliationBatch):
        payload.update(
            {
                "bank_allocations": sorted(
                    (allocation.value() for allocation in batch.bank_allocations),
                    key=canonical_json_bytes,
                ),
                "batch_status": batch.status,
                "batch_reason_codes": list(batch.reason_codes),
                "state_sha256": batch.state.semantic_digest(),
            }
        )
    else:
        payload["state_sha256"] = batch.state.semantic_digest()
    return payload


def _request_payload(
    *,
    attempt_id: str,
    expected_head: str | None,
    created_at: str,
    transaction_batch: TransactionReconciliationBatch | None,
    settlement_batch: SettlementReconciliationBatch | None,
) -> dict[str, Any]:
    if IDENTIFIER.fullmatch(attempt_id) is None:
        raise AdmissionRejected("SCHEMA_VIOLATION", "invalid finalization attempt identity")
    if expected_head is not None and SHA256.fullmatch(expected_head) is None:
        raise AdmissionRejected("SCHEMA_VIOLATION", "invalid expected control head")
    occurred_at = canonical_timestamp(created_at)
    batches = [batch for batch in (transaction_batch, settlement_batch) if batch is not None]
    if not batches:
        raise AdmissionRejected("SCHEMA_VIOLATION", "at least one reconciliation batch required")
    metadata = {
        (
            batch.run_id,
            batch.policy_version,
            batch.policy_sha256,
            batch.manifest_sha256,
        )
        for batch in batches
    }
    if len(metadata) != 1:
        raise AdmissionRejected(
            "POLICY_MISMATCH", "transaction and settlement batch metadata differ"
        )
    candidate_count = sum(len(batch.candidates) for batch in batches)
    if candidate_count == 0:
        raise AdmissionRejected("SCHEMA_VIOLATION", "no reconciliation candidate to finalize")
    return {
        "schema_version": "1.0",
        "attempt_id": attempt_id,
        "expected_head": expected_head,
        "created_at": occurred_at,
        "transaction_batch": (
            _batch_payload(transaction_batch) if transaction_batch is not None else None
        ),
        "settlement_batch": (
            _batch_payload(settlement_batch) if settlement_batch is not None else None
        ),
    }


def _proof(
    registry: ContractRegistry,
    *,
    candidate: Mapping[str, Any],
    metadata: Mapping[str, Any],
    created_at: str,
    revision: int,
    prior: Mapping[str, Any] | None,
) -> dict[str, Any]:
    key_components = candidate.get("key_components")
    totals = candidate.get("totals")
    if not isinstance(key_components, Mapping) or not isinstance(totals, Mapping):
        raise AdmissionRejected("SCHEMA_VIOLATION", "candidate proof shape differs")
    reconciliation_key = candidate.get("reconciliation_key")
    currency = key_components.get("currency")
    grain = "TRANSACTION" if str(reconciliation_key).startswith("txn:") else "SETTLEMENT"
    identity = {
        "grain": grain,
        "reconciliation_key": reconciliation_key,
        "revision": revision,
        "source_manifest_sha256": metadata["manifest_sha256"],
        "policy_sha256": metadata["policy_sha256"],
    }
    value: dict[str, Any] = {
        "schema_version": "2.0",
        "proof_id": proof_id(identity),
        "run_id": metadata["run_id"],
        **identity,
        "key_components": dict(key_components),
        "currency": currency,
        "policy_version": metadata["policy_version"],
        "totals": dict(totals),
        "status": candidate.get("status"),
        "reason_codes": list(cast(Sequence[Any], candidate.get("reason_codes"))),
        "created_at": created_at,
    }
    if prior is not None:
        value["prior_proof_id"] = prior["proof_id"]
    value["proof_sha256"] = canonical_sha256(value, {"proof_sha256"})
    registry.validate("RECONCILIATION_PROOF", value)
    return value


def _case_revision(
    registry: ContractRegistry,
    *,
    proof: Mapping[str, Any],
    prior: Mapping[str, Any] | None,
    occurred_at: str,
) -> dict[str, Any] | None:
    exception = proof.get("status") == "EXCEPTION"
    if prior is None and not exception:
        return None
    if prior is None:
        initial_proof = proof["proof_id"]
        revision = 1
        reasons = list(cast(Sequence[Any], proof["reason_codes"]))
    else:
        initial_proof = prior["initial_exception_proof_id"]
        revision = int(prior["revision"]) + 1
        reasons = (
            list(cast(Sequence[Any], proof["reason_codes"]))
            if exception
            else list(cast(Sequence[Any], prior["reason_codes"]))
        )
    identity = {
        "grain": proof["grain"],
        "reconciliation_key": proof["reconciliation_key"],
        "initial_exception_proof_id": initial_proof,
    }
    value: dict[str, Any] = {
        "schema_version": "2.0",
        "case_id": case_id(identity),
        **identity,
        "revision": revision,
        "status": "OPEN" if exception else "RESOLVED_BY_LATE_DATA",
        "reason_codes": reasons,
        "proof_id": proof["proof_id"],
        "actor_type": "SYSTEM",
        "occurred_at": occurred_at,
    }
    if prior is not None:
        value["prior_case_revision_id"] = prior["case_revision_sha256"]
    value["case_revision_sha256"] = canonical_sha256(value, {"case_revision_sha256"})
    registry.validate("CASE_REVISION", value)
    return value


class FinalizationStore:
    """Content-addressed local store with one conditional authoritative control head."""

    def __init__(self, repository: Path, root: Path) -> None:
        self.repository = repository.resolve()
        self.root = root.resolve()
        self.registry = ContractRegistry.load(self.repository)
        for relative in ("objects", "commits", "attempts", "control", "locks"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_immutable(self, path: Path, raw: bytes) -> None:
        if path.exists():
            if path.read_bytes() != raw:
                _reject(f"immutable path conflict: {path.relative_to(self.root)}")
            return
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._sync_directory(path.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _replace_head(self, digest: str) -> None:
        head = self.root / "control/HEAD"
        temporary = head.with_name(f".HEAD.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write((digest + "\n").encode("ascii"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, head)
            self._sync_directory(head.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _read_canonical(self, path: Path, expected_digest: str | None = None) -> dict[str, Any]:
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise FinalizationRejected(f"persisted object unavailable: {path.name}") from error
        if expected_digest is not None and _sha256(raw) != expected_digest:
            _reject(f"persisted object digest mismatch: {path.name}")
        try:
            value = parse_strict_json(raw)
            if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
                _reject(f"persisted object is not canonical: {path.name}")
        except AdmissionRejected as error:
            raise FinalizationRejected(f"persisted object is invalid: {path.name}") from error
        return value

    def read_head(self) -> str | None:
        path = self.root / "control/HEAD"
        if not path.exists():
            return None
        try:
            value = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as error:
            raise FinalizationRejected("authoritative control head is unreadable") from error
        if SHA256.fullmatch(value) is None:
            _reject("authoritative control head is malformed")
        self._read_commit(value)
        return value

    def _read_object(self, digest: str, family: str) -> dict[str, Any]:
        if SHA256.fullmatch(digest) is None:
            _reject("invalid content address")
        value = self._read_canonical(self.root / "objects" / f"{digest}.json", digest)
        try:
            self.registry.validate(family, value)
        except AdmissionRejected as error:
            raise FinalizationRejected(
                f"persisted {family.lower()} violates its contract"
            ) from error
        digest_field = (
            "proof_sha256" if family == "RECONCILIATION_PROOF" else "case_revision_sha256"
        )
        if value.get(digest_field) != canonical_sha256(value, {digest_field}):
            _reject(f"persisted {family.lower()} self-digest mismatch")
        if family == "RECONCILIATION_PROOF":
            identity = {
                key: value.get(key)
                for key in (
                    "grain",
                    "reconciliation_key",
                    "revision",
                    "source_manifest_sha256",
                    "policy_sha256",
                )
            }
            if value.get("proof_id") != proof_id(identity):
                _reject("persisted reconciliation_proof identity differs")
        else:
            identity = {
                key: value.get(key)
                for key in ("grain", "reconciliation_key", "initial_exception_proof_id")
            }
            if value.get("case_id") != case_id(identity):
                _reject("persisted case_revision identity differs")
        return value

    def read_proof(self, object_sha256: str) -> dict[str, Any]:
        return self._read_object(object_sha256, "RECONCILIATION_PROOF")

    def read_case_revision(self, object_sha256: str) -> dict[str, Any]:
        return self._read_object(object_sha256, "CASE_REVISION")

    def _read_commit(self, digest: str) -> dict[str, Any]:
        if SHA256.fullmatch(digest) is None:
            _reject("invalid commit address")
        value = self._read_canonical(self.root / "commits" / f"{digest}.json", digest)
        required = {
            "schema_version",
            "attempt_id",
            "request_sha256",
            "parent_sha256",
            "proof_heads",
            "case_heads",
            "updated_keys",
            "written_proofs",
            "written_cases",
        }
        if set(value) != required or value.get("schema_version") != "1.0":
            _reject("authoritative commit shape differs")
        for name in ("proof_heads", "case_heads"):
            rows = value.get(name)
            if not isinstance(rows, Mapping) or any(
                not isinstance(key, str)
                or not isinstance(item, str)
                or SHA256.fullmatch(item) is None
                for key, item in rows.items()
            ):
                _reject(f"authoritative commit {name} differs")
        for name in ("updated_keys", "written_proofs", "written_cases"):
            rows = value.get(name)
            if (
                not isinstance(rows, list)
                or any(not isinstance(item, str) for item in rows)
                or rows != sorted(set(rows))
            ):
                _reject(f"authoritative commit {name} differs")
        parent = value.get("parent_sha256")
        if parent is not None and (not isinstance(parent, str) or SHA256.fullmatch(parent) is None):
            _reject("authoritative commit parent differs")
        attempt_id = value.get("attempt_id")
        request_sha256 = value.get("request_sha256")
        if (
            not isinstance(attempt_id, str)
            or IDENTIFIER.fullmatch(attempt_id) is None
            or not isinstance(request_sha256, str)
            or SHA256.fullmatch(request_sha256) is None
        ):
            _reject("authoritative commit identity differs")
        self._read_request(attempt_id, request_sha256)
        return value

    def _read_request(self, attempt_id: str, request_sha256: str) -> dict[str, Any]:
        request = self._read_canonical(
            self.root / "attempts" / attempt_id / "request.json", request_sha256
        )
        if (
            set(request)
            != {
                "schema_version",
                "attempt_id",
                "expected_head",
                "created_at",
                "transaction_batch",
                "settlement_batch",
            }
            or request.get("schema_version") != "1.0"
        ):
            _reject("authoritative request shape differs")
        if request.get("attempt_id") != attempt_id:
            _reject("authoritative request identity differs")
        expected_head = request.get("expected_head")
        if expected_head is not None and (
            not isinstance(expected_head, str) or SHA256.fullmatch(expected_head) is None
        ):
            _reject("authoritative request expected head differs")
        created_at = request.get("created_at")
        if not isinstance(created_at, str):
            _reject("authoritative request timestamp differs")
        metadata: set[tuple[str, str, str, str]] = set()
        candidate_count = 0
        for name, settlement in (("transaction_batch", False), ("settlement_batch", True)):
            payload = request.get(name)
            if payload is None:
                continue
            if not isinstance(payload, Mapping):
                _reject("authoritative request batch differs")
            required = {
                "run_id",
                "policy_version",
                "policy_sha256",
                "manifest_sha256",
                "semantic_sha256",
                "candidates",
                "state",
                "state_sha256",
            }
            if settlement:
                required.update({"bank_allocations", "batch_status", "batch_reason_codes"})
            if set(payload) != required:
                _reject("authoritative request batch shape differs")
            run_id = payload.get("run_id")
            version = payload.get("policy_version")
            policy_digest = payload.get("policy_sha256")
            manifest_digest = payload.get("manifest_sha256")
            semantic_digest = payload.get("semantic_sha256")
            if not all(isinstance(item, str) for item in (run_id, version)) or not all(
                isinstance(item, str) and SHA256.fullmatch(item) is not None
                for item in (policy_digest, manifest_digest, semantic_digest)
            ):
                _reject("authoritative request metadata differs")
            metadata.add((str(run_id), str(version), str(policy_digest), str(manifest_digest)))
            candidates = payload.get("candidates")
            if not isinstance(candidates, list) or any(
                not isinstance(candidate, Mapping)
                or not isinstance(candidate.get("reconciliation_key"), str)
                or candidate.get("authoritative_proof") is not False
                for candidate in candidates
            ):
                _reject("authoritative request candidate inventory differs")
            candidate_count += len(candidates)
            self._state_from_payload(payload, settlement)
            if settlement and (
                not isinstance(payload.get("bank_allocations"), list)
                or not isinstance(payload.get("batch_status"), str)
                or not isinstance(payload.get("batch_reason_codes"), list)
            ):
                _reject("authoritative request settlement evidence differs")
        if len(metadata) != 1 or candidate_count == 0:
            _reject("authoritative request batch set differs")
        return request

    def _record_from_payload(self, value: Mapping[str, Any]) -> AdmittedRecord:
        try:
            family = str(value["family"])
            identity_value = value["source_identity"]
            if not isinstance(identity_value, list) or any(
                not isinstance(item, str) for item in identity_value
            ):
                raise TypeError("source identity")
            identity = tuple(identity_value)
            record_value = value["value"]
            if not isinstance(record_value, Mapping):
                raise TypeError("record value")
            canonical = canonical_json_bytes(record_value)
            self.registry.validate(family, record_value)
            if source_identity(family, record_value) != identity:
                _reject("persisted state source identity differs")
            if business_digest(record_value) != value["business_sha256"]:
                _reject("persisted state business digest differs")
            record = AdmittedRecord(
                family=family,
                source_identity=identity,
                business_sha256=str(value["business_sha256"]),
                canonical_bytes=canonical,
                reconciliation_key=cast(str | None, value["reconciliation_key"]),
                normalized_settlement_reference=cast(
                    str | None, value["normalized_settlement_reference"]
                ),
                journal_balanced_total_minor=cast(
                    int | None, value["journal_balanced_total_minor"]
                ),
                journal_clearing_role_valid=cast(bool | None, value["journal_clearing_role_valid"]),
                identical_replay=cast(bool, value["identical_replay"]),
                prior_state_replay=cast(bool, value["prior_state_replay"]),
            )
        except (AdmissionRejected, KeyError, TypeError, ValueError) as error:
            raise FinalizationRejected("persisted reconciliation state differs") from error
        if value != _record_payload(record):
            _reject("persisted reconciliation state shape differs")
        return record

    def _state_from_payload(
        self, payload: Mapping[str, Any], settlement: bool
    ) -> TransactionState | SettlementState:
        state_value = payload.get("state")
        if not isinstance(state_value, Mapping):
            _reject("persisted reconciliation state is unavailable")
        records_value = state_value.get("records")
        if not isinstance(records_value, list) or any(
            not isinstance(item, Mapping) for item in records_value
        ):
            _reject("persisted reconciliation record inventory differs")
        records = tuple(self._record_from_payload(item) for item in records_value)
        if settlement:
            if any(
                record.family not in {"PROCESSOR_SETTLEMENT", "BANK_ENTRY"}
                and not (
                    record.family == "LEDGER_JOURNAL"
                    and str(record.reconciliation_key).startswith("stl:")
                )
                for record in records
            ):
                _reject("persisted settlement state contains another grain")
            duplicate_value = state_value.get("duplicate_bank_identities")
            if not isinstance(duplicate_value, list) or any(
                not isinstance(identity, list)
                or any(not isinstance(item, str) for item in identity)
                for identity in duplicate_value
            ):
                _reject("persisted duplicate-bank state differs")
            state: TransactionState | SettlementState = SettlementState(
                records,
                tuple(tuple(identity) for identity in duplicate_value),
            )
        else:
            if any(
                record.family != "PROCESSOR_EVENT"
                and not (
                    record.family == "LEDGER_JOURNAL"
                    and str(record.reconciliation_key).startswith("txn:")
                )
                for record in records
            ):
                _reject("persisted transaction state contains another grain")
            if set(state_value) != {"records"}:
                _reject("persisted transaction state shape differs")
            state = TransactionState(records)
        if state.semantic_digest() != payload.get("state_sha256"):
            _reject("persisted reconciliation state digest differs")
        return state

    def load_states(self) -> tuple[AdmissionState, TransactionState, SettlementState]:
        """Recover admission and both reconciliation states from authoritative history."""

        head = self.read_head()
        if head is None:
            return AdmissionState(), TransactionState(), SettlementState()
        transaction_state: TransactionState | None = None
        settlement_state: SettlementState | None = None
        policies: dict[str, str] = {}
        manifests: dict[str, str] = {}
        cursor: str | None = head
        while cursor is not None:
            commit = self._read_commit(cursor)
            request = self._read_canonical(
                self.root / "attempts" / str(commit["attempt_id"]) / "request.json",
                str(commit["request_sha256"]),
            )
            for name, settlement in (
                ("transaction_batch", False),
                ("settlement_batch", True),
            ):
                payload = request.get(name)
                if not isinstance(payload, Mapping):
                    continue
                version = payload.get("policy_version")
                policy_digest = payload.get("policy_sha256")
                run_id = payload.get("run_id")
                manifest_digest = payload.get("manifest_sha256")
                if not all(
                    isinstance(item, str)
                    for item in (version, policy_digest, run_id, manifest_digest)
                ):
                    _reject("persisted reconciliation metadata differs")
                previous_policy = policies.setdefault(str(version), str(policy_digest))
                previous_manifest = manifests.setdefault(str(run_id), str(manifest_digest))
                if previous_policy != policy_digest or previous_manifest != manifest_digest:
                    _reject("persisted admission history conflicts")
                if settlement and settlement_state is None:
                    settlement_state = cast(
                        SettlementState, self._state_from_payload(payload, True)
                    )
                if not settlement and transaction_state is None:
                    transaction_state = cast(
                        TransactionState, self._state_from_payload(payload, False)
                    )
            cursor = cast(str | None, commit["parent_sha256"])
        transaction_state = transaction_state or TransactionState()
        settlement_state = settlement_state or SettlementState()
        sources: dict[tuple[str, ...], str] = {}
        for record in transaction_state.records + settlement_state.records:
            previous = sources.setdefault(record.source_identity, record.business_sha256)
            if previous != record.business_sha256:
                _reject("persisted source state conflicts")
        admission = AdmissionState(
            policy_versions=tuple(sorted(policies.items())),
            run_manifests=tuple(sorted(manifests.items())),
            source_records=tuple(
                SourceStateEntry(identity, digest) for identity, digest in sorted(sources.items())
            ),
        )
        return admission, transaction_state, settlement_state

    def _validate_request_state(self, request: Mapping[str, Any]) -> None:
        admission, prior_transactions, prior_settlements = self.load_states()
        policies = dict(admission.policy_versions)
        manifests = dict(admission.run_manifests)
        sources = {entry.identity: entry.business_sha256 for entry in admission.source_records}
        for name, settlement, prior_state in (
            ("transaction_batch", False, prior_transactions),
            ("settlement_batch", True, prior_settlements),
        ):
            payload = request.get(name)
            if not isinstance(payload, Mapping):
                continue
            version = payload.get("policy_version")
            policy_digest = payload.get("policy_sha256")
            run_id = payload.get("run_id")
            manifest_digest = payload.get("manifest_sha256")
            if not all(
                isinstance(item, str) for item in (version, policy_digest, run_id, manifest_digest)
            ):
                raise AdmissionRejected("SCHEMA_VIOLATION", "finalization metadata differs")
            if version in policies and policies[cast(str, version)] != policy_digest:
                raise AdmissionRejected("POLICY_MISMATCH", "policy version reused")
            if run_id in manifests and manifests[cast(str, run_id)] != manifest_digest:
                raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "run identity reused")
            state = self._state_from_payload(payload, settlement)
            prior_records = {
                record.source_identity: record.business_sha256 for record in prior_state.records
            }
            current_records = {
                record.source_identity: record.business_sha256 for record in state.records
            }
            if any(
                current_records.get(identity) != digest
                for identity, digest in prior_records.items()
            ):
                raise AdmissionRejected("IDENTITY_CONFLICT", "reconciliation history removed")
            for identity, digest in current_records.items():
                if identity in sources and sources[identity] != digest:
                    raise AdmissionRejected("IDENTITY_CONFLICT", "source identity reused")
                sources.setdefault(identity, digest)

    @staticmethod
    def _heads(commit: Mapping[str, Any] | None, name: str) -> dict[str, str]:
        if commit is None:
            return {}
        return dict(cast(Mapping[str, str], commit[name]))

    def _verify_transition(
        self, parent: Mapping[str, Any] | None, commit: Mapping[str, Any]
    ) -> None:
        parent_proofs = self._heads(parent, "proof_heads")
        parent_cases = self._heads(parent, "case_heads")
        proof_heads = self._heads(commit, "proof_heads")
        case_heads = self._heads(commit, "case_heads")
        if not set(parent_proofs).issubset(proof_heads) or not set(parent_cases).issubset(
            case_heads
        ):
            _reject("authoritative history removes an immutable head")
        updated = set(cast(Sequence[str], commit["updated_keys"]))
        changed_proofs = {
            key for key, digest in proof_heads.items() if parent_proofs.get(key) != digest
        }
        changed_cases = {
            key for key, digest in case_heads.items() if parent_cases.get(key) != digest
        }
        if updated != changed_proofs or not updated:
            _reject("authoritative commit update inventory differs")
        if set(cast(Sequence[str], commit["written_proofs"])) != {
            proof_heads[key] for key in changed_proofs
        }:
            _reject("authoritative proof write inventory differs")
        if set(cast(Sequence[str], commit["written_cases"])) != {
            case_heads[key] for key in changed_cases
        }:
            _reject("authoritative case write inventory differs")
        if not changed_cases.issubset(updated):
            _reject("case changes without a proof revision")
        request = self._read_request(str(commit["attempt_id"]), str(commit["request_sha256"]))
        if request.get("expected_head") != commit.get("parent_sha256"):
            _reject("request expected head differs from commit parent")
        requested: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        for name in ("transaction_batch", "settlement_batch"):
            payload = request.get(name)
            if not isinstance(payload, Mapping):
                continue
            for candidate in cast(Sequence[Mapping[str, Any]], payload["candidates"]):
                key = str(candidate["reconciliation_key"])
                if key in requested:
                    _reject("authoritative request contains a duplicate candidate")
                requested[key] = (candidate, payload)
        if set(requested) != updated:
            _reject("authoritative request and commit updates differ")
        for key in updated:
            proof = self.read_proof(proof_heads[key])
            if proof.get("reconciliation_key") != key:
                _reject("proof head key differs")
            prior_proof = self.read_proof(parent_proofs[key]) if key in parent_proofs else None
            if prior_proof is None:
                if proof.get("revision") != 1 or "prior_proof_id" in proof:
                    _reject("initial proof revision differs")
            elif proof.get("revision") != int(prior_proof["revision"]) + 1 or proof.get(
                "prior_proof_id"
            ) != prior_proof.get("proof_id"):
                _reject("proof predecessor chain differs")
            prior_case = self.read_case_revision(parent_cases[key]) if key in parent_cases else None
            current_case = (
                self.read_case_revision(case_heads[key]) if key in changed_cases else None
            )
            expects_case = proof.get("status") == "EXCEPTION" or prior_case is not None
            if expects_case != (current_case is not None):
                _reject("proof-to-case transition differs")
            if current_case is not None:
                if current_case.get("reconciliation_key") != key:
                    _reject("case head key differs")
                if current_case.get("proof_id") != proof.get("proof_id"):
                    _reject("case does not bind current proof")
                if prior_case is None:
                    if (
                        current_case.get("revision") != 1
                        or "prior_case_revision_id" in current_case
                    ):
                        _reject("initial case revision differs")
                elif (
                    current_case.get("revision") != int(prior_case["revision"]) + 1
                    or current_case.get("prior_case_revision_id")
                    != prior_case.get("case_revision_sha256")
                    or current_case.get("case_id") != prior_case.get("case_id")
                ):
                    _reject("case predecessor chain differs")
            candidate, metadata = requested[key]
            expected_proof = _proof(
                self.registry,
                candidate=candidate,
                metadata=metadata,
                created_at=str(request["created_at"]),
                revision=int(proof["revision"]),
                prior=prior_proof,
            )
            if proof != expected_proof:
                _reject("proof differs from authoritative request")
            expected_case = _case_revision(
                self.registry,
                proof=proof,
                prior=prior_case,
                occurred_at=str(request["created_at"]),
            )
            if expected_case != current_case:
                _reject("case differs from authoritative request")

    def verify_history(self) -> dict[str, Any] | None:
        head = self.read_head()
        if head is None:
            return None
        commits: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor: str | None = head
        while cursor is not None:
            if cursor in seen:
                _reject("authoritative commit cycle")
            seen.add(cursor)
            commit = self._read_commit(cursor)
            commits.append(commit)
            cursor = cast(str | None, commit["parent_sha256"])
        parent: dict[str, Any] | None = None
        for commit in reversed(commits):
            self._verify_transition(parent, commit)
            parent = commit
        return commits[0]

    def _find_attempt(
        self, head: str | None, attempt_id: str, request_sha256: str
    ) -> tuple[str, dict[str, Any]] | None:
        cursor = head
        seen: set[str] = set()
        while cursor is not None:
            if cursor in seen:
                _reject("authoritative commit cycle")
            seen.add(cursor)
            commit = self._read_commit(cursor)
            if (
                commit.get("attempt_id") == attempt_id
                and commit.get("request_sha256") == request_sha256
            ):
                return cursor, commit
            cursor = cast(str | None, commit["parent_sha256"])
        return None

    def _receipt(self, digest: str, commit: Mapping[str, Any]) -> FinalizationReceipt:
        proofs: list[ProofReference] = []
        cases: list[CaseReference] = []
        proof_heads = self._heads(commit, "proof_heads")
        case_heads = self._heads(commit, "case_heads")
        for key in cast(Sequence[str], commit["updated_keys"]):
            object_digest = proof_heads[key]
            proof = self.read_proof(object_digest)
            proofs.append(
                ProofReference(
                    key,
                    str(proof["proof_id"]),
                    str(proof["proof_sha256"]),
                    object_digest,
                    int(proof["revision"]),
                )
            )
            if key in case_heads and case_heads[key] in cast(
                Sequence[str], commit["written_cases"]
            ):
                case_digest = case_heads[key]
                case = self.read_case_revision(case_digest)
                cases.append(
                    CaseReference(
                        key,
                        str(case["case_id"]),
                        str(case["case_revision_sha256"]),
                        case_digest,
                        int(case["revision"]),
                    )
                )
        return FinalizationReceipt(
            attempt_id=str(commit["attempt_id"]),
            request_sha256=str(commit["request_sha256"]),
            commit_sha256=digest,
            proofs=tuple(sorted(proofs)),
            cases=tuple(sorted(cases)),
        )

    def _read_outcome(self, path: Path) -> FinalizationReceipt:
        value = self._read_canonical(path)
        try:
            if (
                set(value)
                != {
                    "schema_version",
                    "attempt_id",
                    "request_sha256",
                    "commit_sha256",
                    "proofs",
                    "cases",
                }
                or value.get("schema_version") != "1.0"
            ):
                raise ValueError("outcome envelope")
            proof_rows = cast(Sequence[Mapping[str, Any]], value["proofs"])
            case_rows = cast(Sequence[Mapping[str, Any]], value["cases"])
            if not isinstance(proof_rows, list) or not isinstance(case_rows, list):
                raise TypeError("outcome inventories")
            proofs = tuple(
                ProofReference(
                    str(row["reconciliation_key"]),
                    str(row["proof_id"]),
                    str(row["proof_sha256"]),
                    str(row["object_sha256"]),
                    int(row["revision"]),
                )
                for row in proof_rows
            )
            cases = tuple(
                CaseReference(
                    str(row["reconciliation_key"]),
                    str(row["case_id"]),
                    str(row["case_revision_sha256"]),
                    str(row["object_sha256"]),
                    int(row["revision"]),
                )
                for row in case_rows
            )
            receipt = FinalizationReceipt(
                str(value["attempt_id"]),
                str(value["request_sha256"]),
                str(value["commit_sha256"]),
                proofs,
                cases,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FinalizationRejected("attempt outcome shape differs") from error
        if value != receipt.value():
            _reject("attempt outcome shape differs")
        commit = self._read_commit(receipt.commit_sha256)
        if receipt != self._receipt(receipt.commit_sha256, commit):
            _reject("attempt outcome does not match authoritative commit")
        authoritative = self._find_attempt(
            self.read_head(), receipt.attempt_id, receipt.request_sha256
        )
        if authoritative is None or authoritative[0] != receipt.commit_sha256:
            _reject("attempt outcome is not in authoritative history")
        return receipt

    def recover_attempt(
        self,
        *,
        attempt_id: str,
        expected_head: str | None,
        created_at: str,
        run_id: str,
        policy_version: str,
        policy_sha256: str,
        manifest_sha256: str,
    ) -> FinalizationReceipt | None:
        """Return an authoritative prior receipt after validating repeated inputs."""

        if IDENTIFIER.fullmatch(attempt_id) is None:
            raise AdmissionRejected("SCHEMA_VIOLATION", "invalid finalization attempt identity")
        if expected_head is not None and SHA256.fullmatch(expected_head) is None:
            raise AdmissionRejected("SCHEMA_VIOLATION", "invalid expected control head")
        occurred_at = canonical_timestamp(created_at)
        request_path = self.root / "attempts" / attempt_id / "request.json"
        if not request_path.exists():
            return None
        lock_path = self.root / "locks/finalization.lock"
        try:
            with lock_path.open("a+b") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                request = self._read_canonical(request_path)
                expected_metadata = {
                    "run_id": run_id,
                    "policy_version": policy_version,
                    "policy_sha256": policy_sha256,
                    "manifest_sha256": manifest_sha256,
                }
                if (
                    request.get("attempt_id") != attempt_id
                    or request.get("expected_head") != expected_head
                    or request.get("created_at") != occurred_at
                    or any(
                        not isinstance(request.get(name), Mapping)
                        or any(
                            cast(Mapping[str, Any], request[name]).get(key) != value
                            for key, value in expected_metadata.items()
                        )
                        for name in ("transaction_batch", "settlement_batch")
                    )
                ):
                    _reject("attempt identity reused with different inputs")
                request_raw = canonical_json_bytes(request)
                request_digest = _sha256(request_raw)
                head = self.read_head()
                recovered = self._find_attempt(head, attempt_id, request_digest)
                if recovered is None:
                    return None
                self.verify_history()
                digest, commit = recovered
                outcome_path = request_path.with_name("outcome.json")
                if outcome_path.exists():
                    return self._read_outcome(outcome_path)
                receipt = self._receipt(digest, commit)
                self._write_immutable(outcome_path, canonical_json_bytes(receipt.value()))
                return receipt
        except FinalizationRejected:
            raise
        except OSError as error:
            raise FinalizationRejected("local finalization storage operation failed") from error

    def finalize(
        self,
        *,
        attempt_id: str,
        expected_head: str | None,
        created_at: str,
        transaction_batch: TransactionReconciliationBatch | None = None,
        settlement_batch: SettlementReconciliationBatch | None = None,
        fault_point: str | None = None,
    ) -> FinalizationReceipt:
        """Finalize every candidate through one atomic authoritative pointer update."""

        if fault_point is not None and fault_point not in FAULT_POINTS:
            raise AdmissionRejected("SCHEMA_VIOLATION", "unknown finalization fault point")
        request = _request_payload(
            attempt_id=attempt_id,
            expected_head=expected_head,
            created_at=created_at,
            transaction_batch=transaction_batch,
            settlement_batch=settlement_batch,
        )
        request_raw = canonical_json_bytes(request)
        request_sha256 = _sha256(request_raw)
        try:
            attempt_root = self.root / "attempts" / attempt_id
            attempt_root.mkdir(parents=True, exist_ok=True)
            request_path = attempt_root / "request.json"
            outcome_path = attempt_root / "outcome.json"
            lock_path = self.root / "locks/finalization.lock"
            with lock_path.open("a+b") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                if request_path.exists() and request_path.read_bytes() != request_raw:
                    _reject("attempt identity reused with a different request")
                if outcome_path.exists():
                    self.verify_history()
                    receipt = self._read_outcome(outcome_path)
                    if receipt.request_sha256 != request_sha256:
                        _reject("attempt outcome request differs")
                    return receipt
                current_head = self.read_head()
                recovered = self._find_attempt(current_head, attempt_id, request_sha256)
                if recovered is not None:
                    digest, commit = recovered
                    self.verify_history()
                    receipt = self._receipt(digest, commit)
                    self._write_immutable(outcome_path, canonical_json_bytes(receipt.value()))
                    return receipt
                self._validate_request_state(request)
                self._write_immutable(request_path, request_raw)
                if fault_point == "after_attempt":
                    os._exit(71)
                if current_head != expected_head:
                    _reject("stale authoritative control head")
                parent = self._read_commit(current_head) if current_head is not None else None
                proof_heads = self._heads(parent, "proof_heads")
                case_heads = self._heads(parent, "case_heads")
                candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
                for name in ("transaction_batch", "settlement_batch"):
                    payload = request.get(name)
                    if not isinstance(payload, Mapping):
                        continue
                    for candidate in cast(Sequence[Mapping[str, Any]], payload["candidates"]):
                        candidates.append((candidate, payload))
                keys = [str(candidate["reconciliation_key"]) for candidate, _ in candidates]
                if len(set(keys)) != len(keys):
                    raise AdmissionRejected("IDENTITY_CONFLICT", "duplicate finalization candidate")
                written_proofs: list[str] = []
                written_cases: list[str] = []
                for candidate, metadata in sorted(
                    candidates, key=lambda row: str(row[0]["reconciliation_key"])
                ):
                    key = str(candidate["reconciliation_key"])
                    prior_proof = self.read_proof(proof_heads[key]) if key in proof_heads else None
                    prior_case = (
                        self.read_case_revision(case_heads[key]) if key in case_heads else None
                    )
                    revision = 1 if prior_proof is None else int(prior_proof["revision"]) + 1
                    proof = _proof(
                        self.registry,
                        candidate=candidate,
                        metadata=metadata,
                        created_at=str(request["created_at"]),
                        revision=revision,
                        prior=prior_proof,
                    )
                    proof_raw = canonical_json_bytes(proof)
                    proof_object = _sha256(proof_raw)
                    self._write_immutable(self.root / "objects" / f"{proof_object}.json", proof_raw)
                    proof_heads[key] = proof_object
                    written_proofs.append(proof_object)
                    case = _case_revision(
                        self.registry,
                        proof=proof,
                        prior=prior_case,
                        occurred_at=str(request["created_at"]),
                    )
                    if case is not None:
                        case_raw = canonical_json_bytes(case)
                        case_object = _sha256(case_raw)
                        self._write_immutable(
                            self.root / "objects" / f"{case_object}.json", case_raw
                        )
                        case_heads[key] = case_object
                        written_cases.append(case_object)
                if fault_point == "after_objects":
                    os._exit(72)
                commit = {
                    "schema_version": "1.0",
                    "attempt_id": attempt_id,
                    "request_sha256": request_sha256,
                    "parent_sha256": current_head,
                    "proof_heads": dict(sorted(proof_heads.items())),
                    "case_heads": dict(sorted(case_heads.items())),
                    "updated_keys": sorted(keys),
                    "written_proofs": sorted(written_proofs),
                    "written_cases": sorted(written_cases),
                }
                commit_raw = canonical_json_bytes(commit)
                commit_sha256 = _sha256(commit_raw)
                self._write_immutable(self.root / "commits" / f"{commit_sha256}.json", commit_raw)
                if fault_point == "after_commit":
                    os._exit(73)
                self._replace_head(commit_sha256)
                if fault_point == "after_head":
                    os._exit(74)
                receipt = self._receipt(commit_sha256, commit)
                self._write_immutable(outcome_path, canonical_json_bytes(receipt.value()))
                self.verify_history()
                return receipt
        except FinalizationRejected:
            raise
        except OSError as error:
            raise FinalizationRejected("local finalization storage operation failed") from error
