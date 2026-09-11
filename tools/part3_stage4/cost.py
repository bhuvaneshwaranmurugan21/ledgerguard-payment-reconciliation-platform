"""Exact-decimal Part 3 mutation admission; never used to deny owned cleanup."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

CEILING = Decimal("10.00")
UNBILLED_FLOOR = Decimal("1.00")
CLEANUP_FLOOR = Decimal("2.00")
MAXIMUM_AGE_SECONDS = 172800


def amount(value: Any) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,10})?", value
    ):
        raise ValueError("cost amount must be a nonnegative plain decimal string")
    return Decimal(value)


def admit_mutation(
    observation: dict[str, Any], estimate: dict[str, Any], now: int
) -> dict[str, str]:
    if type(now) is not int or now < 0:
        raise ValueError("invalid observation clock")
    if (
        observation.get("currency") != "USD"
        or observation.get("gross_no_credit_netting") is not True
    ):
        raise ValueError("cumulative gross USD evidence is required")
    if (
        observation.get("complete") is not True
        or observation.get("attribution_verified") is not True
    ):
        raise ValueError("cost observation incomplete or unattributed")
    digest = observation.get("source_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("cost source identity unavailable")
    through, retrieved = observation.get("data_through_epoch"), observation.get("retrieved_epoch")
    if type(through) is not int or type(retrieved) is not int:
        raise ValueError("cost timestamps unavailable")
    if not 0 <= through <= retrieved <= now or now - through > MAXIMUM_AGE_SECONDS:
        raise ValueError("cost evidence is stale or from the future")
    known = amount(observation.get("known_cumulative_gross_usd"))
    totals: dict[str, Decimal] = {}
    identities: set[str] = set()
    for category in ("unbilled", "operation", "cleanup"):
        rows = estimate.get(category)
        if not isinstance(rows, list) or not rows:
            raise ValueError("missing bounded estimate category: " + category)
        total = Decimal("0")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                raise ValueError("estimate component identity unavailable")
            if row["id"] in identities:
                raise ValueError("overlapping exposure/operation/cleanup component")
            identities.add(row["id"])
            total += amount(row.get("maximum_usd"))
        totals[category] = total
    if totals["unbilled"] < UNBILLED_FLOOR or totals["cleanup"] < CLEANUP_FLOOR:
        raise ValueError("required unbilled or cleanup reserve is missing")
    maximum = known + sum(totals.values(), Decimal("0"))
    if maximum >= CEILING:
        raise ValueError("cumulative gross ceiling or reserved cleanup would be exhausted")
    return {
        "verdict": "MUTATION_BUDGET_ADMITTED",
        "maximum_cumulative_gross_usd": str(maximum),
        "remaining_after_reserved_maxima_usd": str(CEILING - maximum),
        "cleanup_budget_gate": "NOT_APPLICABLE_TO_ALREADY_OWNED_CLEANUP",
    }
