"""Fail-closed validation for the LedgerGuard Part 1 correction candidate."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource

from .stage0 import Stage0Error, validate_stage0
from .stage1 import Stage1Error, validate_stage1

PROJECT = "ledgerguard-payment-reconciliation-platform"
EXPECTED_TARGET = {
    "repository": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
    "default_branch": "main",
    "account_id": "857229544428",
    "region": "ap-southeast-2",
    "oidc_role_name": "LedgerGuardGitHubOidcRole",
}
EXPECTED_RUNTIME = {
    "glue_version": "5.1",
    "python_version": "3.11",
    "spark_version": "3.5.6",
}
STAGE2_STATE = "PART1_FINANCIAL_CONTRACTS_ENCODED"
STAGE3_STATE = "PART1_CONTRACT_COHERENCE_VALIDATED"
PART1_STATE = "PART1_FOUNDATION_CORRECTION_IN_PROGRESS"
STAGE2_BASELINE = {
    "main_sha": "155211c5df0985b332d3ba8c9d7b82ec4fc10c6a",
    "main_tree_sha": "0bb7631d533418ecf78c2d4b9f3e44959fee767d",
    "accepted_stage1_head_sha": "46b1f4e852ea40b24adaa30625074a2a05654259",
    "stage1_post_merge_ci_run_id": 33505222160,
    "stage0_sha256": "3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b",
    "stage1_sha256": "4234ac61999de769b87b2329512a8741761023b6c258dfd2207beb66f7dbc191",
    "stage1_completion_contract_sha256": (
        "d766641ccd150f3a188b1d156b912cde7473752c7af911b13876ad2c50a61ece"
    ),
}
STAGE3_BASELINE = {
    "main_sha": "583fbd13a129ac067a23f6348d05077d8b9250eb",
    "main_tree_sha": "40283451e9b73217c598ccea2d6eaea3a75797da",
    "accepted_stage2_head_sha": "a6bbcbc24d9acda5d2a04a54cce890eaf90fab00",
    "stage2_pr_ci_run_id": 33511658292,
    "stage2_post_merge_ci_run_id": 33511951023,
    "stage0_sha256": "3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b",
    "stage1_sha256": "4234ac61999de769b87b2329512a8741761023b6c258dfd2207beb66f7dbc191",
    "stage2_sha256": "3e8a3cdb753d94d013f592429bd8691f5ad100221496eb17e61864dc8d3b270c",
    "stage2_completion_contract_sha256": (
        "8464ce66ddc8dcf153f8a09915d0676778caf140e28533a864ab14e40adb7fe9"
    ),
}
STAGE3_PRESERVED_AUTHORITIES = {
    "ci_workflow": {
        "path": ".github/workflows/ci.yml",
        "sha256": "fa33b7e798875f32f06629fb2b958df40a527989c2b04a7c8f2d0649bf65b521",
    },
    "aws_target": {
        "path": ".github/ledgerguard-target.json",
        "sha256": "d9dccdc0dbae17638f02ac6596be1b1f0a8c24dddc57974f97024ed1cc415058",
    },
    "project_completion": {
        "path": "contracts/project-completion-v1.json",
        "sha256": "9a323c8b7800c90fc3ad1697ec407f6756ceebba8df266ab88deba97fe6017b6",
    },
    "stage0_completion": {
        "path": "contracts/part1-stage0-completion-v1.json",
        "sha256": "81fb7b9863b255cdc19768e80972e2174f940e0d0be97c31cf6ab0cecd4b66c5",
    },
    "stage1_completion": {
        "path": "contracts/part1-stage1-completion-v1.json",
        "sha256": "d766641ccd150f3a188b1d156b912cde7473752c7af911b13876ad2c50a61ece",
    },
    "stage2_completion": {
        "path": "contracts/part1-stage2-completion-v1.json",
        "sha256": "8464ce66ddc8dcf153f8a09915d0676778caf140e28533a864ab14e40adb7fe9",
    },
}
EVIDENCE_LEVELS = ["DESIGNED/MODELED", "LOCAL_VERIFIED", "AWS_VERIFIED", "UNCLAIMED"]
SCHEMA_NAMES = {
    "bank-entry-v1.schema.json",
    "case-revision-v1.schema.json",
    "journal-v1.schema.json",
    "processor-event-v1.schema.json",
    "processor-settlement-v1.schema.json",
    "reconciliation-policy-v1.schema.json",
    "reconciliation-proof-v1.schema.json",
    "run-manifest-v1.schema.json",
}
REQUIRED_DOCS = {
    "README.md",
    "PROJECT_STATUS.md",
    "docs/architecture.md",
    "docs/correctness.md",
    "docs/failure-model.md",
    "docs/gap-audit.md",
    "docs/scorecard.md",
    "docs/adr/0001-two-grain-reconciliation.md",
    "docs/adr/0002-parquet-proof-storage.md",
    "docs/adr/0003-late-data-revisions.md",
    "docs/adr/0000-corrective-baseline.md",
    "contracts/part1-stage0-completion-v1.json",
    "evidence/part1-stage0-local.json",
    "docs/adr/0004-canonical-source-identity.md",
    "docs/adr/0005-exact-bank-allocation.md",
    "docs/adr/0006-failure-ownership-and-finalization.md",
    "docs/financial-examples.md",
    "docs/part1-requirements.md",
    "docs/semantic-decisions.md",
    "docs/stage1-gap-audit.md",
    "evidence/part1-stage1-local.json",
    "contracts/part1-stage1-completion-v1.json",
    "spec/financial-examples-v1.json",
    "spec/financial-semantics-v1.json",
    "contracts/active-contract-set-v1.json",
    "contracts/part1-stage2-completion-v1.json",
    "docs/adr/0007-versioned-contract-set-and-enforcement-layers.md",
    "docs/contract-model.md",
    "docs/part1-stage2-requirements.md",
    "docs/stage2-gap-audit.md",
    "evidence/part1-stage2-local.json",
    "spec/contract-invariants-v1.json",
    "spec/contract-traceability-v1.json",
    "contracts/part1-stage3-completion-v1.json",
    "docs/adr/0008-canonical-contract-coherence.md",
    "docs/contract-coherence.md",
    "docs/part1-stage3-requirements.md",
    "docs/stage3-gap-audit.md",
    "evidence/part1-stage3-local.json",
    "spec/contract-coherence-traceability-v1.json",
    "spec/contract-coherence-v1.json",
    "spec/contract-coherence-vectors-v1.json",
}
FORBIDDEN_PATHS = {"docs/" + "".join(("INTER", "VIEW.md"))}
FORBIDDEN_TEXT = (
    "".join(("co", "dex")),
    "".join(("ai", "-assisted")),
    "".join(("generated by ", "ai")),
    "".join(("aws", "_lab_verified")),
    "".join(("inter", "view")),
)
FORBIDDEN_REGION = "-".join(("ap", "south", "1"))
RFC3339_OFFSET = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?P<fraction>\.[0-9]{1,6})?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})$"
)
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


class FoundationError(ValueError):
    """Raised when the checked-in foundation violates its frozen contract."""


def _reject_float(_: str) -> NoReturn:
    raise FoundationError("decimal or exponent JSON number is forbidden")


def _reject_constant(_: str) -> NoReturn:
    raise FoundationError("non-finite JSON number is forbidden")


def _parse_int(value: str) -> int:
    parsed = int(value)
    if not INT64_MIN <= parsed <= INT64_MAX:
        raise FoundationError("JSON integer is outside signed 64-bit range")
    return parsed


def _normalize_string(value: str) -> str:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise FoundationError("Unicode surrogate code point is forbidden")
    return unicodedata.normalize("NFC", value)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    raw_keys: set[str] = set()
    for raw_key, item in pairs:
        if raw_key in raw_keys:
            raise FoundationError("duplicate JSON object key")
        raw_keys.add(raw_key)
        key = _normalize_string(raw_key)
        if key in result:
            raise FoundationError("NFC-normalized JSON object-key collision")
        result[key] = item
    return result


def _normalize_contract_value(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_string(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not INT64_MIN <= value <= INT64_MAX:
            raise FoundationError("integer is outside signed 64-bit range")
        return value
    if isinstance(value, float):
        raise FoundationError("floating-point contract value is forbidden")
    if isinstance(value, list):
        return [_normalize_contract_value(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise FoundationError("contract object keys must be strings")
            key = _normalize_string(raw_key)
            if key in result:
                raise FoundationError("NFC-normalized contract object-key collision")
            result[key] = _normalize_contract_value(item)
        return result
    raise FoundationError(f"unsupported contract value type: {type(value).__name__}")


def parse_contract_json(text: str) -> Any:
    """Parse canonical contract input with a fail-closed numeric and Unicode profile."""

    if text.startswith("\ufeff"):
        raise FoundationError("UTF-8 BOM is forbidden")
    try:
        parsed = json.loads(
            text,
            parse_float=_reject_float,
            parse_int=_parse_int,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_pairs,
        )
    except json.JSONDecodeError as error:
        raise FoundationError(f"invalid JSON: {error.msg}") from error
    return _normalize_contract_value(parsed)


def canonical_timestamp(value: str) -> str:
    """Normalize an offset-aware RFC 3339 timestamp to the Stage 3 UTC profile."""

    if RFC3339_OFFSET.fullmatch(value) is None:
        raise FoundationError("timestamp is outside the Stage 3 RFC 3339 profile")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise FoundationError("timestamp is not calendar-valid RFC 3339") from error
    if parsed.utcoffset() is None:
        raise FoundationError("timestamp must be offset-aware")
    rendered = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    date_and_time, offset = rendered.split("+")
    if offset != "00:00":
        raise FoundationError("timestamp did not normalize to UTC")
    return date_and_time.rstrip("0").rstrip(".") + "Z"


def _canonicalize_timestamps(
    value: Any, timestamp_fields: set[str], field: str | None = None
) -> Any:
    normalized = _normalize_contract_value(value)
    if isinstance(normalized, str) and field in timestamp_fields:
        return canonical_timestamp(normalized)
    if isinstance(normalized, list):
        return [_canonicalize_timestamps(item, timestamp_fields) for item in normalized]
    if isinstance(normalized, Mapping):
        return {
            key: _canonicalize_timestamps(item, timestamp_fields, key)
            for key, item in normalized.items()
        }
    return normalized


def canonical_json_bytes(value: Any, timestamp_fields: set[str] | None = None) -> bytes:
    """Return deterministic UTF-8 JSON bytes for a contract value."""

    canonical = _canonicalize_timestamps(value, timestamp_fields or set())
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(
    value: Mapping[str, Any],
    *,
    excluded_fields: set[str] | None = None,
    timestamp_fields: set[str] | None = None,
) -> str:
    """Hash a top-level-field-scoped canonical contract object."""

    excluded = excluded_fields or set()
    scoped = {key: item for key, item in value.items() if key not in excluded}
    return sha256(canonical_json_bytes(scoped, timestamp_fields)).hexdigest()


def derive_contract_id(prefix: str, components: Mapping[str, Any]) -> str:
    """Derive a domain-separated content identity from canonical components."""

    return prefix + sha256(canonical_json_bytes(components)).hexdigest()


def _load_strict_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise FoundationError(f"cannot read strict JSON {path}: {error}") from error
    value = parse_contract_json(text)
    if not isinstance(value, dict):
        raise FoundationError(f"strict JSON object required: {path}")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FoundationError(f"cannot load JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise FoundationError(f"JSON object required: {path}")
    return value


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FoundationError(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise FoundationError(message)
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FoundationError(message)


def _validate_schemas(root: Path) -> dict[str, str]:
    contract_dir = root / "contracts"
    actual = {path.name for path in contract_dir.glob("*.schema.json")}
    _require(actual == SCHEMA_NAMES, f"schema inventory differs: {sorted(actual ^ SCHEMA_NAMES)}")
    digests: dict[str, str] = {}
    identifiers: set[str] = set()
    for name in sorted(SCHEMA_NAMES):
        path = contract_dir / name
        schema = _load_json(path)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise FoundationError(f"invalid schema {name}: {error.message}") from error
        identifier = schema.get("$id")
        if not isinstance(identifier, str) or not identifier:
            raise FoundationError(f"schema $id missing: {name}")
        _require(identifier not in identifiers, f"duplicate schema $id: {identifier}")
        identifiers.add(identifier)
        digests[name] = sha256(path.read_bytes()).hexdigest()
    return digests


def _artifact_digests(
    root: Path, artifacts: Mapping[str, Any], stage_name: str = "Stage 2"
) -> dict[str, str]:
    digests: dict[str, str] = {}
    for name, artifact_value in artifacts.items():
        artifact = _mapping(artifact_value, f"{stage_name} artifact {name} must be an object")
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(relative, str) or not relative:
            raise FoundationError(f"{stage_name} artifact path missing: {name}")
        relative_path = Path(relative)
        _require(
            not relative_path.is_absolute() and ".." not in relative_path.parts,
            f"{stage_name} artifact path escapes repository: {name}",
        )
        path = root / relative_path
        _require(path.is_file(), f"{stage_name} artifact missing: {relative}")
        actual = sha256(path.read_bytes()).hexdigest()
        _require(actual == expected, f"{stage_name} artifact digest differs: {relative}")
        digests[name] = actual
    return digests


def _iter_references(value: object) -> list[str]:
    references: list[str] = []
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str):
            references.append(reference)
        for child in value.values():
            references.extend(_iter_references(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(_iter_references(child))
    return references


def _validate_stage2(
    root: Path, stage0: Mapping[str, Any], stage1: Mapping[str, Any]
) -> dict[str, Any]:
    contract_path = root / "contracts/part1-stage2-completion-v1.json"
    evidence_path = root / "evidence/part1-stage2-local.json"
    contract = _load_json(contract_path)
    evidence = _load_json(evidence_path)

    _require(contract.get("project") == PROJECT, "Stage 2 project differs")
    _require(contract.get("part") == 1 and contract.get("stage") == 2, "Stage 2 identity differs")
    _require(contract.get("state") == STAGE2_STATE, "Stage 2 state differs")
    _require(contract.get("overall_part1_state") == PART1_STATE, "Stage 2 Part 1 state differs")
    baseline = _mapping(contract.get("baseline"), "Stage 2 baseline missing")
    _require(dict(baseline) == STAGE2_BASELINE, "Stage 2 baseline differs")
    _require(stage0.get("stage0_sha256") == STAGE2_BASELINE["stage0_sha256"], "Stage 0 differs")
    _require(stage1.get("stage1_sha256") == STAGE2_BASELINE["stage1_sha256"], "Stage 1 differs")

    completion_artifacts = _mapping(
        contract.get("contract_artifacts"), "Stage 2 contract artifacts missing"
    )
    artifact_digests = _artifact_digests(root, completion_artifacts)
    required_gates = _list(contract.get("required_gates"), "Stage 2 required gates missing")
    _require(len(required_gates) == len(set(required_gates)), "Stage 2 gates must be unique")
    _require("EXACT_HEAD_CI_SUCCESS" in required_gates, "Stage 2 exact-head CI gate missing")
    _require("POST_MERGE_MAIN_CI_SUCCESS" in required_gates, "Stage 2 post-merge CI gate missing")
    inventory = _mapping(contract.get("acceptance_inventory"), "Stage 2 inventory missing")
    _require(inventory.get("preserved_v1_schema_count") == 8, "v1 inventory differs")
    _require(inventory.get("active_schema_count") == 9, "v2 inventory differs")
    _require(inventory.get("contract_rule_count") == 18, "contract rule inventory differs")
    _require(inventory.get("requirement_count") == 12, "requirement inventory differs")
    _require(inventory.get("contract_test_count") == 26, "contract test inventory differs")
    _require(inventory.get("governance_test_count") == 10, "governance test inventory differs")
    _require(
        contract.get("remaining_part1_work")
        == [
            "VALIDATE_COMPLETE_CONTRACT_COHERENCE",
            "FREEZE_FINAL_PART1_COMPLETION_GOVERNANCE",
        ],
        "Stage 2 remaining Part 1 work differs",
    )

    active = _load_json(root / "contracts/active-contract-set-v1.json")
    _require(active.get("state") == "ACTIVE_CONTRACT_SET_V2", "active contract state differs")
    _require(active.get("active_schema_version") == "2.0", "active schema version differs")
    legacy = _mapping(active.get("legacy_contract_set"), "legacy contract set missing")
    _require(
        legacy.get("status") == "SUPERSEDED_BEFORE_RUNTIME_USE",
        "legacy contract status differs",
    )
    actual_v1 = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "contracts").glob("*-v1.schema.json"))
    }
    _require(legacy.get("digests") == actual_v1, "historical v1 schema bytes differ")
    _require(len(actual_v1) == 8, "historical v1 schema inventory differs")

    entries = _list(active.get("contracts"), "active contracts missing")
    _require(len(entries) == 9, "active schema inventory differs")
    identifiers: set[str] = set()
    families: set[str] = set()
    schemas: dict[str, Mapping[str, Any]] = {}
    active_digests: dict[str, str] = {}
    for entry_value in entries:
        entry = _mapping(entry_value, "every active contract must be an object")
        relative = entry.get("path")
        identifier = entry.get("id")
        family = entry.get("family")
        expected_digest = entry.get("sha256")
        if not isinstance(relative, str) or not relative:
            raise FoundationError("active contract path missing")
        relative_path = Path(relative)
        _require(
            not relative_path.is_absolute() and ".." not in relative_path.parts,
            "active contract path escapes repository",
        )
        if not isinstance(identifier, str) or not identifier:
            raise FoundationError("active contract ID missing")
        if not isinstance(family, str) or not family:
            raise FoundationError("active contract family missing")
        _require(identifier not in identifiers, f"duplicate active contract ID: {identifier}")
        _require(family not in families, f"duplicate active contract family: {family}")
        identifiers.add(identifier)
        families.add(family)
        path = root / relative_path
        _require(path.is_file(), f"active contract missing: {relative}")
        actual_digest = sha256(path.read_bytes()).hexdigest()
        _require(actual_digest == expected_digest, f"active contract digest differs: {relative}")
        schema = _load_json(path)
        _require(schema.get("$id") == identifier, f"active contract ID differs: {relative}")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            raise FoundationError(f"invalid active schema {relative}: {error.message}") from error
        schemas[identifier] = schema
        active_digests[family] = actual_digest
    for active_identifier, active_schema in schemas.items():
        for reference in _iter_references(active_schema):
            if reference.startswith("#"):
                continue
            target = reference.split("#", maxsplit=1)[0]
            _require(
                target in identifiers,
                f"unresolved active schema reference: {active_identifier} -> {target}",
            )

    invariants = _load_json(root / "spec/contract-invariants-v1.json")
    rules = _list(invariants.get("invariants"), "contract invariants missing")
    _require(len(rules) == 18, "contract invariant count differs")
    _require(
        [item.get("id") if isinstance(item, Mapping) else None for item in rules]
        == [f"CTR-{number:03d}" for number in range(1, 19)],
        "contract invariant IDs differ",
    )
    decision_ids = {
        decision
        for item in rules
        if isinstance(item, Mapping)
        for decision in _list(item.get("decision_ids"), "contract decision ownership missing")
    }
    requirement_ids = {
        requirement
        for item in rules
        if isinstance(item, Mapping)
        for requirement in _list(
            item.get("requirement_ids"), "contract requirement ownership missing"
        )
    }
    _require(
        decision_ids == {f"SEM-{number:03d}" for number in range(1, 19)},
        "semantic contract ownership differs",
    )
    _require(
        requirement_ids == {f"P1-R{number:02d}" for number in range(1, 13)},
        "requirement contract ownership differs",
    )
    _require(invariants.get("unmapped_decision_ids") == [], "unmapped semantic decisions remain")
    _require(invariants.get("unmapped_requirement_ids") == [], "unmapped requirements remain")

    traceability = _load_json(root / "spec/contract-traceability-v1.json")
    requirements = _list(traceability.get("requirements"), "Stage 2 traceability missing")
    _require(
        [item.get("id") if isinstance(item, Mapping) else None for item in requirements]
        == [f"P1-R{number:02d}" for number in range(1, 13)],
        "Stage 2 traceability order differs",
    )

    boundary = _mapping(contract.get("execution_boundary"), "Stage 2 boundary missing")
    for field in (
        "legacy_v1_schema_mutation",
        "reconciliation_engine_added",
        "spark_workload_added",
        "aws_execution",
        "infrastructure_mutation",
        "managed_evidence_claimed",
    ):
        _require(boundary.get(field) is False, f"Stage 2 {field} must be false")

    contract_digest = sha256(contract_path.read_bytes()).hexdigest()
    _require(evidence.get("project") == PROJECT, "Stage 2 evidence project differs")
    _require(evidence.get("part") == 1 and evidence.get("stage") == 2, "Stage 2 evidence differs")
    _require(evidence.get("stage_state") == STAGE2_STATE, "Stage 2 evidence state differs")
    _require(evidence.get("overall_state") == PART1_STATE, "Stage 2 evidence Part 1 state differs")
    _require(evidence.get("baseline") == dict(baseline), "Stage 2 evidence baseline differs")
    _require(
        evidence.get("completion_contract_sha256") == contract_digest,
        "Stage 2 completion contract digest differs",
    )
    _require(
        evidence.get("active_schema_digests") == active_digests,
        "Stage 2 active schema evidence differs",
    )
    _require(evidence.get("legacy_v1_schema_digests") == actual_v1, "v1 evidence differs")
    _require(
        evidence.get("contract_artifact_digests") == artifact_digests, "artifact evidence differs"
    )
    local = _mapping(evidence.get("local_validation"), "Stage 2 local validation missing")
    _require(
        isinstance(local.get("test_count"), int) and local["test_count"] > 59,
        "Stage 2 test count must exceed the Stage 1 baseline",
    )
    _require(local.get("contract_test_count") == 26, "Stage 2 contract test count differs")
    for field in (
        "ruff_format",
        "ruff_lint",
        "strict_mypy",
        "pytest",
        "fresh_install",
        "offline_reference_resolution",
        "diff_check",
        "determinism",
    ):
        _require(local.get(field) == "PASS", f"Stage 2 local validation {field} differs")
    claims = _mapping(evidence.get("claim_boundary"), "Stage 2 claim boundary missing")
    _require(claims.get("contract_structure") == "LOCAL_VERIFIED", "contract claim differs")
    _require(claims.get("reconciliation_execution") == "UNCLAIMED", "runtime claim differs")
    _require(claims.get("aws_execution") is False, "Stage 2 evidence claims AWS execution")
    _require(
        claims.get("aws_infrastructure_mutated") is False,
        "Stage 2 evidence claims infrastructure mutation",
    )

    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 2,
        "stage_state": STAGE2_STATE,
        "overall_part1_state": PART1_STATE,
        "baseline_main_sha": STAGE2_BASELINE["main_sha"],
        "baseline_main_tree_sha": STAGE2_BASELINE["main_tree_sha"],
        "stage0_sha256": stage0["stage0_sha256"],
        "stage1_sha256": stage1["stage1_sha256"],
        "completion_contract_sha256": contract_digest,
        "active_registry_sha256": artifact_digests["active_registry"],
        "active_schema_digests": active_digests,
        "contract_rule_count": len(rules),
        "requirement_count": len(requirements),
        "aws_execution": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage2_sha256"] = sha256(canonical).hexdigest()
    _require(
        local.get("stage2_validator_sha256") == payload["stage2_sha256"],
        "Stage 2 validator digest differs",
    )
    return payload


def _resolve_json_pointer(document: object, pointer: str) -> object:
    current = document
    if pointer == "":
        return current
    if not pointer.startswith("/"):
        raise FoundationError("JSON reference fragment must be a JSON pointer")
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as error:
                raise FoundationError(f"unresolved JSON pointer token: {token}") from error
        elif isinstance(current, Mapping):
            if token not in current:
                raise FoundationError(f"unresolved JSON pointer token: {token}")
            current = current[token]
        else:
            raise FoundationError("JSON pointer enters a scalar")
    return current


def _validate_instance(
    identifier: str,
    instance: Mapping[str, Any],
    validators: Mapping[str, Draft202012Validator],
) -> None:
    try:
        validators[identifier].validate(instance)
    except (KeyError, ValidationError) as error:
        raise FoundationError(f"Stage 3 specimen violates {identifier}: {error}") from error


def _validate_stage3_traceability(
    profile: Mapping[str, Any],
    traceability: Mapping[str, Any],
    required_gates: list[Any],
) -> tuple[int, int]:
    profile_requirements = _list(profile.get("requirements"), "Stage 3 requirements missing")
    expected_ids = [f"COH-{number:03d}" for number in range(1, 13)]
    profile_ids = [
        item.get("id") if isinstance(item, Mapping) else None for item in profile_requirements
    ]
    _require(profile_ids == expected_ids, "Stage 3 requirement IDs differ")

    mappings = _list(traceability.get("requirements"), "Stage 3 traceability missing")
    mapping_ids = [item.get("id") if isinstance(item, Mapping) else None for item in mappings]
    _require(mapping_ids == expected_ids, "Stage 3 traceability requirement order differs")
    mapped_gates: list[Any] = []
    mapped_tests: list[Any] = []
    for item_value in mappings:
        item = _mapping(item_value, "Stage 3 traceability entry must be an object")
        _require(
            bool(_list(item.get("profile_sections"), "profile-section ownership missing")),
            "profile-section ownership cannot be empty",
        )
        mapped_gates.extend(_list(item.get("gates"), "gate ownership missing"))
        mapped_tests.extend(_list(item.get("test_ids"), "test ownership missing"))
    _require(len(mapped_gates) == len(set(mapped_gates)), "Stage 3 gates have multiple owners")
    _require(mapped_gates == required_gates, "Stage 3 completion gates and traceability differ")
    expected_tests = [f"COH-T{number:03d}" for number in range(1, 18)]
    _require(sorted(mapped_tests) == expected_tests, "Stage 3 test IDs differ")

    ownership = _list(traceability.get("artifact_ownership"), "artifact ownership missing")
    owned_requirements: set[Any] = set()
    owned_paths: set[Any] = set()
    for entry_value in ownership:
        entry = _mapping(entry_value, "artifact ownership entry must be an object")
        path = entry.get("path")
        _require(
            isinstance(path, str) and path not in owned_paths, "artifact ownership path differs"
        )
        owned_paths.add(path)
        requirement_ids = _list(entry.get("requirement_ids"), "artifact requirements missing")
        _require(set(requirement_ids).issubset(set(expected_ids)), "unknown artifact requirement")
        owned_requirements.update(requirement_ids)
    _require(owned_requirements == set(expected_ids), "requirements lack artifact ownership")

    upstream = _mapping(traceability.get("upstream_coverage"), "upstream coverage missing")
    _require(
        upstream.get("semantic_decision_ids") == [f"SEM-{number:03d}" for number in range(1, 19)],
        "semantic decision coverage differs",
    )
    _require(
        upstream.get("contract_invariant_ids") == [f"CTR-{number:03d}" for number in range(1, 19)],
        "contract invariant coverage differs",
    )
    _require(
        upstream.get("part1_requirement_ids") == [f"P1-R{number:02d}" for number in range(1, 13)],
        "Part 1 requirement coverage differs",
    )
    for field in ("unmapped_requirement_ids", "unowned_gate_ids", "unowned_artifact_paths"):
        _require(traceability.get(field) == [], f"Stage 3 {field} must be empty")
    return len(mappings), len(mapped_tests)


def _validate_stage3(
    root: Path,
    stage0: Mapping[str, Any],
    stage1: Mapping[str, Any],
    stage2: Mapping[str, Any],
) -> dict[str, Any]:
    contract_path = root / "contracts/part1-stage3-completion-v1.json"
    evidence_path = root / "evidence/part1-stage3-local.json"
    contract = _load_strict_json(contract_path)
    evidence = _load_strict_json(evidence_path)
    profile = _load_strict_json(root / "spec/contract-coherence-v1.json")
    vectors = _load_strict_json(root / "spec/contract-coherence-vectors-v1.json")
    traceability = _load_strict_json(root / "spec/contract-coherence-traceability-v1.json")

    _require(contract.get("project") == PROJECT, "Stage 3 project differs")
    _require(contract.get("part") == 1 and contract.get("stage") == 3, "Stage 3 identity differs")
    _require(contract.get("state") == STAGE3_STATE, "Stage 3 state differs")
    _require(contract.get("overall_part1_state") == PART1_STATE, "Stage 3 Part 1 state differs")
    baseline = _mapping(contract.get("baseline"), "Stage 3 baseline missing")
    _require(dict(baseline) == STAGE3_BASELINE, "Stage 3 baseline differs")
    _require(stage0.get("stage0_sha256") == STAGE3_BASELINE["stage0_sha256"], "Stage 0 differs")
    _require(stage1.get("stage1_sha256") == STAGE3_BASELINE["stage1_sha256"], "Stage 1 differs")
    _require(stage2.get("stage2_sha256") == STAGE3_BASELINE["stage2_sha256"], "Stage 2 differs")

    artifacts = _mapping(contract.get("coherence_artifacts"), "Stage 3 artifacts missing")
    artifact_digests = _artifact_digests(root, artifacts, "Stage 3")
    required_gates = _list(contract.get("required_gates"), "Stage 3 required gates missing")
    _require(len(required_gates) == len(set(required_gates)), "Stage 3 gates must be unique")
    requirement_count, traceability_test_count = _validate_stage3_traceability(
        profile, traceability, required_gates
    )
    inventory = _mapping(contract.get("acceptance_inventory"), "Stage 3 inventory missing")
    expected_inventory = {
        "coherence_requirement_count": 12,
        "binding_rule_count": 12,
        "reference_fragment_count": 131,
        "preserved_v1_schema_count": 8,
        "preserved_v2_schema_count": 9,
        "coherence_test_count": 13,
        "governance_test_count": 11,
        "total_test_count": 119,
        "unresolved_coherence_decision_count": 0,
        "unmapped_requirement_count": 0,
        "unowned_gate_count": 0,
    }
    _require(dict(inventory) == expected_inventory, "Stage 3 acceptance inventory differs")

    _require(profile.get("project") == PROJECT, "coherence profile project differs")
    _require(profile.get("state") == STAGE3_STATE, "coherence profile state differs")
    _require(profile.get("unresolved_coherence_decisions") == [], "coherence decisions remain")
    strict_json = _mapping(profile.get("strict_json"), "strict JSON profile missing")
    _require(strict_json.get("integer_domain") == "SIGNED_64_BIT", "integer domain differs")
    _require(strict_json.get("booleans_are_integers") is False, "boolean/integer rule differs")
    canonicalization = _mapping(profile.get("canonicalization"), "canonicalization missing")
    _require(
        canonicalization.get("fractional_second_digits_max") == 6,
        "timestamp precision differs",
    )
    timestamp_fields = set(
        _list(canonicalization.get("timestamp_fields"), "timestamp fields missing")
    )
    strict_paths = _list(profile.get("strict_artifact_paths"), "strict artifact paths missing")
    _require(len(strict_paths) == len(set(strict_paths)), "strict artifact paths must be unique")
    for relative_value in strict_paths:
        _require(isinstance(relative_value, str), "strict artifact path must be a string")
        relative = Path(relative_value)
        _require(
            not relative.is_absolute() and ".." not in relative.parts,
            "strict path escapes repository",
        )
        _load_strict_json(root / relative)

    active = _load_strict_json(root / "contracts/active-contract-set-v1.json")
    entries = _list(active.get("contracts"), "active contracts missing")
    schemas: dict[str, dict[str, Any]] = {}
    families: dict[str, str] = {}
    registry: Registry[Any] = Registry()
    for entry_value in entries:
        entry = _mapping(entry_value, "active contract entry must be an object")
        identifier = entry.get("id")
        relative_value = entry.get("path")
        family = entry.get("family")
        if not isinstance(identifier, str):
            raise FoundationError("active contract ID missing")
        if not isinstance(relative_value, str):
            raise FoundationError("active contract path missing")
        if not isinstance(family, str):
            raise FoundationError("active contract family missing")
        schema = _load_strict_json(root / relative_value)
        schemas[identifier] = schema
        families[family] = identifier
        registry = registry.with_resource(identifier, Resource.from_contents(schema))
    validators = {
        identifier: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for identifier, schema in schemas.items()
    }

    reference_count = 0
    for identifier, schema in schemas.items():
        for reference in _iter_references(schema):
            base, _, fragment = reference.partition("#")
            target = schemas[base] if base else schema
            _resolve_json_pointer(target, fragment)
            reference_count += 1
        _require(schema.get("$id") == identifier, "active schema identifier differs")
    _require(reference_count == 131, "active schema reference-fragment inventory differs")

    semantics = _load_strict_json(root / "spec/financial-semantics-v1.json")
    common = _mapping(
        schemas["urn:ledgerguard:common:v2"].get("$defs"), "common definitions missing"
    )
    policy_defs = _mapping(
        schemas["urn:ledgerguard:reconciliation-policy:v2"].get("$defs"),
        "policy definitions missing",
    )
    proof_defs = _mapping(
        schemas["urn:ledgerguard:reconciliation-proof:v2"].get("$defs"),
        "proof definitions missing",
    )
    money = _mapping(semantics.get("money"), "money semantics missing")
    currency_rules = _mapping(policy_defs.get("currencyRules"), "currency rules missing")
    _require(
        set(
            _list(
                _mapping(common.get("supportedCurrency"), "currency domain missing").get("enum"),
                "currency enum missing",
            )
        )
        == set(_mapping(money.get("supported_currency_exponents"), "currency exponents missing"))
        == set(_mapping(currency_rules.get("properties"), "currency properties missing")),
        "currency domains differ",
    )
    transaction = _mapping(semantics.get("transaction"), "transaction semantics missing")
    settlement = _mapping(semantics.get("settlement"), "settlement semantics missing")
    _require(
        set(
            _list(
                _mapping(common.get("eventType"), "event domain missing").get("enum"),
                "event enum missing",
            )
        )
        == set(_mapping(transaction.get("processor_sign"), "processor signs missing")),
        "processor event domains differ",
    )
    ownership = _mapping(semantics.get("failure_ownership"), "failure ownership missing")
    _require(
        set(
            _list(
                _mapping(common.get("financialReason"), "financial reasons missing").get("enum"),
                "financial reason enum missing",
            )
        )
        == set(_list(ownership.get("FINANCIAL_EXCEPTION"), "financial exceptions missing")),
        "financial reason domains differ",
    )
    _require(
        set(
            _list(
                _mapping(proof_defs.get("transactionKey"), "transaction key missing").get(
                    "required"
                ),
                "transaction key fields missing",
            )
        )
        == set(_list(transaction.get("grain"), "transaction grain missing")),
        "transaction key fields differ",
    )
    _require(
        set(
            _list(
                _mapping(proof_defs.get("settlementKey"), "settlement key missing").get("required"),
                "settlement key fields missing",
            )
        )
        == set(_list(settlement.get("grain"), "settlement grain missing")),
        "settlement key fields differ",
    )

    family_contracts = _mapping(
        profile.get("manifest_family_contracts"), "manifest family contracts missing"
    )
    _require(
        dict(family_contracts)
        == {
            "PROCESSOR_EVENTS": families["PROCESSOR_EVENT"],
            "PROCESSOR_SETTLEMENTS": families["PROCESSOR_SETTLEMENT"],
            "LEDGER_JOURNALS": families["LEDGER_JOURNAL"],
            "BANK_ENTRIES": families["BANK_ENTRY"],
        },
        "manifest family contract bindings differ",
    )

    digest_scopes = _mapping(profile.get("digest_scopes"), "digest scopes missing")
    source_scope = set(
        _list(
            _mapping(digest_scopes.get("source_payload_sha256"), "source digest missing").get(
                "exclude"
            ),
            "source digest exclusions missing",
        )
    )
    source_vector = _mapping(vectors.get("source_digest"), "source digest vector missing")
    source_record = _mapping(source_vector.get("record"), "source record vector missing")
    source_bytes = canonical_json_bytes(
        {key: item for key, item in source_record.items() if key not in source_scope},
        timestamp_fields,
    )
    source_digest = sha256(source_bytes).hexdigest()
    _require(
        source_bytes.decode() == source_vector.get("expected_canonical_json"),
        "source canonical bytes differ",
    )
    _require(source_digest == source_vector.get("expected_sha256"), "source golden digest differs")
    replay = dict(source_record)
    replay.update(_mapping(source_vector.get("equivalent_redelivery"), "replay vector missing"))
    _require(
        canonical_sha256(replay, excluded_fields=source_scope, timestamp_fields=timestamp_fields)
        == source_digest,
        "equivalent source replay differs",
    )
    conflict = dict(source_record)
    conflict.update(
        _mapping(source_vector.get("conflicting_redelivery"), "conflict vector missing")
    )
    _require(
        canonical_sha256(conflict, excluded_fields=source_scope, timestamp_fields=timestamp_fields)
        != source_digest,
        "source identity conflict was accepted as replay",
    )
    canonical_source = _canonicalize_timestamps(source_record, timestamp_fields)
    _require(isinstance(canonical_source, dict), "canonical source must be an object")
    canonical_source["payload_sha256"] = source_digest
    _validate_instance(family_contracts["PROCESSOR_EVENTS"], canonical_source, validators)

    identities = _mapping(profile.get("identity_derivations"), "identity derivations missing")
    for vector_name, identity_name in (
        ("transaction_key", "transaction_key"),
        ("settlement_key", "settlement_key"),
    ):
        vector = _mapping(vectors.get(vector_name), f"{vector_name} vector missing")
        components = _mapping(vector.get("components"), f"{vector_name} components missing")
        identity = _mapping(identities.get(identity_name), f"{identity_name} identity missing")
        component_bytes = canonical_json_bytes(components)
        _require(
            component_bytes.decode() == vector.get("expected_canonical_json"),
            f"{vector_name} canonical bytes differ",
        )
        _require(
            derive_contract_id(str(identity.get("prefix")), components)
            == vector.get("expected_key"),
            f"{vector_name} derivation differs",
        )

    chain = _mapping(
        vectors.get("policy_manifest_proof_case_chain"), "binding-chain vector missing"
    )
    policy = _mapping(chain.get("policy"), "policy vector missing")
    manifest = _mapping(chain.get("manifest"), "manifest vector missing")
    proof = _mapping(chain.get("proof"), "proof vector missing")
    case_one = _mapping(chain.get("case_revision_one"), "case revision one missing")
    case_two = _mapping(chain.get("case_revision_two"), "case revision two missing")

    def chain_digest(
        name: str, value: Mapping[str, Any], expected_field: str, bytes_field: str | None
    ) -> str:
        scope = set(
            _list(
                _mapping(digest_scopes.get(name), f"{name} scope missing").get("exclude"),
                f"{name} exclusions missing",
            )
        )
        canonical = canonical_json_bytes(
            {key: item for key, item in value.items() if key not in scope}, timestamp_fields
        )
        digest = sha256(canonical).hexdigest()
        _require(chain.get(expected_field) == digest, f"{name} golden digest differs")
        if bytes_field is not None:
            _require(
                chain.get(bytes_field) == len(canonical), f"{name} canonical byte count differs"
            )
        return digest

    policy_digest = chain_digest(
        "policy_sha256", policy, "expected_policy_sha256", "expected_policy_canonical_bytes"
    )
    manifest_digest = chain_digest(
        "manifest_sha256", manifest, "expected_manifest_sha256", "expected_manifest_canonical_bytes"
    )
    chain_digest("proof_sha256", proof, "expected_proof_sha256", "expected_proof_canonical_bytes")
    case_one_digest = chain_digest(
        "case_revision_sha256",
        case_one,
        "expected_case_revision_one_sha256",
        "expected_case_revision_one_canonical_bytes",
    )
    case_two_digest = chain_digest(
        "case_revision_sha256", case_two, "expected_case_revision_two_sha256", None
    )

    transaction_vector = _mapping(vectors.get("transaction_key"), "transaction vector missing")
    expected_transaction_key = transaction_vector.get("expected_key")
    _require(
        proof.get("reconciliation_key") == expected_transaction_key, "proof key binding differs"
    )
    proof_identity = _mapping(identities.get("proof_id"), "proof identity missing")
    proof_components = {
        field: proof[field]
        for field in _list(proof_identity.get("fields"), "proof identity fields missing")
    }
    expected_proof_id = derive_contract_id(str(proof_identity.get("prefix")), proof_components)
    _require(chain.get("expected_proof_id") == expected_proof_id, "proof identity golden differs")
    _require(proof.get("proof_id") == expected_proof_id, "proof identity binding differs")
    case_identity = _mapping(identities.get("case_id"), "case identity missing")
    case_components = {
        field: case_one[field]
        for field in _list(case_identity.get("fields"), "case identity fields missing")
    }
    expected_case_id = derive_contract_id(str(case_identity.get("prefix")), case_components)
    _require(chain.get("expected_case_id") == expected_case_id, "case identity golden differs")
    _require(case_one.get("case_id") == expected_case_id, "case identity binding differs")

    _require(
        manifest.get("policy_version") == policy.get("policy_version"),
        "manifest policy version differs",
    )
    _require(manifest.get("policy_sha256") == policy_digest, "manifest policy digest differs")
    manifest_objects = _list(manifest.get("objects"), "manifest objects missing")
    manifest_families = [
        _mapping(item, "manifest object must be an object").get("family")
        for item in manifest_objects
    ]
    _require(set(manifest_families) == set(family_contracts), "manifest family inventory differs")
    _require(len(manifest_families) == len(set(manifest_families)), "manifest family duplicated")
    _require(proof.get("run_id") == manifest.get("run_id"), "proof run binding differs")
    _require(
        proof.get("source_manifest_sha256") == manifest_digest, "proof manifest binding differs"
    )
    _require(
        proof.get("policy_version") == policy.get("policy_version"), "proof policy version differs"
    )
    _require(proof.get("policy_sha256") == policy_digest, "proof policy digest differs")
    _require(
        case_one.get("initial_exception_proof_id") == expected_proof_id,
        "case initial proof differs",
    )
    _require(case_one.get("proof_id") == expected_proof_id, "case current proof differs")
    _require(case_two.get("case_id") == expected_case_id, "later case identity differs")
    _require(case_two.get("prior_case_revision_id") == case_one_digest, "case predecessor differs")
    _require(
        case_two.get("revision") == 2 and case_one.get("revision") == 1,
        "case revision sequence differs",
    )
    _require(case_two_digest != case_one_digest, "case revisions must be content-distinct")

    for identifier, specimen in (
        ("urn:ledgerguard:reconciliation-policy:v2", policy),
        ("urn:ledgerguard:run-manifest:v2", manifest),
        ("urn:ledgerguard:reconciliation-proof:v2", proof),
        ("urn:ledgerguard:case-revision:v2", case_one),
        ("urn:ledgerguard:case-revision:v2", case_two),
    ):
        _validate_instance(identifier, specimen, validators)

    boundary = _mapping(contract.get("execution_boundary"), "Stage 3 boundary missing")
    profile_boundary = _mapping(profile.get("execution_boundary"), "profile boundary missing")
    expected_false_fields = (
        "legacy_v1_schema_mutation",
        "active_v2_schema_mutation",
        "reconciliation_engine_added",
        "spark_workload_added",
        "aws_execution",
        "infrastructure_mutation",
        "managed_evidence_claimed",
    )
    for field in expected_false_fields:
        _require(boundary.get(field) is False, f"Stage 3 {field} must be false")
        _require(profile_boundary.get(field) is False, f"coherence profile {field} must be false")
    _require(
        contract.get("remaining_part1_work") == ["FREEZE_FINAL_PART1_COMPLETION_GOVERNANCE"],
        "Stage 3 remaining Part 1 work differs",
    )

    contract_digest = sha256(contract_path.read_bytes()).hexdigest()
    _require(evidence.get("project") == PROJECT, "Stage 3 evidence project differs")
    _require(evidence.get("part") == 1 and evidence.get("stage") == 3, "Stage 3 evidence differs")
    _require(evidence.get("stage_state") == STAGE3_STATE, "Stage 3 evidence state differs")
    _require(evidence.get("baseline") == dict(baseline), "Stage 3 evidence baseline differs")
    _require(
        evidence.get("completion_contract_sha256") == contract_digest,
        "Stage 3 completion contract digest differs",
    )
    _require(
        evidence.get("coherence_artifact_digests") == artifact_digests,
        "Stage 3 artifact evidence differs",
    )
    preserved_authorities = _mapping(
        evidence.get("preserved_authorities"), "Stage 3 preserved authorities missing"
    )
    _require(
        dict(preserved_authorities) == STAGE3_PRESERVED_AUTHORITIES,
        "Stage 3 preserved authority inventory differs",
    )
    _artifact_digests(root, preserved_authorities, "Stage 3 preserved authority")
    local = _mapping(evidence.get("local_validation"), "Stage 3 local validation missing")
    _require(
        isinstance(local.get("test_count"), int) and local["test_count"] > 95,
        "Stage 3 test count must exceed Stage 2",
    )
    _require(local.get("reference_fragment_count") == 131, "reference count evidence differs")
    for field in (
        "ruff_format",
        "ruff_lint",
        "strict_mypy",
        "pytest",
        "fresh_install",
        "strict_json_adversarial",
        "golden_vector_replay",
        "offline_reference_resolution",
        "bidirectional_traceability",
        "preservation_diff",
        "determinism",
    ):
        _require(local.get(field) == "PASS", f"Stage 3 local validation {field} differs")
    claims = _mapping(evidence.get("claim_boundary"), "Stage 3 claim boundary missing")
    _require(claims.get("contract_coherence") == "LOCAL_VERIFIED", "coherence claim differs")
    _require(claims.get("reconciliation_execution") == "UNCLAIMED", "runtime claim differs")
    _require(claims.get("aws_execution") is False, "Stage 3 evidence claims AWS execution")
    _require(
        claims.get("aws_infrastructure_mutated") is False,
        "Stage 3 evidence claims infrastructure mutation",
    )

    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 3,
        "stage_state": STAGE3_STATE,
        "overall_part1_state": PART1_STATE,
        "baseline_main_sha": STAGE3_BASELINE["main_sha"],
        "baseline_main_tree_sha": STAGE3_BASELINE["main_tree_sha"],
        "stage0_sha256": stage0["stage0_sha256"],
        "stage1_sha256": stage1["stage1_sha256"],
        "stage2_sha256": stage2["stage2_sha256"],
        "completion_contract_sha256": contract_digest,
        "coherence_artifact_digests": artifact_digests,
        "coherence_requirement_count": requirement_count,
        "traceability_test_count": traceability_test_count,
        "reference_fragment_count": reference_count,
        "binding_rule_count": len(_list(profile.get("binding_rules"), "binding rules missing")),
        "aws_execution": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage3_sha256"] = sha256(canonical).hexdigest()
    _require(
        local.get("stage3_validator_sha256") == payload["stage3_sha256"],
        "Stage 3 validator digest differs",
    )
    return payload


def _validate_target(root: Path) -> dict[str, Any]:
    target = _load_json(root / ".github/ledgerguard-target.json")
    for key, expected in EXPECTED_TARGET.items():
        _require(target.get(key) == expected, f"target {key} must equal {expected}")
    _require(target.get("managed_runtime") == EXPECTED_RUNTIME, "managed runtime differs")
    return target


def _validate_completion(root: Path, target: Mapping[str, Any]) -> dict[str, Any]:
    completion = _load_json(root / "contracts/project-completion-v1.json")
    _require(completion.get("project") == PROJECT, "completion project differs")
    _require(completion.get("state") == "PART1_FOUNDATION_FROZEN", "foundation state differs")
    _require(completion.get("evidence_levels") == EVIDENCE_LEVELS, "evidence vocabulary differs")

    parts = completion.get("parts")
    if not isinstance(parts, list):
        raise FoundationError("completion parts must be a list")
    part_mappings: list[Mapping[str, Any]] = []
    for part in parts:
        if not isinstance(part, Mapping):
            raise FoundationError("every completion part must be an object")
        part_mappings.append(part)
    part_numbers = [part.get("part") for part in part_mappings]
    _require(part_numbers == [1, 2, 3, 4, 5], "completion parts must be exactly 1 through 5")
    _require(
        all(isinstance(part.get("gates"), list) and part["gates"] for part in part_mappings),
        "part gates missing",
    )
    workload_parts = [
        part.get("part") for part in part_mappings if part.get("aws_workload_allowed") is True
    ]
    _require(workload_parts == [4], "managed workload must be allowed only in Part 4")

    scorecard = completion.get("scorecard")
    if not isinstance(scorecard, Mapping) or len(scorecard) != 12:
        raise FoundationError("scorecard must have 12 dimensions")
    for dimension, value in scorecard.items():
        _require(
            isinstance(value, (int, float)) and not isinstance(value, bool) and 7 < value <= 10,
            f"scorecard target {dimension} must be above 7 and at most 10",
        )

    aws_boundary = completion.get("aws_boundary")
    if not isinstance(aws_boundary, Mapping):
        raise FoundationError("completion AWS boundary missing")
    for key in ("account_id", "region", "oidc_role_name"):
        _require(
            aws_boundary.get(key) == target.get(key), f"completion and target differ for {key}"
        )
    _require(aws_boundary.get("gross_project_cost_ceiling_usd") == 10, "cost ceiling differs")
    _require(
        aws_boundary.get("managed_runtime") == "AWS Glue 5.1 / Spark 3.5.6 / Python 3.11",
        "completion runtime differs",
    )
    return completion


def _validate_repository_surface(root: Path) -> None:
    missing = sorted(path for path in REQUIRED_DOCS if not (root / path).is_file())
    _require(not missing, f"required documentation missing: {missing}")
    present_forbidden = sorted(path for path in FORBIDDEN_PATHS if (root / path).exists())
    _require(not present_forbidden, f"forbidden repository paths present: {present_forbidden}")

    ignored_parts = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = content.lower()
        for forbidden in FORBIDDEN_TEXT:
            _require(
                forbidden not in lowered, f"forbidden project text in {path.relative_to(root)}"
            )
        _require(
            FORBIDDEN_REGION not in content, f"blocked region present in {path.relative_to(root)}"
        )


def _validated_stage2_context(
    repository: Path,
) -> tuple[
    dict[str, str],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    schema_digests = _validate_schemas(repository)
    target = _validate_target(repository)
    completion = _validate_completion(repository, target)
    try:
        stage0 = validate_stage0(repository)
        stage1 = validate_stage1(repository)
    except (Stage0Error, Stage1Error) as error:
        raise FoundationError(f"preserved stage validation failed: {error}") from error
    stage2 = _validate_stage2(repository, stage0, stage1)
    return schema_digests, target, completion, stage0, stage1, stage2


def validate_foundation(root: Path | None = None) -> dict[str, Any]:
    """Validate and reproduce the accepted Stage 2 foundation interface."""

    repository = root or Path(__file__).resolve().parents[2]
    schema_digests, target, completion, stage0, stage1, stage2 = _validated_stage2_context(
        repository
    )
    _validate_repository_surface(repository)

    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "state": PART1_STATE,
        "stage": 2,
        "stage_state": STAGE2_STATE,
        "aws_execution": False,
        "stage0_sha256": stage0["stage0_sha256"],
        "stage1_sha256": stage1["stage1_sha256"],
        "stage2_sha256": stage2["stage2_sha256"],
        "schema_digests": schema_digests,
        "active_schema_digests": stage2["active_schema_digests"],
        "target": {
            "repository": target["repository"],
            "default_branch": target["default_branch"],
            "account_id": target["account_id"],
            "region": target["region"],
            "oidc_role_name": target["oidc_role_name"],
            "managed_runtime": target["managed_runtime"],
        },
        "scorecard_targets": completion["scorecard"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["foundation_sha256"] = sha256(canonical).hexdigest()
    return payload


def validate_contract_coherence(root: Path | None = None) -> dict[str, Any]:
    """Validate Stage 3 coherence while preserving the Stage 2 interface."""

    repository = root or Path(__file__).resolve().parents[2]
    schema_digests, target, completion, stage0, stage1, stage2 = _validated_stage2_context(
        repository
    )
    stage3 = _validate_stage3(repository, stage0, stage1, stage2)
    _validate_repository_surface(repository)

    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "state": PART1_STATE,
        "stage": 3,
        "stage_state": STAGE3_STATE,
        "aws_execution": False,
        "stage0_sha256": stage0["stage0_sha256"],
        "stage1_sha256": stage1["stage1_sha256"],
        "stage2_sha256": stage2["stage2_sha256"],
        "stage3_sha256": stage3["stage3_sha256"],
        "schema_digests": schema_digests,
        "active_schema_digests": stage2["active_schema_digests"],
        "target": {
            "repository": target["repository"],
            "default_branch": target["default_branch"],
            "account_id": target["account_id"],
            "region": target["region"],
            "oidc_role_name": target["oidc_role_name"],
            "managed_runtime": target["managed_runtime"],
        },
        "scorecard_targets": completion["scorecard"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["foundation_sha256"] = sha256(canonical).hexdigest()
    stage3_evidence = _load_strict_json(repository / "evidence/part1-stage3-local.json")
    local = _mapping(stage3_evidence.get("local_validation"), "Stage 3 local validation missing")
    _require(
        local.get("foundation_candidate_sha256") == payload["foundation_sha256"],
        "Stage 3 foundation candidate digest differs",
    )
    return payload


def main() -> None:
    print(json.dumps(validate_contract_coherence(Path.cwd()), indent=2, sort_keys=True))
