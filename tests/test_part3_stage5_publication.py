from __future__ import annotations

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_part2_stage6_finalization import _transaction_batch, _transaction_candidate

from ledgerguard.reconciliation.finalization import FinalizationStore
from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.authority import LocalAuthority
from ledgerguard_control.contracts import ControlRejected, strict_json
from ledgerguard_control.objects import LocalVersionedObjects
from ledgerguard_control.publication import CHUNK_BYTES, FinancialSnapshots, ImmutableObjects

ROOT = Path(__file__).resolve().parents[1]
OWNER = "arn:aws:states:ap-southeast-2:857229544428:execution:ledgerguard-test:execution-1"


def setup(tmp_path, count=1):
    objects = LocalVersionedObjects(tmp_path / "objects.sqlite")
    snapshots = FinancialSnapshots(objects, "ledgerguard-test", "finance-main")
    source = FinalizationStore(ROOT, tmp_path / "source")
    source.finalize(
        attempt_id="financial-1",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=_transaction_batch(
            *[
                _transaction_candidate(
                    payment_id=f"payment-{i}",
                    processor=100,
                    ledger=90,
                    status="EXCEPTION",
                    reasons=("PROCESSOR_LEDGER_MISMATCH",),
                )
                for i in range(count)
            ]
        ),
    )
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    authority.register("finance-main", "run-first", "a" * 64)
    attempt = authority.admit("finance-main", "run-first", "a" * 64, "attempt-1", OWNER)
    return objects, snapshots, source, authority, attempt


def test_immutable_create_concurrency_and_conflicts(tmp_path):
    store = LocalVersionedObjects(tmp_path / "objects.sqlite")
    uri = "s3://ledgerguard-test/publications/x"
    with ThreadPoolExecutor(max_workers=4) as pool:
        versions = list(pool.map(lambda _: store.put_immutable(uri, b"one"), range(8)))
    assert len(set(versions)) == 1
    with pytest.raises(ControlRejected, match="conflict"):
        store.put_immutable(uri, b"two")
    store.delete(uri)
    with pytest.raises(ControlRejected, match="conflict"):
        store.put_immutable(uri, b"one")


@pytest.mark.parametrize("count", [1, 1000])
def test_financial_snapshot_all_cases_replay_and_durable_reader(tmp_path, count):
    objects, snapshots, source, authority, attempt = setup(tmp_path, count)
    digest = snapshots.seal(source)
    assert snapshots.seal(source) == digest
    with pytest.raises(ControlRejected, match="no published"):
        snapshots.open_committed(authority, ROOT, tmp_path / "premature")
    committed = authority.publish(attempt, None, digest)
    assert authority.publish(attempt, None, digest) == committed
    reader = FinancialSnapshots(
        LocalVersionedObjects(objects.path), "ledgerguard-test", "finance-main"
    ).open_committed(LocalAuthority(authority.path), ROOT, tmp_path / "reader")
    assert reader.verify_history() == source.verify_history()
    assert len(reader.verify_history()["case_heads"]) == count
    assert reader.load_states() == source.load_states()
    assert all(
        "/publications/" in row.uri and row.size_bytes <= CHUNK_BYTES
        for row in objects.versions(snapshots.prefix)
    )
    assert authority.register("finance-main", "run-first", "a" * 64) == committed


def test_empty_and_unexpected_source_rejected(tmp_path):
    objects = LocalVersionedObjects(tmp_path / "o.sqlite")
    snapshots = FinancialSnapshots(objects, "ledgerguard-test", "finance-main")
    with pytest.raises(ControlRejected, match="no commit"):
        snapshots.seal(FinalizationStore(ROOT, tmp_path / "empty"))
    _, snapshots, source, _, _ = setup(tmp_path)
    (source.root / "unexpected").write_bytes(b"bad")
    with pytest.raises(ControlRejected, match="unexpected"):
        snapshots.seal(source)
    (source.root / "unexpected").unlink()
    (source.root / "link").symlink_to(source.root / "control/HEAD")
    with pytest.raises(ControlRejected, match="symlink"):
        snapshots.seal(source)
    (source.root / "link").unlink()
    (source.root / "attempts/empty-one").mkdir()
    (source.root / "attempts/empty-one/request.json").write_bytes(b"")
    with pytest.raises(ControlRejected, match="empty financial"):
        snapshots.seal(source)


