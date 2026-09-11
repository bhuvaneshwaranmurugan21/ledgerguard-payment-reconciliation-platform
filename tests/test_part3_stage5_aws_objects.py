"""AWS request/response contract negatives only; no live gate uses these responses."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest

from ledgerguard_control.aws_objects import S3VersionedObjects
from ledgerguard_control.contracts import MAX_DOCUMENT_BYTES, ControlRejected
from ledgerguard_control.objects import snapshot


class Transport:
    def __init__(self, pages: list[dict[str, Any]], response: dict[str, Any]):
        self.pages = iter(pages)
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_object_versions(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("list_object_versions", request))
        return next(self.pages)

    def get_object(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("get_object", request))
        return self.response


def row(**change: Any) -> dict[str, Any]:
    return {"Key": "attempt/data", "VersionId": "v1", "Size": 4, "IsLatest": True, **change}


def test_complete_pagination_and_version_reads() -> None:
    body = BytesIO(b"data")
    transport = Transport(
        [
            {
                "Versions": [row()],
                "IsTruncated": True,
                "NextKeyMarker": "attempt/data",
                "NextVersionIdMarker": "v1",
            },
            {"DeleteMarkers": [row(VersionId="deleted", IsLatest=False)], "IsTruncated": False},
        ],
        {"Body": body, "VersionId": "v1", "ContentLength": 4},
    )
    store = S3VersionedObjects(transport)
    versions = snapshot(store, "s3://bucket-one/attempt")
    assert len(versions) == 2
    assert sum(value.delete_marker for value in versions) == 1
    assert store.read("s3://bucket-one/attempt/data", "v1") == b"data"
    assert body.closed
    assert transport.calls == [
        ("list_object_versions", {"Bucket": "bucket-one", "Prefix": "attempt/", "MaxKeys": 1000}),
        (
            "list_object_versions",
            {
                "Bucket": "bucket-one",
                "Prefix": "attempt/",
                "MaxKeys": 1000,
                "KeyMarker": "attempt/data",
                "VersionIdMarker": "v1",
            },
        ),
        ("get_object", {"Bucket": "bucket-one", "Key": "attempt/data", "VersionId": "v1"}),
    ]


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"IsTruncated": "false"},
        {"IsTruncated": True},
        {"IsTruncated": True, "NextKeyMarker": "", "NextVersionIdMarker": "v"},
        {"IsTruncated": True, "NextKeyMarker": "key", "NextVersionIdMarker": None},
        {"IsTruncated": False, "Versions": {}},
        {"IsTruncated": False, "Versions": [None]},
        {"IsTruncated": False, "Versions": [row(Key=1)]},
        {"IsTruncated": False, "Versions": [row(VersionId=None)]},
        {"IsTruncated": False, "Versions": [row(IsLatest=1)]},
        {"IsTruncated": False, "Versions": [row(Size=True)]},
    ],
)
def test_malformed_and_incomplete_page_rejected(page: dict[str, Any]) -> None:
    transport = Transport([page], {})
    with pytest.raises(ControlRejected):
        S3VersionedObjects(transport).versions("s3://bucket-one/attempt")


def test_repeated_page_markers_rejected() -> None:
    page = {"IsTruncated": True, "NextKeyMarker": "attempt/data", "NextVersionIdMarker": "v1"}
    transport = Transport([page, page], {})
    with pytest.raises(ControlRejected, match="repeated"):
        S3VersionedObjects(transport).versions("s3://bucket-one/attempt")


@pytest.mark.parametrize(
    "changes",
    [
        {"VersionId": "other"},
        {"DeleteMarker": True},
        {"ContentLength": True},
        {"ContentLength": None},
        {"ContentLength": -1},
        {"ContentLength": 3},
        {"ContentLength": 5},
    ],
)
def test_invalid_stream_metadata_and_lengths(changes: dict[str, Any]) -> None:
    body = BytesIO(b"data")
    transport = Transport([], {"Body": body, "VersionId": "v1", "ContentLength": 4, **changes})
    with pytest.raises(ControlRejected):
        S3VersionedObjects(transport).read("s3://bucket-one/attempt/data", "v1")
    assert body.closed


def test_unversioned_read_rejected_before_api_call() -> None:
    transport = Transport([], {})
    for version in ("", "null"):
        with pytest.raises(ControlRejected):
            S3VersionedObjects(transport).read("s3://bucket-one/attempt/data", version)
    assert transport.calls == []


def test_document_bound_and_streaming_large_object() -> None:
    raw = b"a" * (1024 * 1024 + 1)
    body = BytesIO(raw)
    transport = Transport([], {"Body": body, "VersionId": "v1", "ContentLength": len(raw)})
    store = S3VersionedObjects(transport)
    assert list(store.chunks("s3://bucket-one/attempt/data", "v1")) == [raw[:-1], raw[-1:]]
    assert body.closed
    body = BytesIO(b"a" * (MAX_DOCUMENT_BYTES + 1))
    transport.response = {"Body": body, "VersionId": "v1", "ContentLength": MAX_DOCUMENT_BYTES + 1}
    with pytest.raises(ControlRejected, match="byte bound"):
        store.read("s3://bucket-one/attempt/data", "v1")
    assert body.closed


class WrongStream:
    closed = False

    def read(self, size: int) -> str:
        return "text"

    def close(self) -> None:
        self.closed = True


def test_non_byte_stream_rejected_and_closed() -> None:
    body = WrongStream()
    transport = Transport([], {"Body": body, "VersionId": "v1", "ContentLength": 4})
    with pytest.raises(ControlRejected, match="non-byte"):
        S3VersionedObjects(transport).read("s3://bucket-one/attempt/data", "v1")
    assert body.closed
