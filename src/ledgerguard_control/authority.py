"""Durable registration/fencing and fixed-size namespace-root metadata CAS.

This component does not decide financial correctness. A publication payload is
a digest-bound pointer to separately qualified immutable preparation. The full
handler must preserve the accepted FinalizationStore's financial/correction rules.
SQLite proves local atomic metadata behavior; AWS requests are not live proof.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes, canonical_digest

from .contracts import IDENTIFIER, ControlRejected, strict_json


@dataclass(frozen=True)
class Attempt:
    namespace: str
    run_id: str
    identity_sha256: str
    attempt_id: str
    owner: str
    fence: int


def _id(value: str) -> None:
    if type(value) is not str or re.fullmatch(IDENTIFIER, value) is None:
        raise ControlRejected("invalid metadata identity")


def _digest(value: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ControlRejected("invalid metadata digest")


def _attempt(value: Attempt) -> None:
    for identity in (value.namespace, value.run_id, value.attempt_id):
        _id(identity)
    _digest(value.identity_sha256)
    if type(value.fence) is not int or not 1 <= value.fence <= 2**63 - 1:
        raise ControlRejected("invalid attempt fence")
    if (
        type(value.owner) is not str
        or re.fullmatch(
            r"arn:aws:states:ap-southeast-2:857229544428:execution:[A-Za-z0-9_-]{1,80}:[A-Za-z0-9_-]{1,80}",
            value.owner,
        )
        is None
    ):
        raise ControlRejected("invalid execution owner")


def commit_document(
    attempt: Attempt,
    predecessor: str | None,
    preparation_sha256: str,
) -> dict[str, Any]:
    _attempt(attempt)
    if predecessor is not None:
        _digest(predecessor)
    _digest(preparation_sha256)
    return {
        "schema_version": "ledgerguard.metadata-commit.v1",
        **asdict(attempt),
        "predecessor": predecessor,
        "preparation_sha256": preparation_sha256,
    }


class LocalAuthority:
    """Real serialized SQLite transactions with durable replay beyond token windows."""

    def __init__(self, path: Path):
        self.path = path
        with self._transaction() as connection:
            for statement in (
                "CREATE TABLE IF NOT EXISTS runs (namespace TEXT, run_id TEXT, identity TEXT, "
                "status TEXT, committed TEXT, active_attempt TEXT, PRIMARY KEY(namespace,run_id), "
                "UNIQUE(run_id))",
                "CREATE TABLE IF NOT EXISTS attempts (fence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "namespace TEXT, run_id TEXT, attempt_id TEXT, owner TEXT, status TEXT, "
                "UNIQUE(namespace,attempt_id))",
                "CREATE TABLE IF NOT EXISTS roots (namespace TEXT PRIMARY KEY, committed TEXT)",
                "CREATE TABLE IF NOT EXISTS commits (digest TEXT PRIMARY KEY, body BLOB NOT NULL)",
            ):
                connection.execute(statement)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection
        finally:
            connection.close()

    def register(self, namespace: str, run_id: str, identity: str) -> str | None:
        _id(namespace)
        _id(run_id)
        _digest(identity)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT identity, committed, namespace FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is not None:
                if row[0] != identity or row[2] != namespace:
                    raise ControlRejected("immutable run identity conflict")
                if row[1] is not None:
                    committed = self._read_commit(connection, namespace, str(row[1]))
                    if (
                        committed.get("run_id") != run_id
                        or committed.get("identity_sha256") != identity
                    ):
                        raise ControlRejected("terminal run points at another identity")
                    self._require_reachable(connection, namespace, str(row[1]))
                return row[1] if row[1] is None else str(row[1])
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, 'REGISTERED', NULL, NULL)",
                (namespace, run_id, identity),
            )
        return None

    def admit(
        self, namespace: str, run_id: str, identity: str, attempt_id: str, owner: str
    ) -> Attempt:
        _attempt(Attempt(namespace, run_id, identity, attempt_id, owner, 1))
        with self._transaction() as connection:
            run = connection.execute(
                "SELECT identity,status,active_attempt FROM runs WHERE namespace=? AND run_id=?",
                (namespace, run_id),
            ).fetchone()
            if run is None or run[0] != identity or run[1] == "COMMITTED":
                raise ControlRejected("run unavailable, changed or already committed")
            previous = connection.execute(
                "SELECT run_id,owner,status,fence FROM attempts WHERE namespace=? AND attempt_id=?",
                (namespace, attempt_id),
            ).fetchone()
            if previous is not None:
                if previous[:3] != (run_id, owner, "ACTIVE") or run[2] != attempt_id:
                    raise ControlRejected("attempt identity reuse or stale ownership")
                return Attempt(namespace, run_id, identity, attempt_id, owner, previous[3])
            if run[2] is not None:
                raise ControlRejected("another attempt owns the active run")
            cursor = connection.execute(
                "INSERT INTO attempts(namespace,run_id,attempt_id,owner,status) "
                "VALUES(?,?,?,?,'ACTIVE')",
                (namespace, run_id, attempt_id, owner),
            )
            connection.execute(
                "UPDATE runs SET active_attempt=? WHERE namespace=? AND run_id=?",
                (attempt_id, namespace, run_id),
            )
            return Attempt(
                namespace, run_id, identity, attempt_id, owner, int(cursor.lastrowid or 0)
            )

    def _require_owner(self, connection: sqlite3.Connection, attempt: Attempt) -> None:
        row = connection.execute(
            "SELECT r.identity,r.status,r.active_attempt,a.owner,a.status,a.fence "
            "FROM runs r JOIN attempts a ON r.namespace=a.namespace AND r.run_id=a.run_id "
            "WHERE r.namespace=? AND r.run_id=? AND a.attempt_id=?",
            (attempt.namespace, attempt.run_id, attempt.attempt_id),
        ).fetchone()
        expected = (
            attempt.identity_sha256,
            "REGISTERED",
            attempt.attempt_id,
            attempt.owner,
            "ACTIVE",
            attempt.fence,
        )
        if row != expected:
            raise ControlRejected("stale attempt fence or execution owner")

    def fail(self, attempt: Attempt) -> None:
        """Release only the current owned attempt; external recovery must prove termination."""
        _attempt(attempt)
        with self._transaction() as connection:
            self._require_owner(connection, attempt)
            connection.execute(
                "UPDATE attempts SET status='FAILED' WHERE fence=?", (attempt.fence,)
            )
            connection.execute(
                "UPDATE runs SET active_attempt=NULL WHERE namespace=? AND run_id=?",
                (attempt.namespace, attempt.run_id),
            )

    def publish(
        self,
        attempt: Attempt,
        predecessor: str | None,
        preparation_sha256: str,
        fault: Callable[[str], None] | None = None,
    ) -> str:
        document = commit_document(attempt, predecessor, preparation_sha256)
        digest = canonical_digest(document)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT body FROM commits WHERE digest=?", (digest,)
            ).fetchone()
            if existing is not None:
                if bytes(existing[0]) != canonical_bytes(document):
                    raise ControlRejected("persisted commit identity corrupted")
                run = connection.execute(
                    "SELECT status,committed FROM runs WHERE namespace=? AND run_id=?",
                    (attempt.namespace, attempt.run_id),
                ).fetchone()
                if run != ("COMMITTED", digest):
                    raise ControlRejected("commit has no terminal run authority")
                self._require_reachable(connection, attempt.namespace, digest)
                return digest
            self._require_owner(connection, attempt)
            root = connection.execute(
                "SELECT committed FROM roots WHERE namespace=?", (attempt.namespace,)
            ).fetchone()
            if (None if root is None else root[0]) != predecessor:
                raise ControlRejected("stale namespace predecessor")
            if fault is not None:
                fault("before_commit_record")
            connection.execute(
                "INSERT INTO commits VALUES (?,?)", (digest, canonical_bytes(document))
            )
            if fault is not None:
                fault("before_root")
            connection.execute(
                "INSERT INTO roots VALUES (?,?) ON CONFLICT(namespace) "
                "DO UPDATE SET committed=excluded.committed",
                (attempt.namespace, digest),
            )
            if fault is not None:
                fault("before_run_terminal")
            connection.execute(
                "UPDATE runs SET status='COMMITTED', committed=? WHERE namespace=? AND run_id=?",
                (digest, attempt.namespace, attempt.run_id),
            )
            connection.execute(
                "UPDATE attempts SET status='COMMITTED' WHERE fence=?", (attempt.fence,)
            )
            if fault is not None:
                fault("before_transaction_commit")
        if fault is not None:
            fault("after_transaction_commit")
        return digest

    def read_root(self, namespace: str) -> dict[str, Any] | None:
        _id(namespace)
        with self._transaction() as connection:
            root = connection.execute(
                "SELECT committed FROM roots WHERE namespace=?", (namespace,)
            ).fetchone()
            if root is None:
                return None
            return self._read_commit(connection, namespace, str(root[0]))

    def _read_commit(
        self,
        connection: sqlite3.Connection,
        namespace: str,
        digest: str,
    ) -> dict[str, Any]:
        row = connection.execute("SELECT body FROM commits WHERE digest=?", (digest,)).fetchone()
        if row is None:
            raise ControlRejected("authoritative root has no commit")
        value = strict_json(bytes(row[0]))
        if canonical_digest(value) != digest or value.get("namespace") != namespace:
            raise ControlRejected("authoritative commit integrity mismatch")
        return value

    def _require_reachable(
        self,
        connection: sqlite3.Connection,
        namespace: str,
        digest: str,
    ) -> None:
        row = connection.execute(
            "SELECT committed FROM roots WHERE namespace=?", (namespace,)
        ).fetchone()
        head = None if row is None else row[0]
        seen = set()
        while head is not None:
            if head in seen:
                raise ControlRejected("commit ancestry cycle")
            seen.add(head)
            value = self._read_commit(connection, namespace, head)
            if head == digest:
                return
            head = value["predecessor"]
        raise ControlRejected("commit is not reachable from authoritative root")


def publication_transaction(
    table: str,
    attempt: Attempt,
    predecessor: str | None,
    preparation_sha256: str,
) -> dict[str, Any]:
    """Build exactly four DynamoDB items independent of financial dataset size.

    The DynamoDB run admission adapter must bind owner/fence on the run and attempt
    items before this request. Preparing this shape is not an AWS transaction receipt.
    """
    if re.fullmatch(r"ledgerguard-[a-z0-9-]+-control", table) is None:
        raise ControlRejected("invalid control table")
    document = commit_document(attempt, predecessor, preparation_sha256)
    digest = canonical_digest(document)
    namespace = f"NAMESPACE#{attempt.namespace}"
    run_key = {"pk": {"S": f"RUN#{attempt.run_id}"}, "sk": {"S": "REGISTRATION"}}
    token = {"pk": {"S": f"RUN#{attempt.run_id}"}, "sk": {"S": f"ATTEMPT#{attempt.attempt_id}"}}
    root_values = {":commit": {"S": digest}}
    root_condition = "attribute_not_exists(#pk)"
    root_names = {"#pk": "pk", "#head": "head"}
    if predecessor is not None:
        root_values[":previous"] = {"S": predecessor}
        root_condition = "#head = :previous"
        del root_names["#pk"]
    return {
        "TransactItems": [
            {
                "Update": {
                    "TableName": table,
                    "Key": {"pk": {"S": namespace}, "sk": {"S": "ROOT"}},
                    "UpdateExpression": "SET #head = :commit",
                    "ConditionExpression": root_condition,
                    "ExpressionAttributeNames": root_names,
                    "ExpressionAttributeValues": root_values,
                }
            },
            {
                "Put": {
                    "TableName": table,
                    "Item": {
                        "pk": {"S": namespace},
                        "sk": {"S": f"COMMIT#{digest}"},
                        "document": {"S": canonical_bytes(document).decode()},
                    },
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
            {
                "Update": {
                    "TableName": table,
                    "Key": run_key,
                    "UpdateExpression": "SET #status = :committed, #commit = :commit",
                    "ConditionExpression": "#namespace = :namespace AND #identity = :identity "
                    "AND #status = :registered "
                    "AND #attempt = :attempt AND #owner = :owner AND #fence = :fence",
                    "ExpressionAttributeNames": {
                        "#identity": "identity",
                        "#status": "status",
                        "#attempt": "active_attempt",
                        "#owner": "owner",
                        "#fence": "fence",
                        "#commit": "commit",
                        "#namespace": "namespace",
                    },
                    "ExpressionAttributeValues": {
                        ":namespace": {"S": attempt.namespace},
                        ":identity": {"S": attempt.identity_sha256},
                        ":registered": {"S": "REGISTERED"},
                        ":committed": {"S": "COMMITTED"},
                        ":commit": {"S": digest},
                        ":attempt": {"S": attempt.attempt_id},
                        ":owner": {"S": attempt.owner},
                        ":fence": {"N": str(attempt.fence)},
                    },
                }
            },
            {
                "Update": {
                    "TableName": table,
                    "Key": token,
                    "UpdateExpression": "SET #status = :committed",
                    "ConditionExpression": "#status = :active AND #owner = :owner "
                    "AND #fence = :fence",
                    "ExpressionAttributeNames": {
                        "#status": "status",
                        "#owner": "owner",
                        "#fence": "fence",
                    },
                    "ExpressionAttributeValues": {
                        ":active": {"S": "ACTIVE"},
                        ":committed": {"S": "COMMITTED"},
                        ":owner": {"S": attempt.owner},
                        ":fence": {"N": str(attempt.fence)},
                    },
                }
            },
        ],
    }
