from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerguard.stage2.control import Stage2Rejected, normalize_policy, policy_diff
from ledgerguard.stage2.validation import validate_repository

ROOT = Path(__file__).resolve().parents[1]


def policy(*statements: dict[str, object]) -> dict[str, object]:
    return {"Version": "2012-10-17", "Statement": list(statements)}


def statement(
    sid: str = "Read",
    action: object = "s3:GetBucketLocation",
    resource: object = "arn:aws:s3:::bucket",
    condition: object | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {"Sid": sid, "Effect": "Allow", "Action": action, "Resource": resource}
    if condition is not None:
        row["Condition"] = condition
    return row


def test_policy_normalization_handles_order_scalar_lists_and_url_encoding() -> None:
    first = policy(
        statement(action=["s3:GetBucketVersioning", "s3:GetBucketLocation"], resource=["b", "a"])
    )
    second = {
        "Statement": [
            statement(
                action=["s3:GetBucketLocation", "s3:GetBucketVersioning"], resource=["a", "b"]
            )
        ],
        "Version": "2012-10-17",
    }
    assert policy_diff(first, second) == {"equal": True, "missing": [], "excess": [], "changed": []}
    encoded = (
        "%7B%22Version%22%3A%222012-10-17%22%2C%22Statement%22%3A%7B%22Sid%22%3A"
        "%22Read%22%2C%22Effect%22%3A%22Allow%22%2C%22Action%22%3A%22s3%3A"
        "GetBucketLocation%22%2C%22Resource%22%3A%22arn%3Aaws%3As3%3A%3A%3A"
        "bucket%22%7D%7D"
    )
    assert normalize_policy(encoded) == normalize_policy(policy(statement()))


def test_policy_diff_reports_missing_excess_and_semantic_change() -> None:
    desired = policy(statement("A"), statement("B", action="s3:GetBucketVersioning"))
    live = policy(statement("B", action="s3:GetBucketPolicy"), statement("C"))
    assert policy_diff(desired, live) == {
        "equal": False,
        "missing": ["A"],
        "excess": ["C"],
        "changed": ["B"],
    }


@pytest.mark.parametrize(
    "change",
    ["version", "field", "effect", "sid", "duplicate", "not-action", "not-resource", "wildcard"],
)
def test_unsafe_or_ambiguous_policy_is_rejected(change: str) -> None:
    row = statement()
    document = policy(row)
    if change == "version":
        document["Version"] = "2008-10-17"
    elif change == "field":
        document["Extra"] = True
    elif change == "effect":
        row["Effect"] = "Deny"
    elif change == "sid":
        row.pop("Sid")
    elif change == "duplicate":
        document["Statement"] = [row, dict(row)]
    elif change == "not-action":
        row["NotAction"] = "iam:*"
    elif change == "not-resource":
        row["NotResource"] = "*"
    else:
        row["Action"] = "s3:*"
    with pytest.raises(Stage2Rejected):
        normalize_policy(document)


@pytest.mark.parametrize(
    "change",
    [
        "audience",
        "subject",
        "wildcard",
        "pass-role",
        "pass-service",
        "global-write",
        "workload-start",
        "principal",
        "resource",
        "approved-global",
        "effective-authority",
        "scoped-write",
    ],
)
def test_checked_in_iam_contract_cannot_broaden(tmp_path: Path, change: str) -> None:
    import shutil

    root = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"
        ),
    )
    if change in {"audience", "subject", "wildcard", "principal"}:
        path = root / "contracts/part3-stage2-oidc-trust-v1.json"
        value = json.loads(path.read_text())
        condition = value["policy"]["Statement"][0]["Condition"]["StringEquals"]
        if change == "audience":
            condition["token.actions.githubusercontent.com:aud"] = "other"
        elif change == "subject":
            condition["token.actions.githubusercontent.com:sub"] = (
                "repo:bhuvaneshwaranmurugan21/"
                "ledgerguard-payment-reconciliation-platform:ref:refs/heads/main"
            )
        elif change == "wildcard":
            condition["token.actions.githubusercontent.com:sub"] = "repo:*"
        else:
            value["policy"]["Statement"][0]["Principal"]["Federated"] = (
                "arn:aws:iam::857229544428:oidc-provider/other.example"
            )
    else:
        path = root / "contracts/part3-stage2-iam-permissions-v1.json"
        value = json.loads(path.read_text())
        rows = value["policy"]["Statement"]
        backend_actions = set(next(row for row in rows if row["Sid"] == "InspectBackend")["Action"])
        # S3 API operation names and IAM authorization action names differ for
        # these two reads. Keep the independently documented IAM names frozen.
        assert {
            "s3:GetEncryptionConfiguration",
            "s3:GetLifecycleConfiguration",
        } <= backend_actions
        assert (
            not {
                "s3:GetBucketEncryption",
                "s3:GetBucketLifecycleConfiguration",
            }
            & backend_actions
        )
        pass_row = next(row for row in rows if row["Sid"] == "PassExactGlueProbeRole")
        if change == "pass-role":
            pass_row["Resource"] = "*"
        elif change == "pass-service":
            pass_row["Condition"]["StringEquals"]["iam:PassedToService"] = "ec2.amazonaws.com"
        elif change == "global-write":
            rows.append(
                {"Sid": "Bad", "Effect": "Allow", "Action": "s3:PutObject", "Resource": "*"}
            )
        elif change == "workload-start":
            rows.append(
                {"Sid": "Bad", "Effect": "Allow", "Action": "glue:StartJobRun", "Resource": "*"}
            )
            value["approved_global_read_actions"].append("glue:StartJobRun")
        elif change == "resource":
            next(row for row in rows if row["Sid"] == "ProbeBackendPrefix")["Resource"] = "*"
        elif change == "approved-global":
            value["approved_global_read_actions"].append("s3:PutObject")
        elif change == "effective-authority":
            value["effective_authority"]["permissions_boundary_required_absent"] = False
        else:
            next(row for row in rows if row["Sid"] == "InspectBackend")["Action"].append(
                "s3:PutBucketPolicy"
            )
    path.write_text(json.dumps(value))
    with pytest.raises(Stage2Rejected):
        validate_repository(root)
