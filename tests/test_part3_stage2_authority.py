from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ledgerguard.stage2.control import Stage2Rejected, validate_stage2_authority
from ledgerguard.stage2.validation import validate_repository

ROOT = Path(__file__).resolve().parents[1]


def copy_repository(tmp_path: Path) -> Path:
    target = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "*.egg-info",
            "build",
        ),
    )
    return target


def test_exact_stage2_entry_and_repository_contracts_are_complete() -> None:
    result = validate_repository(ROOT)
    assert result["authority"] == {
        "entry_verified": True,
        "requirements": 22,
        "gates": 20,
        "protected_paths": 420,
        "traceability_links": 22,
        "scenarios": 167,
    }
    assert result["contracts_verified"] is True
    assert result["workflows"]["workflows"] == 3


@pytest.mark.parametrize(
    "kind",
    ["closure", "protected", "requirement", "duplicate", "gate", "gate-pass", "scenario-schema"],
)
def test_authority_tampering_fails_closed(tmp_path: Path, kind: str) -> None:
    root = copy_repository(tmp_path)
    if kind == "closure":
        path = root / "spec/part3-stage1-external-closure-v1.json"
        value = json.loads(path.read_text())
        value["tree"] = "0" * 40
        path.write_text(json.dumps(value))
    elif kind == "protected":
        path = root / "contracts/part2-stage7-spark-parity-v1.json"
        path.write_text(path.read_text() + "\n")
    elif kind in {"requirement", "duplicate"}:
        path = root / "spec/part3-stage2-requirement-adjudication-v1.json"
        value = json.loads(path.read_text())
        if kind == "requirement":
            value["requirements"].pop()
        else:
            value["requirements"][1]["requirement_id"] = value["requirements"][0]["requirement_id"]
        path.write_text(json.dumps(value))
    elif kind in {"gate", "gate-pass"}:
        path = root / "spec/part3-stage2-gate-registry-v1.json"
        value = json.loads(path.read_text())
        if kind == "gate":
            value["gates"].pop()
        else:
            value["gates"][0]["state"] = "AWS_VERIFIED"
        path.write_text(json.dumps(value))
    else:
        path = root / "spec/part3-stage2-scenario-registry-v1.json"
        value = json.loads(path.read_text())
        value["schema_version"] = "2.0"
        path.write_text(json.dumps(value))
    with pytest.raises(Stage2Rejected):
        validate_stage2_authority(root)


@pytest.mark.parametrize(
    "kind",
    [
        "trigger",
        "ref",
        "sha",
        "oidc",
        "cancel",
        "action",
        "automatic-oidc",
        "status",
        "backend",
        "cost",
        "cost-aggregation",
        "glue",
        "artifact-order",
        "shell-input",
        "permissions",
        "dispatch-input",
        "static-key",
    ],
)
def test_repository_boundaries_reject_weakening(tmp_path: Path, kind: str) -> None:
    root = copy_repository(tmp_path)
    if kind in {
        "trigger",
        "ref",
        "sha",
        "oidc",
        "cancel",
        "action",
        "artifact-order",
        "shell-input",
        "permissions",
        "dispatch-input",
        "static-key",
    }:
        path = root / (
            ".github/workflows/part3-stage2-capability.yml"
            if kind in {"artifact-order", "shell-input", "permissions"}
            else ".github/workflows/part3-stage2-read-only.yml"
        )
        text = path.read_text()
        replacements = {
            "trigger": ("workflow_dispatch:", "push:"),
            "ref": ("refs/heads/main", "refs/heads/dev"),
            "sha": ("git rev-parse HEAD", "git rev-parse HEAD~1"),
            "oidc": ("id-token: write", "id-token: none"),
            "cancel": ("cancel-in-progress: false", "cancel-in-progress: true"),
            "action": (
                "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
                "actions/checkout@main",
            ),
            "artifact-order": (
                "Independently bind accepted read-only artifact before OIDC",
                "Z independently bind accepted read-only artifact before OIDC",
            ),
            "shell-input": (
                '[[ "$PREFLIGHT_RUN_ID" =~ ^[1-9][0-9]*$ ]]',
                '[[ "${{ inputs.preflight_run_id }}" =~ ^[1-9][0-9]*$ ]]',
            ),
            "permissions": ("  actions: read\n", "  actions: write\n"),
            "dispatch-input": ("        required: true", "        required: false"),
            "static-key": (
                "      EXPECTED_SHA: ${{ inputs.expected_sha }}",
                "      AWS_ACCESS_KEY_ID: unsafe-static-value",
            ),
        }
        old, new = replacements[kind]
        path.write_text(text.replace(old, new, 1))
    elif kind == "automatic-oidc":
        path = root / ".github/workflows/ci.yml"
        path.write_text(path.read_text() + "\n# id-token: write\n")
    elif kind == "status":
        path = root / "PROJECT_STATUS.md"
        path.write_text(path.read_text().replace("PART3_STAGE2_IN_PROGRESS", "PART3_COMPLETE", 1))
    else:
        path = (
            root
            / {
                "backend": "contracts/part3-stage2-control-plane-v1.json",
                "cost": "contracts/part3-stage2-cost-v1.json",
                "cost-aggregation": "contracts/part3-stage2-cost-v1.json",
                "glue": "contracts/part3-stage2-glue-probe-v1.json",
            }[kind]
        )
        value = json.loads(path.read_text())
        if kind == "backend":
            value["backend"]["use_lockfile"] = False
        elif kind == "cost":
            value["gross_project_ceiling_usd"] = "100.00"
        elif kind == "cost-aggregation":
            value["aggregation"]["negative_amount_treatment"] = "NET_AGAINST_CHARGES"
        else:
            value["start_allowed"] = True
        path.write_text(json.dumps(value))
    with pytest.raises(Stage2Rejected):
        validate_repository(root)