def test_immutable_content_tampering_and_versions_rejected(tmp_path):
    objects, snapshots, source, authority, attempt = setup(tmp_path)
    digest = snapshots.seal(source)
    authority.publish(attempt, None, digest)
    uri = snapshots._prefix(digest) + "/data"
    with sqlite3.connect(objects.path) as db:
        original = db.execute("SELECT body FROM versions WHERE uri=?", (uri,)).fetchone()[0]
        db.execute("UPDATE versions SET body=? WHERE uri=?", (b"x" * len(original), uri))
    with pytest.raises(ControlRejected, match="content identity"):
        snapshots.open_committed(authority, ROOT, tmp_path / "corrupt")
    with sqlite3.connect(objects.path) as db:
        db.execute("UPDATE versions SET body=? WHERE uri=?", (original, uri))
    objects.put(uri, original)
    with pytest.raises(ControlRejected, match="changed"):
        snapshots.open_committed(authority, ROOT, tmp_path / "overwritten")


@pytest.mark.parametrize("value", ["bad", None, 1])
def test_invalid_addresses(tmp_path, value):
    snapshots = FinancialSnapshots(
        LocalVersionedObjects(tmp_path / "o"), "bucket-test", "namespace-one"
    )
    with pytest.raises(ControlRejected, match="address"):
        snapshots._get(value)


@pytest.mark.parametrize(
    "node",
    [
        {},
        {"children": []},
        {"entries": "bad"},
        {"entries": [None]},
        {"entries": [{}]},
        {"children": ["bad"]},
        {"entries": [{}] * 33},
    ],
)
def test_invalid_pages(tmp_path, node):
    snapshots = FinancialSnapshots(
        LocalVersionedObjects(tmp_path / "o"), "bucket-test", "namespace-one"
    )
    digest = snapshots._put(canonical_bytes(node))
    with pytest.raises(ControlRejected):
        list(snapshots._entries(digest))


def test_index_depth_empty_bound_and_noncanonical(tmp_path):
    snapshots = FinancialSnapshots(
        LocalVersionedObjects(tmp_path / "o"), "bucket-test", "namespace-one"
    )
    with pytest.raises(ControlRejected, match="empty"):
        snapshots._tree(iter([]))
    with pytest.raises(ControlRejected, match="exceeds"):
        snapshots._put(b"x" * (CHUNK_BYTES + 1))
    with pytest.raises(ControlRejected, match="depth"):
        list(snapshots._entries("a" * 64, 33))
    digest = snapshots._put(b'{"children": ["a"]}')
    with pytest.raises(ControlRejected, match="shape"):
        list(snapshots._entries(digest))
    with pytest.raises(ControlRejected, match="namespace"):
        FinancialSnapshots(snapshots.objects, "bucket-test", "../bad")
    with pytest.raises(ControlRejected, match="bucket"):
        FinancialSnapshots(snapshots.objects, "bucket-test/path", "namespace-one")
    with pytest.raises(NotImplementedError):
        ImmutableObjects.put_immutable(None, "unused", b"")


@pytest.mark.parametrize("count", [32, 1024, 1025, 1100])
def test_page_boundaries_preserve_complete_order(tmp_path, count):
    snapshots = FinancialSnapshots(
        LocalVersionedObjects(tmp_path / "o"), "bucket-test", "namespace-one"
    )
    entries = [{"path": str(i), "offset": 0, "sha256": "a" * 64, "size": 1} for i in range(count)]
    digest = snapshots._tree(iter(entries))
    assert list(snapshots._entries(digest)) == entries


