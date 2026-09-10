from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from tools.part3_stage4.cost import admit_mutation, amount

OBSERVATION = {
    "currency": "USD",
    "gross_no_credit_netting": True,
    "complete": True,
    "attribution_verified": True,
    "source_sha256": "a" * 64,
    "data_through_epoch": 100,
    "retrieved_epoch": 200,
    "known_cumulative_gross_usd": "0.7918",
}
ESTIMATE = {
    "unbilled": [{"id": "delayed-billing", "maximum_usd": "1.00"}],
    "operation": [{"id": "new-operation", "maximum_usd": "0.50"}],
    "cleanup": [{"id": "rescue", "maximum_usd": "2.00"}],
}


def test_budget_retains_cumulative_gross_and_separate_reserves() -> None:
    result = admit_mutation(OBSERVATION, ESTIMATE, 300)
    assert result["maximum_cumulative_gross_usd"] == "4.2918"
    assert result["remaining_after_reserved_maxima_usd"] == "5.7082"
    assert result["cleanup_budget_gate"] == "NOT_APPLICABLE_TO_ALREADY_OWNED_CLEANUP"
    assert amount("9007199254740993.1") == Decimal("9007199254740993.1")


@pytest.mark.parametrize(
    "value", [None, True, 1.0, "-1", "NaN", "Infinity", "1e2", "01", " 1", "1.00000000001"]
)
def test_money_rejects_floating_signed_nonfinite_or_ambiguous_inputs(value: Any) -> None:
    with pytest.raises(ValueError, match="decimal"):
        amount(value)


@pytest.mark.parametrize("now", [True, -1, 2.5])
def test_invalid_clock_rejected(now: Any) -> None:
    with pytest.raises(ValueError, match="clock"):
        admit_mutation(OBSERVATION, ESTIMATE, now)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("currency", "INR", "gross USD"),
        ("gross_no_credit_netting", False, "gross USD"),
        ("complete", False, "incomplete"),
        ("attribution_verified", False, "unattributed"),
        ("source_sha256", None, "source identity"),
        ("source_sha256", "a" * 63, "source identity"),
        ("data_through_epoch", True, "timestamps"),
        ("retrieved_epoch", None, "timestamps"),
        ("data_through_epoch", 250, "future"),
        ("retrieved_epoch", 301, "future"),
        ("data_through_epoch", -1, "stale"),
        ("known_cumulative_gross_usd", None, "decimal"),
    ],
)
def test_incomplete_or_invalid_observation_blocks(field: str, value: Any, reason: str) -> None:
    observation = dict(OBSERVATION, **{field: value})
    with pytest.raises(ValueError, match=reason):
        admit_mutation(observation, ESTIMATE, 300)


def test_stale_and_exact_ceiling_block_new_mutation() -> None:
    with pytest.raises(ValueError, match="stale"):
        admit_mutation(OBSERVATION, ESTIMATE, 172901)
    for known in ["6.50", "6.5000000001", "10.00"]:
        with pytest.raises(ValueError, match="ceiling"):
            admit_mutation(dict(OBSERVATION, known_cumulative_gross_usd=known), ESTIMATE, 300)
    accepted = admit_mutation(
        dict(OBSERVATION, known_cumulative_gross_usd="6.4999999999"), ESTIMATE, 300
    )
    assert Decimal(accepted["remaining_after_reserved_maxima_usd"]) == Decimal("0.0000000001")


@pytest.mark.parametrize("category", ["unbilled", "operation", "cleanup"])
@pytest.mark.parametrize("bad", [None, [], "not a list", [1], [{"id": None}], [{"id": ""}]])
def test_missing_or_invalid_estimate_blocks(category: str, bad: Any) -> None:
    changed = deepcopy(ESTIMATE)
    changed[category] = bad
    with pytest.raises(ValueError, match="estimate"):
        admit_mutation(OBSERVATION, changed, 300)


def test_overlap_and_insufficient_reserves_rejected() -> None:
    changed = deepcopy(ESTIMATE)
    changed["cleanup"][0]["id"] = "delayed-billing"
    with pytest.raises(ValueError, match="overlapping"):
        admit_mutation(OBSERVATION, changed, 300)
    for category in ["unbilled", "cleanup"]:
        changed = deepcopy(ESTIMATE)
        changed[category][0]["maximum_usd"] = "0.99"
        with pytest.raises(ValueError, match="reserve"):
            admit_mutation(OBSERVATION, changed, 300)
