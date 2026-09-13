"""Actual durable metadata transactions, concurrent CAS and process-crash recovery."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage3.canonical import canonical_bytes, canonical_digest
from ledgerguard_control.authority import (
    Attempt,
    LocalAuthority,
    commit_document,
    publication_transaction,
)
from ledgerguard_control.contracts import ControlRejected

OWNER = "arn:aws:states:ap-southeast-2:857229544428:execution:ledgerguard-test:execution-one"


def admitted(
    store: LocalAuthority, run: str = "run-first", attempt: str = "attempt-first"
) -> Attempt:
    assert store.register("namespace-one", run, "a" * 64) is None
    return store.admit("namespace-one", run, "a" * 64, attempt, OWNER)


def test_registration_replay_fencing_and_changed_identity(tmp_path: Path) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    token = admitted(store)
    assert admitted(store) == token
    assert store.read_root(token.namespace) is None
    with pytest.raises(ControlRejected, match="immutable"):
        store.register(token.namespace, token.run_id, "b" * 64)
    with pytest.raises(ControlRejected, match="immutable"):
        store.register("namespace-other", token.run_id, token.identity_sha256)
    with pytest.raises(ControlRejected, match="another attempt"):
        store.admit(token.namespace, token.run_id, token.identity_sha256, "attempt-second", OWNER)
    with pytest.raises(ControlRejected, match="attempt identity reuse"):
        store.admit(
            token.namespace, token.run_id, token.identity_sha256, token.attempt_id, OWNER + "-other"
        )
    with pytest.raises(ControlRejected, match="stale attempt"):
        store.fail(replace(token, fence=token.fence + 1))
    store.fail(token)
    with pytest.raises(ControlRejected, match="attempt identity reuse"):
        store.admit(token.namespace, token.run_id, token.identity_sha256, token.attempt_id, OWNER)
    next_token = store.admit(
        token.namespace, token.run_id, token.identity_sha256, "attempt-second", OWNER
    )
    assert next_token.fence > token.fence
    with pytest.raises(ControlRejected, match="stale attempt"):
        store.publish(token, None, "c" * 64)
    digest = store.publish(next_token, None, "c" * 64)
    assert store.register(token.namespace, token.run_id, token.identity_sha256) == digest
    with pytest.raises(ControlRejected, match="already committed"):
        store.admit(token.namespace, token.run_id, token.identity_sha256, "attempt-third", OWNER)
    assert store.publish(next_token, None, "c" * 64) == digest
    with pytest.raises(ControlRejected):
        store.publish(next_token, None, "d" * 64)


def test_missing_and_changed_registration_cannot_admit_attempt(tmp_path: Path) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    with pytest.raises(ControlRejected):
        store.admit("namespace-one", "run-first", "a" * 64, "attempt-first", OWNER)
    store.register("namespace-one", "run-first", "a" * 64)
    with pytest.raises(ControlRejected):
        store.admit("namespace-one", "run-first", "b" * 64, "attempt-first", OWNER)


def test_durable_replay_after_other_run_advances_namespace(tmp_path: Path) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    first = admitted(store)
    digest = store.publish(first, None, "b" * 64)
    second = admitted(store, "run-second", "attempt-second")
    later = store.publish(second, digest, "c" * 64)
    reopened = LocalAuthority(store.path)
    assert reopened.publish(first, None, "b" * 64) == digest
    assert canonical_digest(reopened.read_root(first.namespace)) == later
    assert reopened.read_root(first.namespace)["predecessor"] == digest


def test_concurrent_predecessor_cas_has_one_complete_winner(tmp_path: Path) -> None:
    path = tmp_path / "authority.sqlite"
    store = LocalAuthority(path)
    first = admitted(store)
    second = admitted(store, "run-second", "attempt-second")

    def publish(token: Attempt) -> str:
        try:
            return LocalAuthority(path).publish(token, None, "b" * 64)
        except ControlRejected as error:
            assert "stale namespace" in str(error)
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, (first, second)))
    assert results.count("CONFLICT") == 1
    winner = next(result for result in results if result != "CONFLICT")
    assert canonical_digest(store.read_root("namespace-one")) == winner
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM commits").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM runs WHERE status='COMMITTED'").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "point",
    [
        "before_commit_record",
        "before_root",
        "before_run_terminal",
        "before_transaction_commit",
        "after_transaction_commit",
    ],
)
def test_real_process_crash_never_exposes_partial_metadata(tmp_path: Path, point: str) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    token = admitted(store)
    script = """
import json,os,sys
from pathlib import Path
from ledgerguard_control.authority import Attempt,LocalAuthority
def fault(point):
    if point == sys.argv[3]:
        os._exit(71)
