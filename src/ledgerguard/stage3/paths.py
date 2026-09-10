"""Canonical S3 path confinement validated before Spark construction."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import Stage3Rejected

_BUCKET = re.compile(r"^(?!\d+\.\d+\.\d+\.\d+$)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
_ALIASES = frozenset({"latest", "current", "active"})


@dataclass(frozen=True, order=True)
class S3Location:
    bucket: str
    segments: tuple[str, ...]

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{'/'.join(self.segments)}"


def parse_s3_uri(uri: str) -> S3Location:
    if not isinstance(uri, str) or unicodedata.normalize("NFC", uri) != uri:
        raise Stage3Rejected("PATH_VIOLATION", "S3 URI must be NFC text")
    if any(ord(character) < 33 for character in uri) or "\\" in uri or "%" in uri:
        raise Stage3Rejected("PATH_VIOLATION", "S3 URI has unsafe encoding or character")
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc or parsed.query or parsed.fragment:
        raise Stage3Rejected("PATH_VIOLATION", "S3 URI must have only bucket and key")
    if parsed.username or parsed.password or parsed.port:
        raise Stage3Rejected("PATH_VIOLATION", "S3 URI authority is not canonical")
    bucket = parsed.hostname or ""
    if bucket != parsed.netloc or not _BUCKET.fullmatch(bucket):
        raise Stage3Rejected("PATH_VIOLATION", "invalid or noncanonical bucket")
    if not parsed.path.startswith("/") or parsed.path.endswith("/"):
        raise Stage3Rejected("PATH_VIOLATION", "key must be nonempty without trailing slash")
    segments = tuple(parsed.path[1:].split("/"))
    if not segments or any(not value or value in {".", ".."} for value in segments):
        raise Stage3Rejected("PATH_VIOLATION", "key has empty or traversal segment")
    if any(value.casefold() in _ALIASES for value in segments):
        raise Stage3Rejected("PATH_VIOLATION", "mutable path alias is forbidden")
    return S3Location(bucket, segments)


def _overlap(left: S3Location, right: S3Location) -> bool:
    if left.bucket != right.bucket:
        return False
    width = min(len(left.segments), len(right.segments))
    return left.segments[:width] == right.segments[:width]


def validate_job_paths(
    workload_bucket: str,
    run_id: str,
    attempt_id: str,
    input_prefix: str,
    candidate_prefix: str,
    evidence_prefix: str,
) -> tuple[S3Location, S3Location, S3Location]:
    if not _BUCKET.fullmatch(workload_bucket):
        raise Stage3Rejected("PATH_VIOLATION", "workload bucket is invalid")
    if not _IDENTIFIER.fullmatch(run_id) or not _IDENTIFIER.fullmatch(attempt_id):
        raise Stage3Rejected("PATH_VIOLATION", "run and attempt IDs must be canonical")
    locations = tuple(map(parse_s3_uri, (input_prefix, candidate_prefix, evidence_prefix)))
    if any(value.bucket != workload_bucket for value in locations):
        raise Stage3Rejected("PATH_VIOLATION", "wrong workload bucket")
    expected_input = ("runs", run_id, "inputs")
    expected_attempt = ("runs", run_id, "attempts", attempt_id)
    if locations[0].segments != expected_input:
        raise Stage3Rejected("PATH_VIOLATION", "input prefix is not run-bound")
    if locations[1].segments != (*expected_attempt, "candidates"):
        raise Stage3Rejected("PATH_VIOLATION", "candidate prefix is not attempt-bound")
    if locations[2].segments != (*expected_attempt, "evidence"):
        raise Stage3Rejected("PATH_VIOLATION", "evidence prefix is not attempt-bound")
    if any(
        _overlap(locations[left], locations[right])
        for left in range(len(locations))
        for right in range(left + 1, len(locations))
    ):
        raise Stage3Rejected("PATH_VIOLATION", "input/output prefixes overlap")
    return locations[0], locations[1], locations[2]
