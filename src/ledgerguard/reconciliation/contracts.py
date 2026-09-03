"""Digest-bound active contract registry with offline JSON Schema resolution."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from .errors import AdmissionRejected

ACTIVE_REGISTRY_SHA256 = "dd5088a847b0396cb880089dd68ba977a8910dc6941392c3f6052ba5bc5b4288"
EXPECTED_CONTRACT_FAMILIES = frozenset(
    {
        "COMMON",
        "BANK_ENTRY",
        "CASE_REVISION",
        "LEDGER_JOURNAL",
        "PROCESSOR_EVENT",
        "PROCESSOR_SETTLEMENT",
        "RECONCILIATION_POLICY",
        "RECONCILIATION_PROOF",
        "RUN_MANIFEST",
    }
)
MANIFEST_FAMILY_CONTRACTS = MappingProxyType(
    {
        "PROCESSOR_EVENTS": "PROCESSOR_EVENT",
        "PROCESSOR_SETTLEMENTS": "PROCESSOR_SETTLEMENT",
        "LEDGER_JOURNALS": "LEDGER_JOURNAL",
        "BANK_ENTRIES": "BANK_ENTRY",
    }
)


def _json_pointer(path: Iterable[object]) -> str:
    parts = [str(item).replace("~", "~0").replace("/", "~1") for item in path]
    return "" if not parts else "/" + "/".join(parts)


def _check_references(schemas: Mapping[str, Mapping[str, Any]]) -> None:
    for schema in schemas.values():
        pending: list[Any] = [schema]
        while pending:
            current = pending.pop()
            if isinstance(current, Mapping):
                reference = current.get("$ref")
                if isinstance(reference, str) and not reference.startswith("#"):
                    base = reference.split("#", 1)[0]
                    if base not in schemas:
                        raise AdmissionRejected(
                            "SCHEMA_VIOLATION", "non-local schema reference", base
                        )
                pending.extend(current.values())
            elif isinstance(current, list):
                pending.extend(current)


@dataclass(frozen=True)
class ContractRegistry:
    """Verified active schemas and their local resolver."""

    schemas: Mapping[str, Mapping[str, Any]]
    family_ids: Mapping[str, str]
    resolver: Registry[Any]

    @classmethod
    def load(cls, repository: Path) -> ContractRegistry:
        registry_path = repository / "contracts/active-contract-set-v1.json"
        try:
            registry_raw = registry_path.read_bytes()
        except OSError as error:
            raise AdmissionRejected("SCHEMA_VIOLATION", "active registry unavailable") from error
        if sha256(registry_raw).hexdigest() != ACTIVE_REGISTRY_SHA256:
            raise AdmissionRejected("SCHEMA_VIOLATION", "active registry digest mismatch")
        try:
            authority = json.loads(registry_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdmissionRejected(
                "SCHEMA_VIOLATION", "active registry is invalid JSON"
            ) from error
        if not isinstance(authority, dict):
            raise AdmissionRejected("SCHEMA_VIOLATION", "active registry must be an object")
        rows = authority.get("contracts")
        if not isinstance(rows, list) or len(rows) != len(EXPECTED_CONTRACT_FAMILIES):
            raise AdmissionRejected("SCHEMA_VIOLATION", "active contract count mismatch")
        schemas: dict[str, Mapping[str, Any]] = {}
        family_ids: dict[str, str] = {}
        resources: list[tuple[str, Resource[Any]]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise AdmissionRejected("SCHEMA_VIOLATION", "invalid registry row")
            family = row.get("family")
            identifier = row.get("id")
            relative = row.get("path")
            expected_digest = row.get("sha256")
            if not all(
                isinstance(value, str) for value in (family, identifier, relative, expected_digest)
            ):
                raise AdmissionRejected("SCHEMA_VIOLATION", "invalid registry identity")
            assert isinstance(family, str)
            assert isinstance(identifier, str)
            assert isinstance(relative, str)
            assert isinstance(expected_digest, str)
            if family in family_ids or identifier in schemas:
                raise AdmissionRejected("SCHEMA_VIOLATION", "duplicate contract identity")
            path = repository / relative
            try:
                raw = path.read_bytes()
            except OSError as error:
                raise AdmissionRejected(
                    "SCHEMA_VIOLATION", "registered schema unavailable", relative
                ) from error
            if sha256(raw).hexdigest() != expected_digest:
                raise AdmissionRejected("SCHEMA_VIOLATION", "schema digest mismatch", relative)
            try:
                schema = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AdmissionRejected(
                    "SCHEMA_VIOLATION", "registered schema is invalid JSON", relative
                ) from error
            if not isinstance(schema, dict):
                raise AdmissionRejected(
                    "SCHEMA_VIOLATION", "registered schema must be an object", relative
                )
            if schema.get("$id") != identifier:
                raise AdmissionRejected("SCHEMA_VIOLATION", "schema identifier mismatch", relative)
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise AdmissionRejected("SCHEMA_VIOLATION", "schema dialect mismatch", relative)
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise AdmissionRejected(
                    "SCHEMA_VIOLATION", "registered schema is invalid", relative
                ) from error
            schemas[identifier] = schema
            family_ids[family] = identifier
            resources.append((identifier, Resource.from_contents(schema)))
        if set(family_ids) != EXPECTED_CONTRACT_FAMILIES:
            raise AdmissionRejected("SCHEMA_VIOLATION", "active contract families mismatch")
        _check_references(schemas)
        return cls(
            schemas=MappingProxyType(schemas),
            family_ids=MappingProxyType(family_ids),
            resolver=Registry().with_resources(resources),
        )

    def validate(self, family: str, value: Any) -> None:
        schema_id = self.family_ids.get(family)
        if schema_id is None:
            raise AdmissionRejected("SCHEMA_VIOLATION", "unknown contract family", family)
        validator = Draft202012Validator(
            self.schemas[schema_id],
            registry=self.resolver,
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(value),
            key=lambda error: (
                _json_pointer(error.absolute_path),
                str(error.validator),
                error.message,
            ),
        )
        if errors:
            error = errors[0]
            raise AdmissionRejected(
                "SCHEMA_VIOLATION",
                f"{family}:{error.validator}",
                _json_pointer(error.absolute_path),
            )
