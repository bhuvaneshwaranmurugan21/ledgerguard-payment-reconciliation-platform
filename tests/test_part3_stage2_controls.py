from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerguard.stage2.control import (
    Stage2Rejected,
    acquire_allowed,
    aggregate_gross_spend,
    budget_headroom,
    canonical_bytes,
    release_allowed,
    validate_backend,
    validate_backend_lifecycle,
    validate_dispatch,
    validate_glue_job,
    validate_identity,
    validate_inventory,
    validate_lease_table,
    validate_required_tags,
    validate_s3_cleanup,
    validate_tls_only_bucket_policy,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET = {
    "account_id": "857229544428",
    "region": "ap-southeast-2",
    "oidc_role_name": "LedgerGuardGitHubOidcRole",
}


def dispatch(**changes: str) -> dict[str, str]:
    context = {
        "repository": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
        "event_name": "workflow_dispatch",
        "ref": "refs/heads/main",
        "sha": "a" * 40,
        "checkout_sha": "a" * 40,
    }
    context.update(changes)
    return context


def test_exact_dispatch_and_identity_are_accepted() -> None:
    assert validate_dispatch(dispatch(), "a" * 40)["sha"] == "a" * 40
    result = validate_identity(
        "857229544428",
        "ap-southeast-2",
        "arn:aws:sts::857229544428:assumed-role/LedgerGuardGitHubOidcRole/run",
        TARGET,
    )
    assert result["account_match"] and len(result["identity_fingerprint"]) == 64


@pytest.mark.parametrize(
    "context,sha",
    [
        (dispatch(repository="other/repo"), "a" * 40),
        (dispatch(event_name="push"), "a" * 40),
        (dispatch(ref="refs/heads/dev"), "a" * 40),
        (dispatch(), "bad"),
        (dispatch(sha="b" * 40), "a" * 40),
        (dispatch(checkout_sha="b" * 40), "a" * 40),
    ],
)
def test_dispatch_mismatch_rejects_before_oidc(context: dict[str, str], sha: str) -> None:
    with pytest.raises(Stage2Rejected):
        validate_dispatch(context, sha)


@pytest.mark.parametrize(
    "account,region,arn",
    [
        pytest.param(
            "000000000000",
            "ap-southeast-2",
            "arn:aws:sts::857229544428:assumed-role/LedgerGuardGitHubOidcRole/run",
            id="wrong-account",
        ),
        pytest.param(
            "857229544428",
            "us-east-1",
            "arn:aws:sts::857229544428:assumed-role/LedgerGuardGitHubOidcRole/run",
            id="wrong-region",
        ),
        pytest.param(
            "857229544428",
            "ap-southeast-2",
            "arn:aws:sts::857229544428:assumed-role/Other/run",
            id="wrong-role",
        ),
    ],
)
def test_identity_mismatch_rejects(account: str, region: str, arn: str) -> None:
    with pytest.raises(Stage2Rejected):
        validate_identity(account, region, arn, TARGET)


def backend_observation() -> dict[str, object]:
    return {
        "bucket": "b",
        "region": "ap-southeast-2",
        "versioning": "Enabled",
        "encryption": "aws:kms",
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


def test_backend_and_lease_controls_pass_exact_observations() -> None:
    backend = {"bucket": "b", "region": "ap-southeast-2", "encryption": "aws:kms"}
    assert validate_backend(backend_observation(), backend)["ready"]
    lease = {"table": "t", "partition_key": "lease_key"}
    observed = {
        "table": "t",
        "status": "ACTIVE",
        "partition_key": "lease_key",
        "partition_key_type": "S",
        "encryption": True,
        "billing_mode": "PAY_PER_REQUEST",
        "qualification_key_empty": True,
        "pitr": "ENABLED",
        "ttl_status": "ENABLED",
        "ttl_attribute": "expires_epoch",
    }
    assert validate_lease_table(
        observed,
        {
            **lease,
            "pitr_decision": "ENABLED",
            "ttl_attribute": "expires_epoch",
        },
    )["ready"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("region", "us-east-1"),
        ("versioning", None),
        ("encryption", "AES256"),
        ("ownership", "ObjectWriter"),
        ("tls_deny", False),
        ("prefix_isolated", False),
        ("pagination_complete", False),
    ],
)
def test_backend_drift_rejects(key: str, value: object) -> None:
    observation = backend_observation()
    observation[key] = value
    with pytest.raises(Stage2Rejected):
        validate_backend(
            observation, {"bucket": "b", "region": "ap-southeast-2", "encryption": "aws:kms"}
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "CREATING"),
        ("partition_key", "pk"),
        ("partition_key_type", "N"),
        ("encryption", False),
        ("billing_mode", "PROVISIONED"),
        ("qualification_key_empty", False),
        ("pitr", "DISABLED"),
        ("ttl_status", "DISABLED"),
        ("ttl_attribute", "other"),
    ],
)
def test_lease_table_drift_rejects(key: str, value: object) -> None:
    observation = {
        "table": "t",
        "status": "ACTIVE",
        "partition_key": "lease_key",
        "partition_key_type": "S",
        "encryption": True,
        "billing_mode": "PAY_PER_REQUEST",
        "qualification_key_empty": True,
        "pitr": "ENABLED",
        "ttl_status": "ENABLED",
        "ttl_attribute": "expires_epoch",
    }
    observation[key] = value
    with pytest.raises(Stage2Rejected):
        validate_lease_table(
            observation,
            {
                "table": "t",
                "partition_key": "lease_key",
                "pitr_decision": "ENABLED",
                "ttl_attribute": "expires_epoch",
            },
        )


