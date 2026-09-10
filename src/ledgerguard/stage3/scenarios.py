"""Frozen Stage 3 scenario semantics shared by assets and qualification."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_digest

SCENARIO_SEED = 730031

SCENARIOS = (
    ("P3-S3-S001", "balanced multi-currency source bundle", "EXPECTED_MATCH"),
    ("P3-S3-S002", "transaction amount mismatch", "EXPECTED_EXCEPTION"),
    ("P3-S3-S003", "settlement formula mismatch", "EXPECTED_EXCEPTION"),
    ("P3-S3-S004", "missing processor activity", "EXPECTED_EXCEPTION"),
    ("P3-S3-S005", "missing ledger movement", "EXPECTED_EXCEPTION"),
    ("P3-S3-S006", "missing bank settlement", "EXPECTED_EXCEPTION"),
    ("P3-S3-S007", "invalid ledger account role", "EXPECTED_EXCEPTION"),
    ("P3-S3-S008", "invalid bank account", "EXPECTED_EXCEPTION"),
    ("P3-S3-S009", "exact split deposit", "EXPECTED_MATCH"),
    ("P3-S3-S010", "identical replay", "EXPECTED_IDEMPOTENT"),
    ("P3-S3-S011", "source identity conflict", "EXPECTED_REJECTION"),
    ("P3-S3-S012", "unresolved capture reference", "EXPECTED_EXCEPTION"),
    ("P3-S3-S013", "over-applied capture reference", "EXPECTED_EXCEPTION"),
    ("P3-S3-S014", "partition and input ordering permutation", "EXPECTED_INVARIANT"),
    ("P3-S3-S015", "merchant and currency isolation", "EXPECTED_INVARIANT"),
    ("P3-S3-S016", "late-data immutable revision", "EXPECTED_NEW_REVISION"),
    ("P3-S3-S017", "corrected-source provenance", "EXPECTED_NEW_REVISION"),
    ("P3-S3-S018", "policy change is not source correction", "EXPECTED_REJECTION"),
    ("P3-S3-S019", "skewed merchant concentration", "EXPECTED_INVARIANT"),
    ("P3-S3-S020", "duplicate bank identity", "EXPECTED_EXCEPTION"),
    ("P3-S3-S021", "unknown bank reference", "EXPECTED_UNALLOCATED"),
)


def scenario_inventory() -> dict[str, Any]:
    """Return the canonical, destination-independent scenario inventory."""
    value: dict[str, Any] = {
        "schema_version": "1.0",
        "campaign_seed": SCENARIO_SEED,
        "parameters": {
            "negative_event_cycle": ["REFUND", "CHARGEBACK", "REVERSAL"],
            "split_every_settlements": 10,
            "skew_cycle": 4,
            "skew_hotspot_slots": 3,
            "late_data_strategy": "NEW_IMMUTABLE_REVISION",
            "identical_replay": "SAME_IDENTITY_SAME_PAYLOAD",
            "identity_conflict": "SAME_IDENTITY_DIFFERENT_PAYLOAD",
            "missing_source": "ONE_FAMILY_RECORD_REMOVED",
            "policy_change": "NOT_A_SOURCE_CORRECTION",
        },
        "scenarios": [
            {"scenario_id": scenario_id, "title": title, "expected": expected}
            for scenario_id, title, expected in SCENARIOS
        ],
    }
    value["scenario_inventory_sha256"] = canonical_digest(value)
    return value
