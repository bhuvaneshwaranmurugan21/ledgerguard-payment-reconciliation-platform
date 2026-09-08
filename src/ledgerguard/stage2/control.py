"""Pure fail-closed controls for Part 3 Stage 2 qualification."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import unquote

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HASH_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ACCOUNT = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")
ACCESS_KEY = re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")
REPOSITORY_OWNER = "bhuvaneshwaranmurugan21"
REPOSITORY_OWNER_ID = "276895096"
REPOSITORY_NAME = "ledgerguard-payment-reconciliation-platform"
REPOSITORY_ID = "1333030396"
REPOSITORY = f"{REPOSITORY_OWNER}/{REPOSITORY_NAME}"
MAIN_REF = "refs/heads/main"
OIDC_SUBJECT = (
    f"repo:{REPOSITORY_OWNER}@{REPOSITORY_OWNER_ID}/"
    f"{REPOSITORY_NAME}@{REPOSITORY_ID}:ref:{MAIN_REF}"
)
ENTRY_COMMIT = "5abef1a07899bd8ecd202008f1c397890184a0d2"
ENTRY_TREE = "77f13e8a68c46ccdcdae426b82c37c66d5e3ed81"
ENTRY_PARENT = "cb81704adcfdfac5d93879cd6c189fc2213bbe79"
STAGE2_REQUIREMENTS = (
    "P3-M-L226-01",
    "P3-M-L227-01",
    "P3-M-L227-02",
    "P3-M-L228-01",
    "P3-M-L228-02",
    "P3-M-L229-01",
    "P3-M-L230-01",
    "P3-M-L231-01",
    "P3-M-L232-01",
    "P3-M-L233-01",
    "P3-M-L234-01",
    "P3-M-L234-02",
    "P3-M-L234-03",
    "P3-M-L235-01",
    "P3-M-L236-01",
    "P3-M-L237-01",
    "P3-M-L238-01",
    "P3-M-L239-01",
    "P3-M-L266-01",
    "P3-M-L266-02",
    "P3-M-L267-01",
    "P3-M-L276-01",
)


class Stage2Rejected(ValueError):
    """A Stage 2 input or observation failed a required control."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage2Rejected(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), f"JSON object required: {path}")
    return cast(dict[str, Any], value)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _normalize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(value):
        item = value[key]
        if key in {"Action", "Resource", "AWS", "Federated", "Service"}:
            result[key] = sorted(_as_list(item))
        elif isinstance(item, Mapping):
            result[key] = _normalize_mapping(item)
        elif isinstance(item, list):
            result[key] = sorted(
                (_normalize_mapping(v) if isinstance(v, Mapping) else v for v in item),
                key=lambda v: json.dumps(v, sort_keys=True),
            )
        else:
            result[key] = item
    return result


def normalize_policy(document: Mapping[str, Any] | str) -> dict[str, Any]:
    """Normalize IAM JSON without erasing condition semantics."""
    if isinstance(document, str):
        parsed = json.loads(unquote(document))
    else:
        parsed = dict(document)
    require(set(parsed).issubset({"Version", "Statement"}), "unsupported policy field")
    require(parsed.get("Version") == "2012-10-17", "IAM policy version differs")
    statements = _as_list(parsed.get("Statement", []))
    normalized: list[dict[str, Any]] = []
    sids: set[str] = set()
    for raw in statements:
        require(isinstance(raw, Mapping), "policy statement must be an object")
        statement = _normalize_mapping(raw)
        require(
            "NotAction" not in statement and "NotResource" not in statement,
            "negative IAM selector forbidden",
        )
        require(statement.get("Effect") == "Allow", "unexpected IAM effect")
        sid = statement.get("Sid")
        require(
            isinstance(sid, str) and bool(sid) and sid not in sids,
            "duplicate or absent IAM Sid",
        )
        assert isinstance(sid, str)
        sids.add(sid)
        actions = statement.get("Action", [])
        require(all("*" not in action for action in actions), "wildcard IAM action forbidden")
        normalized.append(statement)
    normalized.sort(key=lambda row: cast(str, row["Sid"]))
    return {"Version": "2012-10-17", "Statement": normalized}


