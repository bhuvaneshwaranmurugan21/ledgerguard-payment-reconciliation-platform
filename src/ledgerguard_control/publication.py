"""Paged immutable snapshots of the accepted financial store.

Only a committed metadata root selects a reader snapshot. Preparation retains the
actual Part 2 history, requests, proofs and cases outside the runs lifecycle.
This is local controller integration, not an AWS write/permission qualification.
"""

from __future__ import annotations

import fcntl
import re
from abc import abstractmethod
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from ledgerguard.reconciliation.finalization import FinalizationStore
from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard.stage3.paths import parse_s3_uri

from .authority import LocalAuthority
from .contracts import IDENTIFIER, ControlRejected, strict_json
from .objects import VersionedObjects, snapshot

CHUNK_BYTES = 65536
PAGE_ITEMS = 32
DIGEST = r"[0-9a-f]{64}"
FILE_PATH = re.compile(
    rf"(?:control/HEAD|(?:objects|commits)/{DIGEST}\.json|"
    r"attempts/[a-z0-9][a-z0-9-]{7,63}/(?:request|outcome)\.json)"
)


class ImmutableObjects(VersionedObjects, Protocol):
    @abstractmethod
    def put_immutable(self, uri: str, raw: bytes) -> str:
        raise NotImplementedError


