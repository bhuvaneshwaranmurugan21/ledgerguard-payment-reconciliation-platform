from __future__ import annotations

from copy import deepcopy

import pytest

from tools.part3_stage6.preflight import validate_preflight

COMMIT = "a" * 40
TREE = "b" * 40
RECEIPT = "c" * 64
NOW = 1_800_000_000


def preflight() -> dict[str, object]:
    return {
        "schema_version": "ledgerguard.part3-stage6-live-preflight.v1",
        "classification": "FRESH_EXACT_MAIN_PLAN_ONLY_ADMISSION",
        "source": {
            "commit": COMMIT,
            "tree": TREE,
            "ref": "refs/heads/main",
            "event": "workflow_dispatch",
        },
        "target": {
            "account": "857229544428",
            "region": "ap-southeast-2",
            "operation_id": "release-qual1",
        },
        "completed_epoch": NOW - 10,
        "administrator_receipt_sha256": RECEIPT,
        "identity_iam": {
            key: True
            for key in (
                "expected_account",
                "expected_deploy_role",
                "trust_parity",
                "role_attachment_parity",
                "policy_document_parity",
                "effective_allow_probe",
                "effective_deny_probe",
                "restrictions_resolved",
            )
        },
        "backend": {
            key: True
            for key in (
                "exact_bucket",
                "exact_region",
                "versioning_enabled",
                "kms_key_exact",
                "public_access_blocked",
                "tls_only",
                "ownership_enforced",
                "lifecycle_admitted",
                "exact_state_absent",
                "lock_absent_before_lease",
            )
        },
        "lease": {
            key: True
            for key in (
                "shared_table_admitted",
                "exact_key",
                "prior_owner_absent",
                "conditionally_acquired",
                "owner_readback_equal",
            )
        },
        "quota": {
            key: True
            for key in ("iam", "lambda", "glue", "athena", "states", "dynamodb", "cloudwatch", "s3")
        },
        "inventory": {
            "pagination_complete": True,
            "access_denied": [],
            "expected_operation_resources": 0,
            "other_ledgerguard_workload_resources": 0,
            "active_glue_runs": 0,
            "active_athena_queries": 0,
            "active_state_machine_executions": 0,
        },
        "budget": {
            "currency": "USD",
            "known_gross_usd": "1.25",
            "reserved_stage6_exposure_usd": "0.05",
            "cleanup_reserve_usd": "1.00",
            "strict_ceiling_usd": "10",
            "cost_explorer_delayed": True,
        },
    }


def test_complete_fresh_preflight_is_admitted() -> None:
    result = validate_preflight(
        preflight(),
        source_commit=COMMIT,
        source_tree=TREE,
        administrator_receipt_sha256=RECEIPT,
        now_epoch=NOW,
    )
    assert result["classification"] == "S6_G01_PREFLIGHT_ADMITTED"
    assert result["known_plus_reserves_usd"] == "2.30"
    assert result["lease_acquired"] is True
    assert result["stage6_complete"] is False


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("source", "ref"), "refs/heads/feature", "source binding"),
        (("target", "region"), "us-east-1", "target differs"),
        (("identity_iam", "effective_deny_probe"), False, "identity/IAM"),
        (("backend", "lock_absent_before_lease"), False, "backend"),
        (("lease", "conditionally_acquired"), False, "lease"),
        (("quota", "glue"), False, "quota"),
        (("inventory", "active_glue_runs"), 1, "inventory"),
        (("budget", "cost_explorer_delayed"), False, "budget classification"),
        (("budget", "known_gross_usd"), "9.0", "strict cumulative"),
    ],
)
def test_preflight_mutations_fail(path: tuple[str, ...], value: object, match: str) -> None:
    changed = deepcopy(preflight())
    parent = changed
    for key in path[:-1]:
        parent = parent[key]  # type: ignore[assignment,index]
    parent[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValueError, match=match):
        validate_preflight(
            changed,
            source_commit=COMMIT,
            source_tree=TREE,
            administrator_receipt_sha256=RECEIPT,
            now_epoch=NOW,
        )


def test_preflight_rejects_staleness_receipt_and_extra_fields() -> None:
    changed = preflight()
    changed["completed_epoch"] = NOW - 901
    with pytest.raises(ValueError, match="stale"):
        validate_preflight(
            changed,
            source_commit=COMMIT,
            source_tree=TREE,
            administrator_receipt_sha256=RECEIPT,
            now_epoch=NOW,
        )
    changed = preflight()
    with pytest.raises(ValueError, match="receipt binding"):
        validate_preflight(
            changed,
            source_commit=COMMIT,
            source_tree=TREE,
            administrator_receipt_sha256="d" * 64,
            now_epoch=NOW,
        )
    changed = preflight()
    changed["lease"]["invented"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="lease admission"):
        validate_preflight(
            changed,
            source_commit=COMMIT,
            source_tree=TREE,
            administrator_receipt_sha256=RECEIPT,
            now_epoch=NOW,
        )


def test_preflight_rejects_schema_containers_time_and_budget_bounds() -> None:
    mutations = []
    changed = preflight()
    changed["schema_version"] = "wrong"
    mutations.append((changed, "schema"))
    changed = preflight()
    changed["classification"] = "wrong"
    mutations.append((changed, "classification"))
    changed = preflight()
    changed["source"] = []
    mutations.append((changed, "source must"))
    changed = preflight()
    changed["completed_epoch"] = True
    mutations.append((changed, "time invalid"))
    changed = preflight()
    changed["budget"] = []
    mutations.append((changed, "budget must"))
    changed = preflight()
    changed["budget"]["known_gross_usd"] = "not-decimal"  # type: ignore[index]
    mutations.append((changed, "amount invalid"))
    changed = preflight()
    changed["budget"]["cleanup_reserve_usd"] = "-1"  # type: ignore[index]
    mutations.append((changed, "bounds differ"))
    for changed, match in mutations:
        with pytest.raises(ValueError, match=match):
            validate_preflight(
                changed,
                source_commit=COMMIT,
                source_tree=TREE,
                administrator_receipt_sha256=RECEIPT,
                now_epoch=NOW,
            )
