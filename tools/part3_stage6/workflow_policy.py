"""Static admission of the Stage 6 CI, role, plan-only and recovery workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

WORKFLOWS = {
    "static": ".github/workflows/part3-stage6-static.yml",
    "role": ".github/workflows/part3-stage6-role-admission.yml",
    "plan": ".github/workflows/part3-stage6-plan-only.yml",
    "recovery": ".github/workflows/part3-stage6-recovery.yml",
}
PROHIBITED = (
    "terraform apply",
    "terraform force-unlock",
    "start-job-run",
    "start-query-execution",
    "start-execution",
    "invoke-function",
)


def _require(source: str, fragments: tuple[str, ...], label: str) -> None:
    missing = [fragment for fragment in fragments if fragment not in source]
    if missing:
        raise ValueError(f"{label} workflow invariant missing: {missing[0]}")


def validate_workflows(root: Path) -> dict[str, Any]:
    sources: dict[str, str] = {}
    for name, relative in WORKFLOWS.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"regular {name} workflow required")
        sources[name] = path.read_text(encoding="utf-8")
    static, role, plan, recovery = (
        sources["static"],
        sources["role"],
        sources["plan"],
        sources["recovery"],
    )
    _require(
        static,
        ("pull_request:\n", "push:\n", 'python-version: "3.11.13"', "-lockfile=readonly"),
        "static",
    )
    if "id-token: write" in static or "workflow_dispatch:" in static:
        raise ValueError("static workflow authority is broader than required")
    _require(
        role,
        (
            "on:\n  workflow_dispatch:",
            "id-token: write",
            'test "${{ github.ref }}" = refs/heads/main',
            "cancel-in-progress: false",
            "LedgerGuardGitHubOidcRole",
            "LedgerGuardPart3ReadOnlyRole",
            "LedgerGuardPart3RecoveryRole",
            "python -m tools.run_part3_stage6_role_probe",
            "aws-actions/configure-aws-credentials@e6de054238d6b7531b4efff3b6587d9aade6a06c",
            "retention-days: 90",
        ),
        "role",
    )
    if any(term in role.lower() for term in PROHIBITED):
        raise ValueError("role workflow contains prohibited workload or apply command")
    if "secrets." in role or "backend-kms-key-arn" in role.lower():
        raise ValueError("role workflow must discover the backend key read-only")
    for label, source in (("plan", plan), ("recovery", recovery)):
        _require(
            source,
            (
                "on:\n  workflow_dispatch:",
                "id-token: write",
                'test "${{ github.ref }}" = refs/heads/main',
                "cancel-in-progress: false",
                "arn:aws:iam::857229544428:role/LedgerGuardGitHubOidcRole",
                "aws-actions/configure-aws-credentials@e6de054238d6b7531b4efff3b6587d9aade6a06c",
                'rm -rf -- "$RUNNER_TEMP/ledgerguard-stage6-',
                "retention-days: 90",
            ),
            label,
        )
        if any(term in source.lower() for term in PROHIBITED):
            raise ValueError(f"{label} workflow contains prohibited workload or apply command")
    group = "group: ledgerguard-part3-stage6-plan-only-${{ github.repository }}"
    if group not in plan or group not in recovery:
        raise ValueError("plan and recovery concurrency groups differ")
    _require(
        plan,
        (
            "python -m tools.run_part3_stage6_plan",
            "python -m tools.inspect_part3_stage6_artifact",
            "administrator_receipt_base64:",
            'test -z "$(git status --porcelain)"',
        ),
        "plan",
    )
    _require(
        recovery,
        (
            "tools.part3_stage6.recovery import validate_failure_handoff",
            "python -m tools.run_part3_stage6_recovery",
            "failure_handoff_base64:",
        ),
        "recovery",
    )
    admission_labels = {
        "plan": "Establish all source and dispatch invariants",
        "recovery": "Admit exact source and handoff",
    }
    for label, source in (("plan", plan), ("recovery", recovery)):
        if source.index(admission_labels[label]) > source.index("configure-aws-credentials"):
            raise ValueError(f"{label} obtains AWS credentials before offline admission")
    if role.index("Admit exact source before OIDC") > role.index("configure-aws-credentials"):
        raise ValueError("role obtains AWS credentials before offline admission")
    return {
        "classification": "STAGE6_WORKFLOW_BOUNDARY_ADMITTED",
        "workflows": sorted(WORKFLOWS),
        "manual_workflows": ["role", "plan", "recovery"],
        "apply_commands": 0,
        "workload_commands": 0,
        "aws_calls": 0,
        "stage6_complete": False,
    }