def lifecycle_observation() -> dict[str, object]:
    return {
        "Rules": [
            {
                "ID": "LedgerGuardQualificationCleanup",
                "Status": "Enabled",
                "Filter": {"Prefix": "qualification/"},
                "Expiration": {"Days": 7},
                "NoncurrentVersionExpiration": {"NoncurrentDays": 7},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
            }
        ]
    }


LIFECYCLE_CONTRACT = {
    "required_lifecycle": {
        "id": "LedgerGuardQualificationCleanup",
        "status": "Enabled",
        "prefix": "qualification/",
        "expiration_days": 7,
        "noncurrent_expiration_days": 7,
        "abort_incomplete_multipart_days": 1,
    }
}


def test_backend_lifecycle_and_required_tags_pass_exactly() -> None:
    assert validate_backend_lifecycle(lifecycle_observation(), LIFECYCLE_CONTRACT)["verified"]
    result = validate_required_tags(
        {"Project": "LedgerGuard", "Purpose": "Lease", "Extra": "allowed"},
        {"Project": "LedgerGuard", "Purpose": "Lease"},
    )
    assert result["verified"] and result["required_tag_count"] == 2


@pytest.mark.parametrize("change", ["resource", "principal", "condition", "duplicate"])
def test_tls_only_bucket_policy_requires_exact_deny_scope(change: str) -> None:
    bucket = "ledgerguard-backend"
    statement = {
        "Sid": "DenyInsecureTransport",
        "Effect": "Deny",
        "Principal": "*",
        "Action": "s3:*",
        "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
    }
    document = {"Statement": [statement]}
    if change == "resource":
        statement["Resource"] = [f"arn:aws:s3:::{bucket}"]
    elif change == "principal":
        statement["Principal"] = {"AWS": "arn:aws:iam::000000000000:root"}
    elif change == "condition":
        statement["Condition"] = {"Bool": {"aws:SecureTransport": "true"}}
    else:
        document["Statement"].append(dict(statement))
    with pytest.raises(Stage2Rejected):
        validate_tls_only_bucket_policy(document, bucket)


