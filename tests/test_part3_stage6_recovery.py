from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

import tools.part3_stage6.recovery as recovery

COMMIT = "a" * 40
TREE = "b" * 40


def handoff() -> dict[str, Any]:
    return {
        "schema_version": "ledgerguard.part3-stage6-failure-handoff.v1",
        "source": {"commit": COMMIT, "tree": TREE},
        "target": {"account": recovery.ACCOUNT, "region": recovery.REGION},
        "run": {"id": "123", "attempt": "2"},
        "failure_type": "RuntimeError",
        "lease_was_acquired": True,
        "conditional_release_completed": False,
        "recovery_required": True,
        "force_unlock_attempted": False,
        "apply_calls": 0,
        "workload_calls": 0,
        "journal": [],
    }


class FakeCli:
    def __init__(self, item: dict[str, Any] | None) -> None:
        self.item = item

    def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
        assert operation == "DDB_GET_ITEM"
        return {} if self.item is None else {"Item": self.item}


def test_exact_failure_handoff_derives_owner_without_publishing_it() -> None:
    value = recovery.validate_failure_handoff(handoff(), source_commit=COMMIT, source_tree=TREE)
    assert value["owner_token"] == recovery.owner_token("123", "2", COMMIT)
    changed = handoff()
    changed["source"] = {"commit": "x", "tree": TREE}
    with pytest.raises(ValueError, match="source identity"):
        recovery.validate_failure_handoff(changed, source_commit="x", source_tree=TREE)
    changed = handoff()
    changed["run"] = []
    with pytest.raises(ValueError, match="run missing"):
        recovery.validate_failure_handoff(changed, source_commit=COMMIT, source_tree=TREE)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("schema_version",), "v2", "schema"),
        (("source", "tree"), "c" * 40, "source"),
        (("target", "region"), "us-east-1", "target"),
        (("run", "id"), "bad", "owner inputs"),
        (("lease_was_acquired",), False, "safety state"),
        (("conditional_release_completed",), True, "safety state"),
        (("force_unlock_attempted",), True, "safety state"),
        (("apply_calls",), 1, "safety state"),
    ],
)
def test_failure_handoff_drift_fails(path: tuple[str, ...], value: Any, message: str) -> None:
    changed = deepcopy(handoff())
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        recovery.validate_failure_handoff(changed, source_commit=COMMIT, source_tree=TREE)


def test_recovery_releases_only_exact_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    token = recovery.owner_token("123", "2", COMMIT)
    fake = FakeCli({"owner_token": {"S": token}})
    released: list[str] = []
    monkeypatch.setattr(
        recovery,
        "observe_backend",
        lambda *args: {"exact_state_absent": True, "lock_absent_before_lease": True},
    )
    monkeypatch.setattr(recovery, "release_lease", lambda cli, owner: released.append(owner))
    monkeypatch.setattr(
        recovery,
        "observe_clean_inventory",
        lambda cli: {"expected_operation_resources": 0, "other_ledgerguard_workload_resources": 0},
    )
    result = recovery.recover_owned_lease(
        cli=fake,  # type: ignore[arg-type]
        handoff=handoff(),
        source_commit=COMMIT,
        source_tree=TREE,
        kms_key_arn="key",
        control_plane={},
    )
    assert released == [token]
    assert result["owned_conditional_release"] is True
    assert result["force_unlock_attempted"] is False


def test_recovery_accepts_absence_and_rejects_foreign_or_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "observe_backend",
        lambda *args: {"exact_state_absent": True, "lock_absent_before_lease": True},
    )
    monkeypatch.setattr(
        recovery,
        "observe_clean_inventory",
        lambda cli: {"expected_operation_resources": 0, "other_ledgerguard_workload_resources": 0},
    )
    absent = recovery.recover_owned_lease(
        cli=FakeCli(None),  # type: ignore[arg-type]
        handoff=handoff(),
        source_commit=COMMIT,
        source_tree=TREE,
        kms_key_arn="key",
        control_plane={},
    )
    assert absent["lease_already_absent"] is True
    with pytest.raises(ValueError, match="different transaction"):
        recovery.recover_owned_lease(
            cli=FakeCli({"owner_token": {"S": "other"}}),  # type: ignore[arg-type]
            handoff=handoff(),
            source_commit=COMMIT,
            source_tree=TREE,
            kms_key_arn="key",
            control_plane={},
        )
    monkeypatch.setattr(
        recovery,
        "observe_backend",
        lambda *args: {"exact_state_absent": False, "lock_absent_before_lease": True},
    )
    with pytest.raises(ValueError, match="state or lock"):
        recovery.recover_owned_lease(
            cli=FakeCli(None),  # type: ignore[arg-type]
            handoff=handoff(),
            source_commit=COMMIT,
            source_tree=TREE,
            kms_key_arn="key",
            control_plane={},
        )
