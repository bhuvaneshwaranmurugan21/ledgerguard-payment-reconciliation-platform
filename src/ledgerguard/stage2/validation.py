"""Repository-level validation for the Part 3 Stage 2 implementation transaction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ledgerguard.stage2.aws_cli import COMMANDS, FORBIDDEN
from ledgerguard.stage2.control import (
    ENTRY_COMMIT,
    MAIN_REF,
    OIDC_SUBJECT,
    REPOSITORY,
    STAGE2_REQUIREMENTS,
    normalize_policy,
    read_object,
    require,
    sha256_bytes,
    validate_stage2_authority,
)

WORKFLOWS = (
    ".github/workflows/part3-stage2-read-only.yml",
    ".github/workflows/part3-stage2-capability.yml",
    ".github/workflows/part3-stage2-recovery.yml",
)
PINNED_ACTIONS = {
    "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
    "actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38",
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    "aws-actions/configure-aws-credentials@e6de054238d6b7531b4efff3b6587d9aade6a06c",
}
WORKFLOW_PERMISSIONS = {
    ".github/workflows/part3-stage2-read-only.yml": "contents: read\nid-token: write",
    ".github/workflows/part3-stage2-capability.yml": (
        "actions: read\ncontents: read\nid-token: write"
    ),
    ".github/workflows/part3-stage2-recovery.yml": (
        "actions: read\ncontents: read\nid-token: write"
    ),
}
WORKFLOW_INPUTS = {
    ".github/workflows/part3-stage2-read-only.yml": {"expected_sha"},
    ".github/workflows/part3-stage2-capability.yml": {
        "expected_sha",
        "preflight_run_id",
        "preflight_artifact_id",
        "preflight_run_attempt",
        "preflight_artifact_sha256",
        "preflight_inspection_sha256",
    },
    ".github/workflows/part3-stage2-recovery.yml": {
        "expected_sha",
        "failed_run_id",
        "failed_run_attempt",
        "failed_artifact_id",
        "failed_artifact_sha256",
        "failed_inspection_sha256",
        "journal_sha256",
    },
}
APPROVED_GLOBAL_READ_ACTIONS = {
    "budgets:ViewBudget",
    "ce:GetCostAndUsage",
    "cloudwatch:ListMetrics",
    "dynamodb:ListTables",
    "glue:GetJobs",
    "logs:DescribeLogGroups",
    "s3:ListAllMyBuckets",
    "servicequotas:ListServiceQuotas",
    "states:ListStateMachines",
    "states:ValidateStateMachineDefinition",
    "tag:GetResources",
}
EXPECTED_POLICY_ACTIONS = {
    "GlueDefinitionProbe": {
        "glue:CreateJob",
        "glue:DeleteJob",
        "glue:GetJob",
        "glue:GetJobRuns",
        "glue:GetTags",
    },
    "InspectAndProbeLease": {
        "dynamodb:DeleteItem",
        "dynamodb:DescribeContinuousBackups",
        "dynamodb:DescribeTable",
        "dynamodb:DescribeTimeToLive",
        "dynamodb:GetItem",
        "dynamodb:ListTagsOfResource",
        "dynamodb:PutItem",
        "dynamodb:Scan",
    },
    "InspectAthenaWorkgroup": {"athena:GetWorkGroup", "athena:ListQueryExecutions"},
    "InspectBackend": {
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:GetBucketLocation",
        "s3:GetBucketOwnershipControls",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketTagging",
        "s3:GetBucketVersioning",
        "s3:ListBucketVersions",
    },
    "InspectGlueProbeRole": {
        "iam:GetRole",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
    },
    "InspectOwnRole": {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
    },
    "InventoryGlueJobs": {"glue:GetJobs"},
    "PassExactGlueProbeRole": {"iam:PassRole"},
    "ProbeBackendPrefix": {"s3:DeleteObjectVersion", "s3:GetObjectVersion", "s3:PutObject"},
    "ReadCloudWatchEvidence": {"cloudwatch:ListMetrics", "logs:DescribeLogGroups"},
    "ReadCostAndBudget": {"budgets:ViewBudget", "ce:GetCostAndUsage"},
    "ReadGlobalResourceInventories": {"dynamodb:ListTables", "s3:ListAllMyBuckets"},
    "ReadInventoryAndQuotas": {"servicequotas:ListServiceQuotas", "tag:GetResources"},
    "ValidateStepFunctionsDefinition": {
        "states:ListStateMachines",
        "states:ValidateStateMachineDefinition",
    },
}


def _validate_policy_contract(root: Path) -> dict[str, Any]:
    trust = read_object(root / "contracts/part3-stage2-oidc-trust-v1.json")
    trust_policy = normalize_policy(trust["policy"])
    require(len(trust_policy["Statement"]) == 1, "one OIDC trust statement required")
    statement = trust_policy["Statement"][0]
    require(statement["Action"] == ["sts:AssumeRoleWithWebIdentity"], "OIDC action differs")
    condition = statement["Condition"]["StringEquals"]
    require(
        condition["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com",
        "OIDC audience differs",
    )
    require(
        condition["token.actions.githubusercontent.com:sub"] == OIDC_SUBJECT,
        "OIDC subject differs",
    )
    require(
        statement["Principal"]
        == {
            "Federated": [
                "arn:aws:iam::857229544428:oidc-provider/token.actions.githubusercontent.com"
            ]
        },
        "OIDC provider differs",
    )
    require("*" not in str(statement), "OIDC wildcard forbidden")
    permission = read_object(root / "contracts/part3-stage2-iam-permissions-v1.json")
    require(
        permission["policy_kind"] == "INLINE"
        and permission["policy_name"] == "LedgerGuardStage2QualificationPolicy"
        and permission["role_name"] == "LedgerGuardGitHubOidcRole",
        "IAM policy identity differs",
    )
    require(
        permission["required_role_tags"]
        == {
            "ManagedBy": "LedgerGuardBootstrap",
            "Project": "LedgerGuard",
            "Purpose": "GitHubOidc",
        },
        "OIDC role tag contract differs",
    )
    require(
        permission["effective_authority"]
        == {
            "permissions_boundary_required_absent": True,
            "scp_narrowing_detected_by_capability_probes": True,
        },
        "effective authority strategy differs",
    )
    policy = normalize_policy(permission["policy"])
    require(
        {row["Sid"]: set(row["Action"]) for row in policy["Statement"]} == EXPECTED_POLICY_ACTIONS,
        "Stage 2 IAM action inventory differs",
    )
    approved_global = set(permission["approved_global_read_actions"])
    require(
        approved_global == APPROVED_GLOBAL_READ_ACTIONS,
        "approved global read-action inventory differs",
    )
    forbidden_fragments = (
        "StartJobRun",
        "StartExecution",
        "StartSyncExecution",
        "StartQueryExecution",
    )
    for row in policy["Statement"]:
        actions = row["Action"]
        resources = row["Resource"]
        require(
            not any(fragment in action for action in actions for fragment in forbidden_fragments),
            "workload-start permission forbidden",
        )
        if resources == ["*"]:
            require(set(actions).issubset(approved_global), "unapproved global-resource action")
        if "iam:PassRole" in actions:
            require(
                resources == ["arn:aws:iam::857229544428:role/LedgerGuardGlueProbeRole"],
                "PassRole resource differs",
            )
            require(
                row["Condition"] == {"StringEquals": {"iam:PassedToService": "glue.amazonaws.com"}},
                "PassRole condition differs",
            )
    resources = {row["Sid"]: row["Resource"] for row in policy["Statement"]}
    require(
        resources["InspectOwnRole"] == ["arn:aws:iam::857229544428:role/LedgerGuardGitHubOidcRole"]
        and resources["InspectGlueProbeRole"]
        == ["arn:aws:iam::857229544428:role/LedgerGuardGlueProbeRole"]
        and resources["InspectBackend"]
        == ["arn:aws:s3:::ledgerguard-tfstate-857229544428-ap-southeast-2"]
        and resources["ProbeBackendPrefix"]
        == ["arn:aws:s3:::ledgerguard-tfstate-857229544428-ap-southeast-2/qualification/*"]
        and resources["InspectAndProbeLease"]
        == ["arn:aws:dynamodb:ap-southeast-2:857229544428:table/ledgerguard-operation-leases"]
        and resources["GlueDefinitionProbe"]
        == ["arn:aws:glue:ap-southeast-2:857229544428:job/ledgerguard-stage2-*"]
        and resources["InspectAthenaWorkgroup"]
        == ["arn:aws:athena:ap-southeast-2:857229544428:workgroup/primary"],
        "scoped IAM resource differs",
    )
    return {
        "trust_sha256": sha256_bytes(str(trust_policy).encode()),
        "permission_statements": len(policy["Statement"]),
    }


def _validate_workflows(root: Path) -> dict[str, Any]:
    actions: set[str] = set()
    for name in WORKFLOWS:
        text = (root / name).read_text()
        header = text.split("permissions:", 1)[0]
        permission_block = text.split("permissions:\n", 1)[1].split("\n\n", 1)[0]
        normalized_permissions = "\n".join(line.strip() for line in permission_block.splitlines())
        require(
            text.count("permissions:") == 1
            and normalized_permissions == WORKFLOW_PERMISSIONS[name],
            f"workflow permissions differ: {name}",
        )
        input_names = set(re.findall(r"^      ([a-z][a-z0-9_]*):$", header, re.MULTILINE))
        require(
            input_names == WORKFLOW_INPUTS[name]
            and header.count("required: true") == len(input_names)
            and header.count("type: string") == len(input_names),
            f"workflow dispatch inputs differ: {name}",
        )
        require("workflow_dispatch:" in header, f"manual dispatch missing: {name}")
        require(
            "pull_request:" not in header
            and "push:" not in header
            and "workflow_call:" not in header,
            f"automatic AWS trigger forbidden: {name}",
        )
        for marker in (
            'test "${{ github.ref }}" = "refs/heads/main"',
            'test "${{ github.sha }}" = "$EXPECTED_SHA"',
            'test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"',
            'test "$AWS_ROLE_ARN" = "arn:aws:iam::857229544428:role/LedgerGuardGitHubOidcRole"',
            "inputs.expected_sha",
            "id-token: write",
            "cancel-in-progress: false",
            "timeout-minutes:",
            "mask-aws-account-id: true",
        ):
            require(marker in text, f"workflow control missing ({marker}): {name}")
        for forbidden in (
            "continue-on-error:",
            "pull_request_target:",
            "secrets.",
            "ubuntu-latest",
            "CloudShell",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AKIA",
            "ASIA",
        ):
            require(forbidden not in text, f"workflow boundary violation ({forbidden}): {name}")
        allowed_input_fields = {
            "EXPECTED_SHA",
            "PREFLIGHT_RUN_ID",
            "PREFLIGHT_RUN_ATTEMPT",
            "PREFLIGHT_ARTIFACT_ID",
            "PREFLIGHT_ARTIFACT_SHA256",
            "PREFLIGHT_INSPECTION_SHA256",
            "FAILED_RUN_ID",
            "FAILED_RUN_ATTEMPT",
            "FAILED_ARTIFACT_ID",
            "FAILED_ARTIFACT_SHA256",
            "FAILED_INSPECTION_SHA256",
            "FAILED_JOURNAL_SHA256",
            "CHECKED_OUT_SHA",
            "ref",
            "name",
        }
        for line in text.splitlines():
            if "${{ inputs." in line:
                require(
                    line.strip().split(":", 1)[0] in allowed_input_fields,
                    f"dispatch input interpolated outside YAML field: {name}",
                )
        actions.update(re.findall(r"uses: ([^\s]+)", text))
        if name.endswith("capability.yml"):
            require("actions: read" in text, "capability artifact read permission missing")
            require(
                "Independently bind accepted read-only artifact before OIDC" in text,
                "capability source evidence binding missing",
            )
            require(
                text.index("Independently bind accepted read-only artifact before OIDC")
                < text.index("Assume exact repository OIDC role"),
                "capability source evidence is not bound before OIDC",
            )
        if name.endswith("recovery.yml"):
            require("actions: read" in text, "recovery artifact read permission missing")
            require(
                "Bind failed mutation journal before OIDC" in text,
                "recovery journal binding missing",
            )
            require(
                text.index("Bind failed mutation journal before OIDC")
                < text.index("Assume exact repository OIDC role"),
                "recovery journal is not bound before OIDC",
            )
    require(actions == PINNED_ACTIONS, "workflow action pin inventory differs")
    automatic = (root / ".github/workflows/ci.yml").read_text()
    require(
        "id-token:" not in automatic and "configure-aws-credentials" not in automatic,
        "automatic CI can access AWS",
    )
    require(
        not any(action in FORBIDDEN for command in COMMANDS.values() for action in command),
        "adapter contains forbidden operation",
    )
    return {
        "workflows": len(WORKFLOWS),
        "actions": sorted(actions),
        "aws_operations": len(COMMANDS),
    }


def validate_repository(root: Path) -> dict[str, Any]:
    authority = validate_stage2_authority(root)
    execution = read_object(root / "contracts/part3-stage2-execution-v1.json")
    require(execution["entry"]["commit"] == ENTRY_COMMIT, "Stage 2 entry differs")
    require(
        execution["requirements"] == list(STAGE2_REQUIREMENTS), "execution requirement list differs"
    )
    require(
        execution["workflow_boundary"]
        == {
            "event": "workflow_dispatch",
            "ref": MAIN_REF,
            "exact_sha_input": True,
            "short_lived_oidc": True,
        },
        "execution boundary differs",
    )
    target = read_object(root / ".github/ledgerguard-target.json")
    require(
        target["repository"] == REPOSITORY
        and target["default_branch"] == "main"
        and target["region"] == "ap-southeast-2"
        and target["oidc_role_name"] == "LedgerGuardGitHubOidcRole",
        "frozen target differs",
    )
    control = read_object(root / "contracts/part3-stage2-control-plane-v1.json")
    require(
        control["backend"]["use_lockfile"] is True
        and control["backend"]["dynamodb_backend_locking"] is False,
        "backend locking decision differs",
    )
    require(
        control["bootstrap_boundary"] == "ADMINISTRATOR_SIDE_SEPARATE_REVIEWED_TRANSACTION",
        "bootstrap boundary differs",
    )
    require(
        control["lease"]["ttl_attribute"] == "expires_epoch"
        and control["lease"]["pitr_decision"] == "ENABLED"
        and control["backend"]["required_lifecycle"]["prefix"] == "qualification/",
        "control-plane retention or recovery contract differs",
    )
    cost = read_object(root / "contracts/part3-stage2-cost-v1.json")
    require(
        cost["gross_project_ceiling_usd"] == "10.00"
        and cost["missing_or_stale"] == "UNKNOWN_BLOCK_MUTATION",
        "cost authority differs",
    )
    glue = read_object(root / "contracts/part3-stage2-glue-probe-v1.json")
    require(
        glue["definition"]["GlueVersion"] == "5.1" and glue["start_allowed"] is False,
        "Glue qualification contract differs",
    )
    asl = read_object(root / "fixtures/part3-stage2/qualification.asl.json")
    require(
        asl["States"]["Pass"]["Type"] == "Pass" and asl["States"]["Pass"]["End"] is True,
        "qualification ASL differs",
    )
    operation_contract = read_object(root / "contracts/part3-stage2-operation-allowlist-v1.json")
    require(
        operation_contract["allowed_operations"] == sorted(COMMANDS)
        and operation_contract["operation_count"] == len(COMMANDS),
        "AWS operation contract differs",
    )
    evidence_schema = read_object(root / "contracts/part3/stage2-live-evidence-v1.schema.json")
    Draft202012Validator.check_schema(evidence_schema)
    status = (
        (root / "PROJECT_STATUS.md")
        .read_text()
        .split("## Active boundary", 1)[1]
        .split("## ", 1)[0]
    )
    for marker in (
        "Stage: 2 — Exact-target AWS qualification",
        "PART3_STAGE2_IN_PROGRESS",
        "AWS execution: false",
        "Stage 1 external closure: `EXTERNALLY_VERIFIED`",
    ):
        require(marker in status, f"active Stage 2 status missing: {marker}")
    return {
        "authority": authority,
        "policy": _validate_policy_contract(root),
        "workflows": _validate_workflows(root),
        "contracts_verified": True,
    }