def test_tls_only_bucket_policy_accepts_exact_statement_and_string_form() -> None:
    bucket = "ledgerguard-backend"
    document = {
        "Statement": [
            {
                "Effect": "Deny",
                "Principal": {"AWS": "*"},
                "Action": "s3:*",
                "Resource": [f"arn:aws:s3:::{bucket}/*", f"arn:aws:s3:::{bucket}"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ]
    }
    assert validate_tls_only_bucket_policy(json.dumps(document), bucket)["verified"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("ID", "Other"),
        ("Status", "Disabled"),
        ("Expiration", {"Days": 8}),
        ("NoncurrentVersionExpiration", {"NoncurrentDays": 8}),
        ("AbortIncompleteMultipartUpload", {"DaysAfterInitiation": 2}),
    ],
)
def test_backend_lifecycle_drift_rejects(field: str, value: object) -> None:
    observation = lifecycle_observation()
    observation["Rules"][0][field] = value  # type: ignore[index]
    with pytest.raises(Stage2Rejected):
        validate_backend_lifecycle(observation, LIFECYCLE_CONTRACT)


@pytest.mark.parametrize(
    "observed",
    [{"Project": "Other"}, {"Project": "LedgerGuard"}],
)
def test_required_tag_drift_rejects(observed: dict[str, str]) -> None:
    with pytest.raises(Stage2Rejected):
        validate_required_tags(observed, {"Project": "LedgerGuard", "Purpose": "Lease"})


def test_lease_semantics_cover_conflict_expiry_recovery_and_owner_release() -> None:
    current = {"owner": "one", "commit": "a" * 40, "run_id": "1", "expires_epoch": 100}
    assert acquire_allowed(None, 100, "one")
    assert acquire_allowed(current, 100, "one")
    assert not acquire_allowed(current, 100, "two")
    assert acquire_allowed(current, 101, "two")
    assert not release_allowed(current, "two", "a" * 40, "1")
    assert not release_allowed(current, "one", "b" * 40, "1")
    assert release_allowed(current, "one", "a" * 40, "1")
    assert not release_allowed(None, "one", "a" * 40, "1")
    with pytest.raises(Stage2Rejected):
        acquire_allowed(None, -1, "one")


def cost_observation(**changes: object) -> dict[str, object]:
    value = {"currency": "USD", "updated_epoch": 900, "known_gross_project_spend": "0.00"}
    value.update(changes)
    return value


COST = {
    "maximum_age_seconds": 200,
    "conservative_unbilled_reserve_usd": "1.00",
    "maximum_stage2_probe_cost_usd": "0.05",
    "gross_project_ceiling_usd": "10.00",
}


def test_budget_headroom_is_conservative_and_exact() -> None:
    assert budget_headroom(cost_observation(), COST, 1000) == {
        "verdict": "HEADROOM_VERIFIED",
        "gross_project_ceiling_usd": "10.0000",
        "known_gross_project_spend_usd": "0.0000",
        "conservative_unbilled_reserve_usd": "1.0000",
        "maximum_stage2_probe_cost_usd": "0.0500",
        "remaining_usd": "9.0000",
        "freshness_seconds": 100,
    }
    assert (
        budget_headroom(cost_observation(updated_epoch=800), COST, 1000)["freshness_seconds"] == 200
    )


def cost_period(amounts: list[tuple[str, str, str]]) -> dict[str, object]:
    return {
        "Groups": [
            {
                "Keys": [record_type],
                "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": unit}},
            }
            for record_type, amount, unit in amounts
        ]
    }


def test_gross_spend_excludes_negative_offsets_without_netting() -> None:
    result = aggregate_gross_spend(
        [
            cost_period([("Usage", "2.25", "USD"), ("Credit", "-5.00", "USD")]),
            cost_period([("Tax", "0.25", "USD"), ("Refund", "-0.10", "USD")]),
        ],
        "UnblendedCost",
        "USD",
    )
    assert result == {
        "known_gross_project_spend": "2.50",
        "currency": "USD",
        "aggregation_dimension": "RECORD_TYPE",
        "gross_aggregation": "SUM_POSITIVE_PERIOD_GROUP_AMOUNTS",
        "negative_amount_treatment": "EXCLUDE_WITHOUT_NETTING",
        "metric_row_count": 4,
        "record_types": ["Credit", "Refund", "Tax", "Usage"],
        "excluded_negative_offsets_usd": "5.10",
    }


def test_gross_spend_accepts_verified_zero_rows() -> None:
    result = aggregate_gross_spend([cost_period([("Usage", "0", "USD")])], "UnblendedCost", "USD")
    assert result["known_gross_project_spend"] == "0"
    assert result["metric_row_count"] == 1