class FinancialSnapshots:
    def __init__(self, objects: ImmutableObjects, bucket: str, namespace: str):
        location = parse_s3_uri(f"s3://{bucket}/publications")
        if location.bucket != bucket:
            raise ControlRejected("invalid snapshot bucket")
        if re.fullmatch(IDENTIFIER, namespace) is None:
            raise ControlRejected("invalid snapshot namespace")
        self.objects = objects
        self.namespace = namespace
        self.prefix = f"s3://{bucket}/publications/{namespace}"

    def _prefix(self, digest: str) -> str:
        if type(digest) is not str or re.fullmatch(DIGEST, digest) is None:
            raise ControlRejected("invalid snapshot content address")
        return f"{self.prefix}/blobs/{digest}"

    def _put(self, raw: bytes) -> str:
        if len(raw) > CHUNK_BYTES:
            raise ControlRejected("snapshot object exceeds bound")
        digest = sha256(raw).hexdigest()
        self.objects.put_immutable(self._prefix(digest) + "/data", raw)
        return digest

    def _get(self, digest: str) -> bytes:
        prefix = self._prefix(digest)
        versions = snapshot(self.objects, prefix)
        if (
            len(versions) != 1
            or versions[0].uri != prefix + "/data"
            or versions[0].delete_marker
            or versions[0].size_bytes > CHUNK_BYTES
        ):
            raise ControlRejected("snapshot object missing, changed or oversized")
        version = versions[0]
        raw = self.objects.read(version.uri, version.version_id)
        if len(raw) != version.size_bytes or sha256(raw).hexdigest() != digest:
            raise ControlRejected("snapshot content identity differs")
        return raw

    def _tree(self, entries: Iterator[dict[str, Any]]) -> str:
        """Streaming fanout tree; only one partial page per level is retained."""
        levels: list[list[str]] = [[]]

        def add(digest: str, level: int) -> None:
            if level == len(levels):
                levels.append([])
            levels[level].append(digest)
            if len(levels[level]) == PAGE_ITEMS:
                node = self._put(canonical_bytes({"children": levels[level]}))
                levels[level] = []
                add(node, level + 1)

        page = []
        for entry in entries:
            page.append(entry)
            if len(page) == PAGE_ITEMS:
                add(self._put(canonical_bytes({"entries": page})), 0)
                page = []
        if page:
            add(self._put(canonical_bytes({"entries": page})), 0)
        if not any(levels):
            raise ControlRejected("empty financial snapshot")
        level = 0
        while level < len(levels) - 1:
            if levels[level]:
                add(self._put(canonical_bytes({"children": levels[level]})), level + 1)
            level += 1
        last = levels[-1]
        return last[0] if len(last) == 1 else self._put(canonical_bytes({"children": last}))

    def seal(self, store: FinalizationStore) -> str:
        """Seal a stable verified local candidate; this does not publish authority."""
        with (store.root / "locks/finalization.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            store.verify_history()
            head = store.read_head()
            if head is None:
                raise ControlRejected("financial snapshot has no commit")

            def entries() -> Iterator[dict[str, Any]]:
                for path in sorted(store.root.rglob("*")):
                    relative = path.relative_to(store.root).as_posix()
                    if path.is_symlink():
                        raise ControlRejected("snapshot contains a symlink")
                    if path.is_dir() or relative == "locks/finalization.lock":
                        continue
                    if FILE_PATH.fullmatch(relative) is None:
                        raise ControlRejected("unexpected financial snapshot file")
                    with path.open("rb") as stream:
                        offset = 0
                        while raw := stream.read(CHUNK_BYTES):
                            yield {
                                "path": relative,
                                "offset": offset,
                                "sha256": self._put(raw),
                                "size": len(raw),
                            }
                            offset += len(raw)
                        if not offset:
                            raise ControlRejected("empty financial snapshot file")

            index = self._tree(entries())
            return self._put(
                canonical_bytes(
                    {
                        "schema_version": "ledgerguard.financial-snapshot.v1",
                        "namespace": self.namespace,
                        "financial_head": head,
                        "index_sha256": index,
                    }
                )
            )

    def _entries(self, digest: str, depth: int = 0) -> Iterator[dict[str, Any]]:
        if depth > 32:
            raise ControlRejected("snapshot index depth exceeds bound")
        raw = self._get(digest)
        node = strict_json(raw)
        if canonical_bytes(node) != raw or set(node) not in ({"entries"}, {"children"}):
            raise ControlRejected("invalid snapshot index shape")
        rows = node.get("entries", node.get("children"))
        if type(rows) is not list or not 1 <= len(rows) <= PAGE_ITEMS:
            raise ControlRejected("invalid snapshot page size")
        if "children" in node:
            for child in rows:
                yield from self._entries(child, depth + 1)
        else:
            for row in rows:
                if type(row) is not dict or set(row) != {"path", "offset", "sha256", "size"}:
                    raise ControlRejected("invalid snapshot entry shape")
                yield row

    def open_committed(
        self,
        authority: LocalAuthority,
        repository: Path,
        destination: Path,
    ) -> FinalizationStore:
        """Resolve one root once, restore its exact bytes, then verify all history.

        The fresh destination is private to this call. A failed restore is never
        returned as a reader and cannot become an authoritative partial view.
        """
        commit = authority.read_root(self.namespace)
        if commit is None:
            raise ControlRejected("namespace has no published financial snapshot")
        root = strict_json(self._get(commit["preparation_sha256"]))
        if (
            set(root) != {"schema_version", "namespace", "financial_head", "index_sha256"}
            or root["schema_version"] != "ledgerguard.financial-snapshot.v1"
            or root["namespace"] != self.namespace
        ):
            raise ControlRejected("invalid financial snapshot root")
        self._prefix(root["financial_head"])
        destination.mkdir(parents=True, exist_ok=False)
        previous = ""
        offset = 0
        for entry in self._entries(root["index_sha256"]):
            name = entry["path"]
            if type(name) is not str or FILE_PATH.fullmatch(name) is None or name < previous:
                raise ControlRejected("snapshot path escaped or ordering differs")
            if name != previous:
                offset = 0
            if (
                type(entry["offset"]) is not int
                or entry["offset"] != offset
                or type(entry["size"]) is not int
                or not 1 <= entry["size"] <= CHUNK_BYTES
            ):
                raise ControlRejected("snapshot chunk offset or size differs")
            raw = self._get(entry["sha256"])
            if len(raw) != entry["size"]:
                raise ControlRejected("snapshot chunk size differs")
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb" if offset == 0 else "ab") as stream:
                stream.write(raw)
            offset += len(raw)
            previous = name
        store = FinalizationStore(repository, destination)
        if store.read_head() != root["financial_head"]:
            raise ControlRejected("restored financial head differs")
        store.verify_history()
        return store
