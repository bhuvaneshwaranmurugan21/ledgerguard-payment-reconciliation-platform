"""Strict version-aware S3 transports.

Transport tests establish request/response semantics only.  They do not establish
effective AWS permissions or managed-service persistence.
"""

from __future__ import annotations

import base64
from collections.abc import Generator
from hashlib import sha256
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


class S3ImmutableObjects(S3VersionedObjects):
    """Create-or-verify immutable publication objects in one frozen bucket.

    ``IfNoneMatch='*'`` chooses one concurrent creator.  Both the winner and a
    precondition loser must then observe exactly one non-deleted version and read
    back identical bytes.  Versioning therefore detects overwrite/deletion history;
    it is never treated as immutability by itself.
    """

    def __init__(self, client: Any, bucket: str):
        super().__init__(client)
        location = parse_s3_uri(f"s3://{bucket}/publications")
        if location.bucket != bucket:
            raise ControlRejected("invalid immutable-object bucket")
        self.bucket = bucket

    @staticmethod
    def _precondition_failed(error: Exception) -> bool:
        response = getattr(error, "response", None)
        if type(response) is not dict:
            return False
        detail = response.get("Error")
        return type(detail) is dict and detail.get("Code") in {"PreconditionFailed", "412"}

    def _exact_history(self, key: str) -> tuple[ObjectVersion, ...]:
        request: dict[str, Any] = {"Bucket": self.bucket, "Prefix": key, "MaxKeys": 1000}
        seen: set[tuple[str, str]] = set()
        rows: list[ObjectVersion] = []
        for _ in range(16):
            page = self.client.list_object_versions(**request)
            if type(page) is not dict or type(page.get("IsTruncated")) is not bool:
                raise ControlRejected("invalid immutable-object version page")
            for field, deleted in (("Versions", False), ("DeleteMarkers", True)):
                values = page.get(field, [])
                if type(values) is not list:
                    raise ControlRejected("invalid immutable-object version inventory")
                for value in values:
                    if type(value) is not dict or value.get("Key") != key:
                        continue
                    version_id = value.get("VersionId")
                    latest = value.get("IsLatest")
                    size = 0 if deleted else value.get("Size")
                    if (
                        type(version_id) is not str
                        or not version_id
                        or version_id == "null"
                        or type(latest) is not bool
                        or type(size) is not int
                        or size < 0
                    ):
                        raise ControlRejected("invalid immutable-object version metadata")
                    rows.append(
                        ObjectVersion(
                            f"s3://{self.bucket}/{key}", version_id, latest, deleted, size
                        )
                    )
                    if len(rows) > 16:
                        raise ControlRejected("immutable-object version history exceeds bound")
            if not page["IsTruncated"]:
                return tuple(sorted(rows))
            key_marker = page.get("NextKeyMarker")
            version_marker = page.get("NextVersionIdMarker")
            if (
                type(key_marker) is not str
                or not key_marker
                or type(version_marker) is not str
            ):
                raise ControlRejected("invalid immutable-object continuation marker")
            marker = key_marker, version_marker
            if marker in seen:
                raise ControlRejected("invalid immutable-object continuation marker")
            seen.add(marker)
            request.update(KeyMarker=key_marker, VersionIdMarker=version_marker)
        raise ControlRejected("immutable-object pagination exceeds bound")

    def put_immutable(self, uri: str, raw: bytes) -> str:
        location = parse_s3_uri(uri)
        key = "/".join(location.segments)
        if (
            location.bucket != self.bucket
            or not key.startswith("publications/")
            or type(raw) is not bytes
            or not 1 <= len(raw) <= MAX_DOCUMENT_BYTES
        ):
            raise ControlRejected("immutable publication address or body differs")
        checksum = base64.b64encode(sha256(raw).digest()).decode()
        try:
            response = self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=raw,
                ContentLength=len(raw),
                ContentType="application/json",
                ChecksumAlgorithm="SHA256",
                ChecksumSHA256=checksum,
                IfNoneMatch="*",
            )
            if (
                type(response) is not dict
                or type(response.get("VersionId")) is not str
                or response["VersionId"] == "null"
                or response.get("ChecksumSHA256") != checksum
            ):
                raise ControlRejected("immutable put response lacks exact version/checksum")
        except Exception as error:
            if not self._precondition_failed(error):
                raise
        history = self._exact_history(key)
        if (
            len(history) != 1
            or not history[0].is_latest
            or history[0].delete_marker
            or history[0].size_bytes != len(raw)
        ):
            raise ControlRejected("immutable object has overwrite or deletion history")
        if self.read(uri, history[0].version_id) != raw:
            raise ControlRejected("immutable object bytes differ")
        return history[0].version_id