@pytest.mark.parametrize(
    "fault",
    [
        "root-shape",
        "root-namespace",
        "root-head",
        "escape",
        "path-type",
        "reverse",
        "offset",
        "bool-offset",
        "bool-size",
        "zero-size",
        "size-disagreement",
        "head-mismatch",
    ],
)
def test_malformed_snapshot_never_returns_a_reader(tmp_path, fault):
    _, snapshots, source, authority, attempt = setup(tmp_path)
    root = strict_json(snapshots._get(snapshots.seal(source)))
    entries = list(snapshots._entries(root["index_sha256"]))
    if fault == "root-shape":
        root["extra"] = True
    elif fault == "root-namespace":
        root["namespace"] = "namespace-other"
    elif fault == "root-head":
        root["financial_head"] = "bad"
    elif fault == "head-mismatch":
        root["financial_head"] = "f" * 64
    elif fault == "escape":
        entries[0]["path"] = "../escape"
    elif fault == "path-type":
        entries[0]["path"] = 1
    elif fault == "reverse":
        entries.reverse()
    elif fault == "offset":
        entries[0]["offset"] = 1
    elif fault == "bool-offset":
        entries[0]["offset"] = False
    elif fault == "bool-size":
        entries[0]["size"] = True
    elif fault == "zero-size":
        entries[0]["size"] = 0
    else:
        entries[0]["size"] += 1
    root["index_sha256"] = snapshots._tree(iter(entries))
    authority.publish(attempt, None, snapshots._put(canonical_bytes(root)))
    with pytest.raises(ControlRejected):
        snapshots.open_committed(authority, ROOT, tmp_path / "reader")


def test_accepted_correction_survives_snapshot_and_exact_replay(tmp_path):
    from test_part3_stage1_correction import scenario

    case = scenario(tmp_path)
    source = case["store"]
    receipt = source.finalize(**case["args"])
    objects = LocalVersionedObjects(tmp_path / "objects.sqlite")
    snapshots = FinancialSnapshots(objects, "ledgerguard-test", "finance-main")
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    authority.register("finance-main", "correction-run-2", "a" * 64)
    attempt = authority.admit(
        "finance-main", "correction-run-2", "a" * 64, "attempt-correction", OWNER
    )
    authority.publish(attempt, None, snapshots.seal(source))
    reader = snapshots.open_committed(authority, ROOT, tmp_path / "reader")
    assert reader.finalize(**case["args"]) == receipt
    assert reader.load_states() == source.load_states()
    assert reader.verify_history() == source.verify_history()
    for reference in receipt.cases:
        assert reader.read_case_revision(reference.object_sha256) == source.read_case_revision(
            reference.object_sha256
        )


@pytest.mark.parametrize("after_write", [1, 3, 8])
def test_process_crash_during_preparation_leaves_no_partial_authority(tmp_path, after_write):
    objects, snapshots, source, authority, attempt = setup(tmp_path)
    script = """
import os, sys
from pathlib import Path
from ledgerguard.reconciliation.finalization import FinalizationStore
from ledgerguard_control.objects import LocalVersionedObjects
from ledgerguard_control.publication import FinancialSnapshots
class CrashAfterDurableWrite(LocalVersionedObjects):
    count = 0
    def put_immutable(self, uri, raw):
        version = super().put_immutable(uri, raw)
        self.count += 1
        if self.count == int(sys.argv[4]):
            os._exit(71)
        return version
objects = CrashAfterDurableWrite(Path(sys.argv[1]))
FinancialSnapshots(objects, "ledgerguard-test", "finance-main").seal(
    FinalizationStore(Path(sys.argv[2]), Path(sys.argv[3])))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(objects.path),
            str(ROOT),
            str(source.root),
            str(after_write),
        ],
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 71, completed.stderr
    assert authority.read_root("finance-main") is None
    with pytest.raises(ControlRejected, match="no published"):
        snapshots.open_committed(authority, ROOT, tmp_path / "premature")
    digest = snapshots.seal(source)
    authority.publish(attempt, None, digest)
    reader = snapshots.open_committed(authority, ROOT, tmp_path / "reader")
    assert reader.verify_history() == source.verify_history()