def policy_diff(desired: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
    expected = normalize_policy(desired)
    observed = normalize_policy(live)
    expected_rows = {row["Sid"]: row for row in expected["Statement"]}
    observed_rows = {row["Sid"]: row for row in observed["Statement"]}
    missing = sorted(set(expected_rows) - set(observed_rows))
    excess = sorted(set(observed_rows) - set(expected_rows))
    changed = sorted(
        sid
        for sid in set(expected_rows) & set(observed_rows)
        if expected_rows[sid] != observed_rows[sid]
    )
    return {
        "equal": not (missing or excess or changed),
        "missing": missing,
        "excess": excess,
        "changed": changed,
    }


def validate_dispatch(context: Mapping[str, str], supplied_sha: str) -> dict[str, str]:
    require(context.get("repository") == REPOSITORY, "repository differs")
    require(context.get("event_name") == "workflow_dispatch", "manual dispatch required")
    require(context.get("ref") == MAIN_REF, "main ref required")
    require(HEX40.fullmatch(supplied_sha) is not None, "exact SHA input malformed")
    require(context.get("sha") == supplied_sha, "input SHA differs from workflow SHA")
    require(context.get("checkout_sha") == supplied_sha, "checkout SHA differs")
    return {"repository": REPOSITORY, "ref": MAIN_REF, "sha": supplied_sha}


def validate_identity(
    account: str, region: str, arn: str, target: Mapping[str, Any]
) -> dict[str, Any]:
    role = target["oidc_role_name"]
    require(account == target["account_id"], "AWS account differs")
    require(region == target["region"], "AWS region differs")
    require(f":assumed-role/{role}/" in arn, "assumed role differs")
    fingerprint = sha256_bytes(f"{account}:{role}".encode())
    return {
        "account_match": True,
        "region_match": True,
        "role_match": True,
        "identity_fingerprint": fingerprint,
    }


def validate_backend(observation: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "bucket": contract["bucket"],
        "region": contract["region"],
        "versioning": "Enabled",
        "encryption": contract["encryption"],
        "public_access_block": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
        "ownership": "BucketOwnerEnforced",
        "tls_deny": True,
        "prefix_isolated": True,
        "pagination_complete": True,
    }
    for key, expected in required.items():
        require(observation.get(key) == expected, f"backend {key} differs")
    return {"ready": True, "bucket_fingerprint": sha256_bytes(contract["bucket"].encode())}


def validate_tls_only_bucket_policy(
    document: Mapping[str, Any] | str, bucket: str
) -> dict[str, Any]:
    policy = json.loads(document) if isinstance(document, str) else dict(document)
    expected_resources = {f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"}
    matches = []
    for statement in _as_list(policy.get("Statement", [])):
        principal = statement.get("Principal")
        principal_all = principal == "*" or principal == {"AWS": "*"}
        if (
            statement.get("Effect") == "Deny"
            and principal_all
            and set(_as_list(statement.get("Action", []))) == {"s3:*"}
            and set(_as_list(statement.get("Resource", []))) == expected_resources
            and statement.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false"
        ):
            matches.append(statement)
    require(len(matches) == 1, "exact TLS-only S3 bucket policy statement required")
    return {"verified": True}


def validate_backend_lifecycle(
    observation: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    expected = contract["required_lifecycle"]
    matches = []
    for rule in observation.get("Rules", []):
        prefix = rule.get("Filter", {}).get("Prefix", rule.get("Prefix"))
        if rule.get("ID") == expected["id"] and prefix == expected["prefix"]:
            matches.append(rule)
    require(len(matches) == 1, "qualification lifecycle rule missing or duplicated")
    rule = matches[0]
    require(rule.get("Status") == expected["status"], "qualification lifecycle status differs")
    require(
        rule.get("Expiration", {}).get("Days") == expected["expiration_days"],
        "qualification expiration differs",
    )
    require(
        rule.get("NoncurrentVersionExpiration", {}).get("NoncurrentDays")
        == expected["noncurrent_expiration_days"],
        "qualification noncurrent expiration differs",
    )
    require(
        rule.get("AbortIncompleteMultipartUpload", {}).get("DaysAfterInitiation")
        == expected["abort_incomplete_multipart_days"],
        "qualification multipart cleanup differs",
    )
    return {"verified": True, "rule_id": expected["id"]}


def validate_lease_table(
    observation: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    checks = {
        "table": contract["table"],
        "status": "ACTIVE",
        "partition_key": contract["partition_key"],
        "partition_key_type": "S",
        "encryption": True,
        "billing_mode": "PAY_PER_REQUEST",
        "qualification_key_empty": True,
        "pitr": "ENABLED" if contract["pitr_decision"] == "ENABLED" else "DISABLED",
        "ttl_status": "ENABLED",
        "ttl_attribute": contract["ttl_attribute"],
    }
    for key, expected in checks.items():
        require(observation.get(key) == expected, f"lease table {key} differs")
    return {"ready": True, "table_fingerprint": sha256_bytes(contract["table"].encode())}


def validate_required_tags(
    observed: Mapping[str, str], required: Mapping[str, str]
) -> dict[str, Any]:
    missing = sorted(key for key, value in required.items() if observed.get(key) != value)
    require(not missing, f"required resource tags differ: {missing}")
    return {
        "verified": True,
        "required_tag_count": len(required),
        "tag_fingerprint": sha256_bytes(canonical_bytes(dict(sorted(required.items())))),
    }


def acquire_allowed(current: Mapping[str, Any] | None, now_epoch: int, owner: str) -> bool:
    require(now_epoch >= 0 and bool(owner), "invalid lease request")
    return (
        current is None
        or int(current["expires_epoch"]) < now_epoch
        or current.get("owner") == owner
    )


def release_allowed(
    current: Mapping[str, Any] | None, owner: str, commit: str, run_id: str
) -> bool:
    if current is None:
        return False
    return (
        current.get("owner") == owner
        and current.get("commit") == commit
        and current.get("run_id") == run_id
    )


def budget_headroom(
    observation: Mapping[str, Any], contract: Mapping[str, Any], now_epoch: int
) -> dict[str, Any]:
    currency = observation.get("currency")
    require(currency == "USD", "billing currency differs")
    updated = observation.get("updated_epoch")
    require(isinstance(updated, int), "billing data missing or stale")
    assert isinstance(updated, int)
    require(
        0 <= now_epoch - updated <= contract["maximum_age_seconds"],
        "billing data missing or stale",
    )
    gross = Decimal(str(observation.get("known_gross_project_spend")))
    reserve = Decimal(str(contract["conservative_unbilled_reserve_usd"]))
    estimate = Decimal(str(contract["maximum_stage2_probe_cost_usd"]))
    ceiling = Decimal(str(contract["gross_project_ceiling_usd"]))
    require(gross >= 0 and reserve >= 0 and estimate >= 0, "cost inputs cannot be negative")
    remaining = ceiling - gross - reserve
    require(remaining > estimate, "insufficient Stage 2 budget headroom")
    return {
        "verdict": "HEADROOM_VERIFIED",
        "gross_project_ceiling_usd": format(ceiling, ".4f"),
        "known_gross_project_spend_usd": format(gross, ".4f"),
        "conservative_unbilled_reserve_usd": format(reserve, ".4f"),
        "maximum_stage2_probe_cost_usd": format(estimate, ".4f"),
        "remaining_usd": format(remaining, ".4f"),
        "freshness_seconds": now_epoch - updated,
    }


def validate_s3_cleanup(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    residue = [row for row in rows if row.get("Key")]
    require(not residue, "S3 object version or delete-marker residue")
    return {"prefix_empty": True, "residue_count": 0}


def validate_glue_job(
    observation: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    compared = {key: observation.get(key) for key in contract["compared_fields"]}
    expected = {key: contract["definition"].get(key) for key in contract["compared_fields"]}
    require(compared == expected, "Glue definition differs")
    require(observation.get("run_count") == 0, "Glue probe must have zero runs")
    return {"definition_equal": True, "zero_runs": True}


def validate_inventory(observation: Mapping[str, Any]) -> dict[str, Any]:
    require(observation.get("pagination_complete") is True, "inventory pagination incomplete")
    require(observation.get("access_denied") == [], "inventory visibility denied")
    require(
        observation.get("workload_resources") == [], "active LedgerGuard workload resource exists"
    )
    require(observation.get("probe_residue") == [], "Stage 2 probe residue exists")
    return {"clean": True}


def validate_manifest(directory: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    require(
        manifest.get("schema_version") == "1.0"
        and manifest.get("excluded_self") == "manifest.json",
        "manifest envelope differs",
    )
    rows = manifest.get("members")
    require(isinstance(rows, list) and bool(rows), "manifest inventory missing")
    assert isinstance(rows, list)
    expected: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "artifact symlink forbidden")
        if path.is_file() and path.name != "manifest.json":
            rel = path.relative_to(directory).as_posix()
            expected.append(
                {
                    "path": rel,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
            )
    for row in rows:
        require(
            isinstance(row, Mapping) and set(row) == {"path", "size_bytes", "sha256"},
            "manifest member shape differs",
        )
        member_path = PurePosixPath(cast(str, row["path"]))
        require(
            not member_path.is_absolute()
            and ".." not in member_path.parts
            and "\\" not in cast(str, row["path"])
            and member_path.name != "manifest.json",
            "unsafe manifest member",
        )
    require(rows == expected, "artifact member inventory or digest differs")
    return {"integrity_verified": True, "members": len(rows)}


def _redact_hash_values(value: Any) -> Any:
    if isinstance(value, str):
        return "<HASH>" if HASH_ID.fullmatch(value) else value
    if isinstance(value, list):
        return [_redact_hash_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_hash_values(item) for key, item in value.items()}
    return value


def scan_safe_evidence(directory: Path) -> dict[str, Any]:
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        text = raw.decode(errors="ignore")
        require(
            b"-----BEGIN" not in raw and ACCESS_KEY.search(text) is None,
            "credential material in evidence",
        )
        if path.suffix in {".json", ".log", ".txt", ".md"}:
            account_material = text
            if path.suffix == ".json":
                try:
                    document = json.loads(text)
                except json.JSONDecodeError:
                    pass
                else:
                    account_material = json.dumps(_redact_hash_values(document), sort_keys=True)
            require(ACCOUNT.search(account_material) is None, "raw AWS account in evidence")
    return {"safe": True}


def validate_stage2_authority(root: Path) -> dict[str, Any]:
    closure = read_object(root / "spec/part3-stage1-external-closure-v1.json")
    require(
        closure["squash_commit"] == ENTRY_COMMIT
        and closure["tree"] == ENTRY_TREE
        and closure["sole_parent"] == ENTRY_PARENT,
        "Stage 1 external closure differs",
    )
    require(
        closure["stage_complete"] is True
        and closure["gate_13"] == closure["gate_14"] == "EXTERNALLY_VERIFIED",
        "Stage 1 is not externally closed",
    )
    freeze = read_object(root / "spec/part3-stage2-baseline-freeze-v1.json")
    for path, digest in freeze["immutable_historical_authority"].items():
        require(
            sha256_bytes((root / path).read_bytes()) == digest,
            f"protected authority changed: {path}",
        )
    adjudication = read_object(root / "spec/part3-stage2-requirement-adjudication-v1.json")
    ids = [row["requirement_id"] for row in adjudication["requirements"]]
    require(
        ids == list(STAGE2_REQUIREMENTS) and len(ids) == len(set(ids)),
        "Stage 2 requirement ownership differs",
    )
    traceability = read_object(root / "spec/part3-stage2-traceability-v1.json")
    require(
        list(traceability["requirements"]) == list(STAGE2_REQUIREMENTS),
        "Stage 2 traceability requirement inventory differs",
    )
    for row in adjudication["requirements"]:
        traced = traceability["requirements"][row["requirement_id"]]
        require(
            row["implementation"] == traced["implementation"]
            and row["tests"] == traced["tests"]
            and row["planned_live_evidence"] == traced["evidence"],
            f"Stage 2 traceability differs: {row['requirement_id']}",
        )
        for path in [*row["implementation"], *row["tests"]]:
            require((root / path).is_file(), f"Stage 2 traced file is absent: {path}")
    gates = read_object(root / "spec/part3-stage2-gate-registry-v1.json")["gates"]
    require(
        [row["gate_id"] for row in gates] == [f"P3-S2-G{i:03d}" for i in range(1, 21)],
        "Stage 2 gate inventory differs",
    )
    require(
        list(traceability["gates"]) == [f"P3-S2-G{i:03d}" for i in range(1, 21)],
        "Stage 2 gate traceability differs",
    )
    require(
        all(row["state"] == "PENDING_EXECUTED_EVIDENCE" for row in gates),
        "Stage 2 gate prematurely passed",
    )
    scenarios = read_object(root / "spec/part3-stage2-scenario-registry-v1.json")
    scenario_rows = scenarios["scenarios"]
    require(
        scenarios["count"] == len(scenario_rows) >= 100
        and [row["scenario_id"] for row in scenario_rows]
        == [f"P3-S2-T{i:03d}" for i in range(1, len(scenario_rows) + 1)],
        "Stage 2 scenario inventory differs",
    )
    for row in scenario_rows:
        require(
            (root / row["test_file"]).is_file()
            and row["nodeid"].startswith(row["test_file"] + "::"),
            f"Stage 2 scenario trace differs: {row['scenario_id']}",
        )
    return {
        "entry_verified": True,
        "requirements": len(ids),
        "gates": len(gates),
        "protected_paths": len(freeze["immutable_historical_authority"]),
        "traceability_links": len(traceability["requirements"]),
        "scenarios": len(scenario_rows),
    }
