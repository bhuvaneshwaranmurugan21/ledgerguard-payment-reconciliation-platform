"""Stage 3 canonical identities independent from output paths and wall clocks."""

from __future__ import annotations

import json
import unicodedata
from hashlib import sha256
from typing import Any

from .errors import Stage3Rejected


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if any(ord(character) < 32 for character in normalized):
            raise Stage3Rejected("CANONICAL_VIOLATION", "control character")
        return normalized
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise Stage3Rejected("CANONICAL_VIOLATION", "non-string object key")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in result:
                raise Stage3Rejected("CANONICAL_VIOLATION", "normalized duplicate key")
            result[normalized_key] = normalize(item)
        return result
    raise Stage3Rejected("CANONICAL_VIOLATION", f"unsupported value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def semantic_id(prefix: str, value: Any, length: int = 32) -> str:
    digest = canonical_digest(value)
    return f"{prefix}-{digest[:length]}"
