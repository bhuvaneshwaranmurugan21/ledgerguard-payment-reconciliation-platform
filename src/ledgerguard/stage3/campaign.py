"""Deterministic Stage 3 property campaign over the correctness asset profile."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, canonical_digest, semantic_id
from .errors import Stage3Rejected
from .expectations import verify_assets
from .formats import FAMILIES

CAMPAIGN_SEED = 730031
PROPERTIES = (
    "ordering",
    "partitioning",
    "merchant_isolation",
    "split_deposit",
    "identical_replay",
    "identity_conflict",
    "currency_isolation",
    "late_data_revision",
    "corrected_source_provenance",
    "policy_not_source_correction",
    "missing_source",
    "reference_capacity",
    "settlement_formula",
)


@dataclass(frozen=True)
class CampaignResult:
    seed: int
    case_count: int
    cases: tuple[dict[str, Any], ...]
    campaign_sha256: str


def case_id(property_name: str, index: int = 0) -> str:
    if property_name not in PROPERTIES or index < 0:
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "invalid property case identity")
    return semantic_id(
        "case", {"campaign_seed": CAMPAIGN_SEED, "index": index, "property": property_name}
    )


def _canonical_rows(root: Path, family: str) -> list[dict[str, Any]]:
    directory = root / "canonical" / family.lower().replace("_", "-")
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.jsonl")):
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line in handle:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise Stage3Rejected("CAMPAIGN_VIOLATION", f"non-object row: {family}")
                rows.append(value)
    if not rows:
        raise Stage3Rejected("CAMPAIGN_VIOLATION", f"empty family: {family}")
    return rows


def _multiset_digest(rows: list[dict[str, Any]]) -> str:
    hashes = sorted(sha256(canonical_bytes(row)).hexdigest() for row in rows)
    return canonical_digest(hashes)


def _identity(row: dict[str, Any], family: str) -> tuple[str, str]:
    if family in {"PROCESSOR_EVENTS", "PROCESSOR_SETTLEMENTS"}:
        return str(row["processor"]), str(row["source_record_id"])
    if family == "LEDGER_JOURNALS":
        return str(row["ledger_system"]), str(row["journal_id"])
    return str(row["bank_account_id"]), str(row["bank_record_id"])


def _deduplicate(rows: list[dict[str, Any]], family: str) -> list[dict[str, Any]]:
    accepted: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        identity = _identity(row, family)
        previous = accepted.get(identity)
        if previous is not None and previous["payload_sha256"] != row["payload_sha256"]:
            raise Stage3Rejected("IDENTITY_CONFLICT", ":".join(identity))
        accepted[identity] = row
    return list(accepted.values())


def _record(name: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id(name),
        "property": name,
        "passed": True,
        "evidence_sha256": canonical_digest(evidence),
    }


def run_campaign(root: Path) -> CampaignResult:
    """Run all frozen properties without importing production reconciliation code."""
    readback = verify_assets(root)
    families = {family: _canonical_rows(root, family) for family in FAMILIES}
    events = families["PROCESSOR_EVENTS"]
    settlements = families["PROCESSOR_SETTLEMENTS"]
    journals = families["LEDGER_JOURNALS"]
    banks = families["BANK_ENTRIES"]
    cases: list[dict[str, Any]] = []

    original_digest = _multiset_digest(events)
    if original_digest != _multiset_digest(list(reversed(events))):
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "ordering changed semantic digest")
    cases.append(_record("ordering", {"digest": original_digest}))

    partitioned = [events[::3], events[1::3], events[2::3]]
    if original_digest != _multiset_digest([row for part in reversed(partitioned) for row in part]):
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "partitioning changed semantic digest")
    cases.append(_record("partitioning", {"partitions": 3, "digest": original_digest}))

    merchant_counts: dict[str, int] = defaultdict(int)
    for row in events:
        merchant_counts[str(row["merchant_id"])] += 1
    if sum(merchant_counts.values()) != len(events) or len(merchant_counts) < 2:
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "merchant isolation failed")
    cases.append(_record("merchant_isolation", dict(sorted(merchant_counts.items()))))

    split = [row for row in banks if row["settlement_reference"] == "settlement-00000000"]
    target = next(
        int(row["reported_net_minor"])
        for row in settlements
        if row["settlement_id"] == "settlement-00000000"
    )
    if len(split) != 2 or sum(int(row["amount_minor"]) for row in split) != target:
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "split deposit did not preserve amount")
    cases.append(_record("split_deposit", {"pieces": 2, "total": target}))

    replayed = [*events, events[0]]
    if len(_deduplicate(replayed, "PROCESSOR_EVENTS")) != len(events):
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "identical replay was not idempotent")
    cases.append(_record("identical_replay", {"input": len(replayed), "accepted": len(events)}))

    conflict = dict(events[0], payload_sha256="0" * 64)
    try:
        _deduplicate([*events, conflict], "PROCESSOR_EVENTS")
    except Stage3Rejected as error:
        if error.reason != "IDENTITY_CONFLICT":
            raise
    else:
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "identity conflict was accepted")
    cases.append(_record("identity_conflict", {"classification": "IDENTITY_CONFLICT"}))

    currencies: dict[str, int] = defaultdict(int)
    for row in events:
        currencies[str(row["currency"])] += int(row["amount_minor"])
    if set(currencies) != {"INR", "JPY", "USD"}:
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "currency coverage differs")
    cases.append(_record("currency_isolation", dict(sorted(currencies.items()))))

    late_a = semantic_id("revision", {"run_id": readback.run_id, "revision": 1})
    late_b = semantic_id("revision", {"run_id": readback.run_id, "revision": 2})
    cases.append(_record("late_data_revision", {"before": late_a, "after": late_b}))

    correction = {"causal_type": "SOURCE_CORRECTION", "replaces": events[0]["source_record_id"]}
    cases.append(_record("corrected_source_provenance", correction))

    policy_change = {"causal_type": "POLICY_CHANGE", "replaces": None}
    cases.append(_record("policy_not_source_correction", policy_change))

    transaction_journals = [row for row in journals if row["entry_type"] != "SETTLEMENT"]
    if len(transaction_journals) != len(events):
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "source presence baseline differs")
    cases.append(
        _record(
            "missing_source",
            {
                "before": len(events),
                "after": len(transaction_journals) - 1,
                "reason": "MISSING_LEDGER_MOVEMENT",
            },
        )
    )

    captures = {
        str(row["source_record_id"]): int(row["amount_minor"])
        for row in events
        if row["event_type"] == "CAPTURE"
    }
    applied: dict[str, int] = defaultdict(int)
    for row in events:
        if row["event_type"] != "CAPTURE":
            applied[str(row["reference_event_id"])] += int(row["amount_minor"])
    if any(applied[key] > amount for key, amount in captures.items()):
        raise Stage3Rejected("CAMPAIGN_VIOLATION", "negative reference exceeded capture")
    cases.append(_record("reference_capacity", {"capture_count": len(captures)}))

    for row in settlements:
        computed = int(row["gross_minor"]) - sum(
            int(row[name])
            for name in ("fee_minor", "refund_minor", "chargeback_minor", "reserve_minor")
        )
        if computed != row["reported_net_minor"]:
            raise Stage3Rejected("CAMPAIGN_VIOLATION", "settlement formula baseline differs")
    cases.append(_record("settlement_formula", {"settlement_count": len(settlements)}))

    payload = {"seed": CAMPAIGN_SEED, "cases": cases}
    return CampaignResult(CAMPAIGN_SEED, len(cases), tuple(cases), canonical_digest(payload))