@pytest.mark.parametrize(
    "periods",
    [
        [],
        [None],
        [{}],
        [{"Groups": []}],
        [{"Groups": [{}]}],
        [{"Groups": [None]}],
        [{"Groups": [{"Keys": [], "Metrics": {}}]}],
        [{"Groups": [{"Keys": [1], "Metrics": {}}]}],
        [{"Groups": [{"Keys": [""], "Metrics": {}}]}],
        [{"Groups": [{"Keys": ["Usage", "Tax"], "Metrics": {}}]}],
        [{"Groups": [{"Keys": ["Usage"], "Metrics": None}]}],
        [{"Groups": [{"Keys": ["Usage"], "Metrics": {}}]}],
        [cost_period([("Usage", "bad", "USD")])],
        [cost_period([("Usage", "1", "")])],
        [cost_period([("Usage", "NaN", "USD")])],
        [cost_period([("Usage", "Infinity", "USD")])],
        [cost_period([("Usage", "1", "EUR")])],
        [cost_period([("Usage", "1", "USD"), ("Tax", "0.1", "EUR")])],
    ],
)
def test_gross_spend_rejects_missing_malformed_or_mixed_data(
    periods: object,
) -> None:
    with pytest.raises(Stage2Rejected):
        aggregate_gross_spend(periods, "UnblendedCost", "USD")


@pytest.mark.parametrize(
    "observation",
    [
        cost_observation(currency="EUR"),
        cost_observation(updated_epoch=0),
        cost_observation(known_gross_project_spend="9.00"),
        cost_observation(known_gross_project_spend="8.95"),
        cost_observation(known_gross_project_spend="-1"),
    ],
)
def test_budget_unknown_or_insufficient_rejects(observation: dict[str, object]) -> None:
    with pytest.raises(Stage2Rejected):
        budget_headroom(observation, COST, 1000)


def test_glue_inventory_and_versioned_cleanup_fail_closed() -> None:
    contract = {
        "compared_fields": ["Name", "GlueVersion"],
        "definition": {"Name": "probe", "GlueVersion": "5.1"},
    }
    assert validate_glue_job({"Name": "probe", "GlueVersion": "5.1", "run_count": 0}, contract)[
        "zero_runs"
    ]
    assert validate_inventory(
        {
            "pagination_complete": True,
            "access_denied": [],
            "workload_resources": [],
            "probe_residue": [],
        }
    )["clean"]
    assert validate_s3_cleanup([])["prefix_empty"]
    with pytest.raises(Stage2Rejected):
        validate_glue_job({"Name": "probe", "GlueVersion": "4.0", "run_count": 0}, contract)
    with pytest.raises(Stage2Rejected):
        validate_glue_job({"Name": "probe", "GlueVersion": "5.1", "run_count": 1}, contract)
    for bad in (
        {
            "pagination_complete": False,
            "access_denied": [],
            "workload_resources": [],
            "probe_residue": [],
        },
        {
            "pagination_complete": True,
            "access_denied": ["glue"],
            "workload_resources": [],
            "probe_residue": [],
        },
        {
            "pagination_complete": True,
            "access_denied": [],
            "workload_resources": ["ledgerguard-job"],
            "probe_residue": [],
        },
        {
            "pagination_complete": True,
            "access_denied": [],
            "workload_resources": [],
            "probe_residue": ["marker"],
        },
    ):
        with pytest.raises(Stage2Rejected):
            validate_inventory(bad)
    with pytest.raises(Stage2Rejected):
        validate_s3_cleanup([{"Key": "probe", "VersionId": "v1"}])


def test_canonical_bytes_and_nested_policy_values_are_deterministic() -> None:
    from ledgerguard.stage2.control import normalize_policy

    assert canonical_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    value = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "A",
                "Effect": "Allow",
                "Action": "x:y",
                "Resource": "r",
                "Condition": {"ForAnyValue:StringEquals": {"key": [{"b": 2, "a": 1}, "z"]}},
            }
        ],
    }
    normalized = normalize_policy(value)
    assert normalized["Statement"][0]["Condition"]["ForAnyValue:StringEquals"]["key"] == [
        "z",
        {"a": 1, "b": 2},
    ]