store=LocalAuthority(Path(sys.argv[1]))
store.publish(Attempt(**json.loads(sys.argv[2])),None,'b'*64,fault=fault)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    process = subprocess.run(
        [sys.executable, "-c", script, str(store.path), json.dumps(asdict(token)), point],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 71, process.stderr
    reopened = LocalAuthority(store.path)
    expected_committed = point == "after_transaction_commit"
    assert (reopened.read_root(token.namespace) is not None) is expected_committed
    with sqlite3.connect(store.path) as connection:
        commits = connection.execute("SELECT count(*) FROM commits").fetchone()[0]
        terminal = connection.execute("SELECT status FROM runs").fetchone()[0]
        assert commits == int(expected_committed)
        assert (terminal == "COMMITTED") is expected_committed
    digest = reopened.publish(token, None, "b" * 64)
    assert digest == canonical_digest(reopened.read_root(token.namespace))


def test_independent_namespace_state_remains_unchanged(tmp_path: Path) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    first = admitted(store)
    initial = store.publish(first, None, "b" * 64)
    store.register("namespace-two", "run-other", "c" * 64)
    other = store.admit("namespace-two", "run-other", "c" * 64, "attempt-other", OWNER)
    store.publish(other, None, "d" * 64)
    assert canonical_digest(store.read_root("namespace-one")) == initial


@pytest.mark.parametrize(
    "change",
    [
        {"namespace": "bad"},
        {"run_id": "run/escape"},
        {"identity_sha256": "bad"},
        {"owner": "other-account"},
        {"fence": 0},
        {"fence": True},
        {"fence": 2**63},
    ],
)
def test_invalid_token_rejected_before_mutation(tmp_path: Path, change: dict[str, Any]) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    token = admitted(store)
    with pytest.raises(ControlRejected):
        store.publish(replace(token, **change), None, "b" * 64)
    assert store.read_root(token.namespace) is None


def test_invalid_predecessor_or_preparation_rejected(tmp_path: Path) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    token = admitted(store)
    with pytest.raises(ControlRejected, match="digest"):
        store.publish(token, "bad", "b" * 64)
    with pytest.raises(ControlRejected, match="digest"):
        store.publish(token, None, "bad")


@pytest.mark.parametrize("fault", ["body", "terminal", "unreachable", "missing"])
def test_corrupt_or_unreachable_record_cannot_be_replayed_as_authority(
    tmp_path: Path,
    fault: str,
) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    token = admitted(store)
    digest = store.publish(token, None, "b" * 64)
    with sqlite3.connect(store.path) as connection:
        if fault == "body":
            connection.execute("UPDATE commits SET body=?", (b"{}",))
        elif fault == "terminal":
            connection.execute("UPDATE runs SET status='REGISTERED'")
        elif fault == "unreachable":
            connection.execute("DELETE FROM roots")
        else:
            connection.execute("DELETE FROM commits WHERE digest=?", (digest,))
    with pytest.raises(ControlRejected):
        if fault == "missing":
            store.read_root(token.namespace)
        else:
            store.publish(token, None, "b" * 64)


def test_fixed_four_item_transaction_binds_fence_owner_predecessor_and_root(tmp_path: Path) -> None:
    token = admitted(LocalAuthority(tmp_path / "authority.sqlite"))
    for predecessor in (None, "c" * 64):
        request = publication_transaction("ledgerguard-test-control", token, predecessor, "b" * 64)
        operations = request["TransactItems"]
        assert [next(iter(item)) for item in operations] == ["Update", "Put", "Update", "Update"]
        assert (
            len(
                {
                    canonical_bytes(
                        item[next(iter(item))].get("Key", item[next(iter(item))].get("Item"))
                    )
                    for item in operations
                }
            )
            == 4
        )
        root, commit, run, attempt = [item[next(iter(item))] for item in operations]
        document = commit_document(token, predecessor, "b" * 64)
        assert root["ExpressionAttributeValues"][":commit"]["S"] == canonical_digest(document)
        assert json.loads(commit["Item"]["document"]["S"]) == document
        assert "attribute_not_exists" in commit["ConditionExpression"]
        assert ":fence" in run["ConditionExpression"] and ":owner" in run["ConditionExpression"]
        assert ":namespace" in run["ConditionExpression"]
        assert attempt["ExpressionAttributeValues"][":fence"] == {"N": str(token.fence)}
        assert ":active" in attempt["ConditionExpression"]
        assert len(canonical_bytes(request)) < 16384
        assert (":previous" in root["ExpressionAttributeValues"]) is (predecessor is not None)
    with pytest.raises(ControlRejected, match="table"):
        publication_transaction("unrelated-control", token, None, "b" * 64)


def test_fault_schedule_covers_each_write_and_commit_response_boundary(tmp_path: Path) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    token = admitted(store)
    phases: list[str] = []
    store.publish(token, None, "b" * 64, fault=phases.append)
    assert phases == [
        "before_commit_record",
        "before_root",
        "before_run_terminal",
        "before_transaction_commit",
        "after_transaction_commit",
    ]
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE commits SET body=?", (b"{}",))
    with pytest.raises(ControlRejected, match="integrity mismatch"):
        store.read_root(token.namespace)


def test_defensive_cycle_guard_with_explicit_traversal_fault(tmp_path: Path) -> None:
    # This injected malformed traversal is a guard unit test, not proof that a
    # cyclic content-addressed history can be persisted with valid SHA256 hashes.
    class CyclicTraversal(LocalAuthority):
        def _read_commit(
            self,
            connection: sqlite3.Connection,
            namespace: str,
            digest: str,
        ) -> dict[str, Any]:
            return {"predecessor": digest}

    store = CyclicTraversal(tmp_path / "authority.sqlite")
    with store._transaction() as connection:
        connection.execute("INSERT INTO roots VALUES (?,?)", ("namespace-one", "a" * 64))
        with pytest.raises(ControlRejected, match="ancestry cycle"):
            store._require_reachable(connection, "namespace-one", "b" * 64)


def test_registration_replay_cannot_return_another_runs_commit(tmp_path: Path) -> None:
    store = LocalAuthority(tmp_path / "authority.sqlite")
    first = admitted(store)
    first_commit = store.publish(first, None, "b" * 64)
    second = admitted(store, "run-second", "attempt-second")
    second_commit = store.publish(second, first_commit, "c" * 64)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE runs SET committed=? WHERE run_id=?", (second_commit, first.run_id)
        )
    with pytest.raises(ControlRejected, match="another identity"):
        store.register(first.namespace, first.run_id, first.identity_sha256)
