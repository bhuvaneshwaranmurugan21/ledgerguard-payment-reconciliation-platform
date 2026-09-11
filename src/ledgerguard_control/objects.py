"""Version-aware object interface and genuine durable local implementation.

SQLite transactions are LOCAL evidence only. The separate AWS adapter must
qualify pagination, VersionId reads, request bounds, and effective permissions.
"""

from __future__ import annotations

import sqlite3
from abc import abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from ledgerguard.stage3.canonical import canonical_digest
from ledgerguard.stage3.paths import parse_s3_uri

from .contracts import ControlRejected


@dataclass(frozen=True, order=True)
class ObjectVersion:
    uri: str
    version_id: str
    is_latest: bool
    delete_marker: bool
    size_bytes: int


class VersionedObjects(Protocol):
    @abstractmethod
    def versions(self, prefix: str) -> tuple[ObjectVersion, ...]:
        raise NotImplementedError

    @abstractmethod
    def read(self, uri: str, version_id: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def chunks(self, uri: str, version_id: str) -> Iterator[bytes]:
        raise NotImplementedError


def snapshot(store: VersionedObjects, prefix: str) -> tuple[ObjectVersion, ...]:
    parent = parse_s3_uri(prefix)
    values = tuple(sorted(store.versions(prefix)))
    seen: set[tuple[str, str]] = set()
    latest: dict[str, int] = {}
    for value in values:
        location = parse_s3_uri(value.uri)
        if (
            location.bucket != parent.bucket
            or location.segments[: len(parent.segments)] != parent.segments
            or len(location.segments) <= len(parent.segments)
        ):
            raise ControlRejected("version inventory escaped prefix")
        if not value.version_id or value.version_id == "null":
            raise ControlRejected("version identity required")
        if (value.uri, value.version_id) in seen:
            raise ControlRejected("duplicate version identity")
        if (
            type(value.size_bytes) is not int
            or value.size_bytes < 0
            or type(value.is_latest) is not bool
            or type(value.delete_marker) is not bool
        ):
            raise ControlRejected("invalid version metadata")
        seen.add((value.uri, value.version_id))
        latest[value.uri] = latest.get(value.uri, 0) + int(value.is_latest)
    if any(count != 1 for count in latest.values()):
        raise ControlRejected("version inventory must have exactly one latest per key")
    return values


def snapshot_digest(versions: tuple[ObjectVersion, ...]) -> str:
    return canonical_digest([asdict(value) for value in versions])


def assert_unchanged(
    store: VersionedObjects,
    prefix: str,
    before: tuple[ObjectVersion, ...],
) -> None:
    if snapshot(store, prefix) != before:
        raise ControlRejected("object versions changed during validation")


class LocalVersionedObjects:
    """Append-only local versions backed by fsynced SQLite transactions.

    Separate instances/processes share durable state. Deletion creates a tombstone;
    it never erases an old version or makes a changed-and-restored inventory equal.
    """

    def __init__(self, path: Path):
        self.path = path
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    uri TEXT NOT NULL,
                    deleted INTEGER NOT NULL CHECK (deleted IN (0,1)),
                    body BLOB NOT NULL
                )
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                yield connection
        finally:
            connection.close()

    def _append(self, uri: str, raw: bytes, deleted: bool) -> str:
        parse_s3_uri(uri)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO versions (uri, deleted, body) VALUES (?, ?, ?)",
                (uri, int(deleted), raw),
            )
            return str(cursor.lastrowid)

    def put(self, uri: str, raw: bytes) -> str:
        return self._append(uri, raw, False)

    def delete(self, uri: str) -> str:
        return self._append(uri, b"", True)

    def versions(self, prefix: str) -> tuple[ObjectVersion, ...]:
        parse_s3_uri(prefix)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, uri, deleted, length(body),
                       sequence = (SELECT MAX(v.sequence) FROM versions v WHERE v.uri = o.uri)
                FROM versions o WHERE substr(uri, 1, ?) = ? ORDER BY uri, sequence
            """,
                (len(prefix) + 1, prefix + "/"),
            ).fetchall()
        return tuple(
            ObjectVersion(uri, str(seq), bool(latest), bool(deleted), size)
            for seq, uri, deleted, size, latest in rows
        )

    def read(self, uri: str, version_id: str) -> bytes:
        return b"".join(self.chunks(uri, version_id))

    def chunks(self, uri: str, version_id: str) -> Iterator[bytes]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sequence, deleted FROM versions "
                "WHERE uri = ? AND CAST(sequence AS TEXT) = ?",
                (uri, version_id),
            ).fetchone()
            if row is None or row[1]:
                raise ControlRejected("object version missing or deleted")
            with connection.blobopen("versions", "body", row[0], readonly=True) as blob:
                while chunk := blob.read(1024 * 1024):
                    yield chunk
