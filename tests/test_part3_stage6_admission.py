from __future__ import annotations

from copy import deepcopy

import pytest

from tools.part3_stage6.admission import validate_administrator_receipt

COMMIT = "a" * 40
TREE = "b" * 40
NOW = 1_800_000_000


def receipt() -> dict[str, object]:
    return {
        "schema_version": "ledgerguard.part3-stage6-administrator-receipt.v1",
        "classification": "SUCCESSOR_IAM_INSTALLED_AND_EFFECTIVELY_ADMITTED",
        "source": {"commit": COMMIT, "tree": TREE},
        "target": {
            "account": "857229544428",
            "region": "ap-southeast-2",
            "operation_id": "release-qual1",
        },
        "timing": {"completed_epoch": NOW - 60},
        "bindings": {
            "private_packet_sha256": "1" * 64,
            "pre_change_snapshot_sha256": "2" * 64,
            "mutation_journal_sha256": "3" * 64,
            "post_change_snapshot_sha256": "4" * 64,
            "rollback_packet_sha256": "5" * 64,
        },
        "checks": {
            "separate_administrator_identity": True,
            "pre_change_snapshot_complete": True,
            "exact_policy_documents_installed": True,
            "exact_role_attachments_installed": True,
            "trust_path_session_boundary_parity": True,
            "effective_permissions_verified": True,
            "policy_simulation_allowed": True,
            "policy_simulation_denials_verified": True,
            "access_analyzer_zero_findings": True,
            "managed_policy_quota_headroom": True,
            "service_quota_headroom": True,
            "rollback_ready": True,
            "executor_did_not_self_remediate": True,
        },
        "restrictions": {
            key: {"visibility": "OBSERVED", "admitted": True}
            for key in (
                "organization_scp",
                "permissions_boundary",
                "session_policy",
                "resource_policy",
            )
        },
        "calls": {
            "administrator_iam_mutations": 12,
            "executor_iam_mutations": 0,
            "workload_calls": 0,
        },
    }


def test_admits_fresh_complete_separate_transaction() -> None:
    result = validate_administrator_receipt(
        receipt(), source_commit=COMMIT, source_tree=TREE, now_epoch=NOW
    )
    assert result["restrictions_resolved"] is True
    assert result["effective_permissions_verified"] is True
    assert result["workload_calls"] == 0
    assert result["stage6_complete"] is False


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("classification",), "OBSERVATION_ONLY", "not admitted"),
        (("source", "commit"), "c" * 40, "source binding"),
        (("target", "account"), "000000000000", "target differs"),
        (("bindings", "private_packet_sha256"), "bad", "binding invalid"),
        (("checks", "effective_permissions_verified"), False, "check inventory"),
        (("restrictions", "organization_scp", "visibility"), "UNKNOWN", "visibility"),
        (("restrictions", "session_policy", "admitted"), False, "not admitted"),
        (("calls", "workload_calls"), 1, "prohibited boundary"),
        (("calls", "executor_iam_mutations"), 1, "prohibited boundary"),
        (("calls", "administrator_iam_mutations"), 0, "not evidenced"),
    ],
)
def test_rejects_incomplete_or_unsafe_transaction(
    path: tuple[str, ...], value: object, match: str
) -> None:
    changed = deepcopy(receipt())
    parent = changed
    for key in path[:-1]:
        parent = parent[key]  # type: ignore[assignment,index]
    parent[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValueError, match=match):
        validate_administrator_receipt(
            changed, source_commit=COMMIT, source_tree=TREE, now_epoch=NOW
        )


def test_rejects_stale_future_and_check_inventory_drift() -> None:
    for completed in (NOW - 3601, NOW + 61):
        changed = receipt()
        changed["timing"]["completed_epoch"] = completed  # type: ignore[index]
        with pytest.raises(ValueError, match="stale or future"):
            validate_administrator_receipt(
                changed, source_commit=COMMIT, source_tree=TREE, now_epoch=NOW
            )
    changed = receipt()
    changed["checks"]["invented"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="check inventory"):
        validate_administrator_receipt(
            changed, source_commit=COMMIT, source_tree=TREE, now_epoch=NOW
        )


def test_rejects_schema_container_source_time_and_restriction_inventory() -> None:
    cases = []
    changed = receipt()
    changed["schema_version"] = "wrong"
    cases.append((changed, "schema"))
    changed = receipt()
    changed["source"] = []
    cases.append((changed, "source must"))
    changed = receipt()
    cases.append((changed, "source identity"))
    changed = receipt()
    changed["timing"]["completed_epoch"] = True  # type: ignore[index]
    cases.append((changed, "completion time"))
    changed = receipt()
    changed["restrictions"].pop("resource_policy")  # type: ignore[union-attr]
    cases.append((changed, "restriction inventory"))
    for index, (changed, match) in enumerate(cases):
        commit = "bad" if index == 2 else COMMIT
        if index == 2:
            changed["source"]["commit"] = "bad"  # type: ignore[index]
        with pytest.raises(ValueError, match=match):
            validate_administrator_receipt(
                changed, source_commit=commit, source_tree=TREE, now_epoch=NOW
            )
