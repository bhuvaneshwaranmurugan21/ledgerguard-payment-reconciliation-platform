"""Read-only S3 adapter. Transport tests do not establish live AWS permissions."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from ledgerguard.stage3.paths import parse_s3_uri

from .contracts import MAX_DOCUMENT_BYTES, ControlRejected
from .objects import ObjectVersion


class S3VersionedObjects:
    def __init__(self, client: Any):
        self.client = client

    def versions(self, prefix: str) -> tuple[ObjectVersion, ...]:
        location = parse_s3_uri(prefix)
        request: dict[str, Any] = {
            "Bucket": location.bucket,
            "Prefix": "/".join(location.segments) + "/",
            "MaxKeys": 1000,
        }
        result = []
        seen_tokens: set[tuple[str, str]] = set()
        while True:
            page = self.client.list_object_versions(**request)
            if type(page.get("IsTruncated")) is not bool:
                raise ControlRejected("missing S3 pagination status")
            for field, deleted in (("Versions", False), ("DeleteMarkers", True)):
                rows = page.get(field, [])
                if type(rows) is not list:
                    raise ControlRejected("invalid S3 version listing")
                for row in rows:
                    if (
                        type(row) is not dict
                        or type(row.get("Key")) is not str
                        or type(row.get("VersionId")) is not str
                        or type(row.get("IsLatest")) is not bool
                        or (not deleted and type(row.get("Size")) is not int)
                    ):
                        raise ControlRejected("incomplete S3 version metadata")
                    result.append(
                        ObjectVersion(
                            f"s3://{location.bucket}/{row['Key']}",
                            row["VersionId"],
                            row["IsLatest"],
                            deleted,
                            0 if deleted else row["Size"],
                        )
                    )
            if not page["IsTruncated"]:
                return tuple(result)
            key, version = page.get("NextKeyMarker"), page.get("NextVersionIdMarker")
            if type(key) is not str or not key or type(version) is not str:
                raise ControlRejected("missing S3 continuation markers")
            token = key, version
            if token in seen_tokens:
                raise ControlRejected("repeated S3 continuation markers")
            seen_tokens.add(token)
            request.update(KeyMarker=key, VersionIdMarker=version)

    def chunks(self, uri: str, version_id: str) -> Generator[bytes, None, None]:
        location = parse_s3_uri(uri)
        if not version_id or version_id == "null":
            raise ControlRejected("versioned read required")
        response = self.client.get_object(
            Bucket=location.bucket,
            Key="/".join(location.segments),
            VersionId=version_id,
        )
        body = response["Body"]
        try:
            if response.get("VersionId") != version_id or response.get("DeleteMarker", False):
                raise ControlRejected("S3 returned a different or deleted version")
            length = response.get("ContentLength")
            if type(length) is not int or length < 0:
                raise ControlRejected("invalid S3 content length")
            size = 0
            while True:
                chunk = body.read(1024 * 1024)
                if type(chunk) is not bytes:
                    raise ControlRejected("non-byte S3 stream")
                if not chunk:
                    break
                size += len(chunk)
                if size > length:
                    raise ControlRejected("S3 stream exceeds content length")
                yield chunk
            if size != length:
                raise ControlRejected("S3 stream truncated")
        finally:
            body.close()

    def read(self, uri: str, version_id: str) -> bytes:
        parts = []
        size = 0
        stream = self.chunks(uri, version_id)
        try:
            for chunk in stream:
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES:
                    raise ControlRejected("document read exceeds byte bound")
                parts.append(chunk)
        finally:
            stream.close()
        return b"".join(parts)
