from __future__ import annotations

from pathlib import Path

import pytest

from tools.part3_stage6.workflow_policy import WORKFLOWS, validate_workflows

ROOT = Path(__file__).resolve().parents[1]


def test_exact_stage6_workflows_pass() -> None:
    result = validate_workflows(ROOT)
    assert result["workflows"] == ["plan", "recovery", "role", "static"]
    assert result["apply_commands"] == 0


@pytest.mark.parametrize(
    ("workflow", "needle", "replacement", "message"),
    [
        ("static", 'python-version: "3.11.13"', 'python-version: "3.12"', "invariant"),
        ("static", "-lockfile=readonly", "-lockfile=update", "invariant"),
        ("plan", "refs/heads/main", "refs/heads/other", "invariant"),
        ("plan", "cancel-in-progress: false", "cancel-in-progress: true", "invariant"),
        (
            "role",
            "LedgerGuardPart3ReadOnlyRole",
            "LedgerGuardPart3UnknownRole",
            "invariant",
        ),
        (
            "role",
            "retention-days: 90",
            "retention-days: 90\n          # ${{ secrets.PART3_BACKEND_KMS_KEY_ARN }}",
            "discover the backend key",
        ),
        (
            "plan",
            "administrator_receipt_base64:",
            "administrator_receipt_weakened:",
            "invariant",
        ),
        ("recovery", "retention-days: 90", "retention-days: 7", "invariant"),
    ],
)
def test_workflow_mutations_fail(
    tmp_path: Path, workflow: str, needle: str, replacement: str, message: str
) -> None:
    for name, relative in WORKFLOWS.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (ROOT / relative).read_text()
        if name == workflow:
            assert needle in source
            source = source.replace(needle, replacement, 1)
        target.write_text(source)
    with pytest.raises(ValueError, match=message):
        validate_workflows(tmp_path)


def test_prohibited_command_and_missing_or_symlink_fail(tmp_path: Path) -> None:
    for relative in WORKFLOWS.values():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text())
    plan = tmp_path / WORKFLOWS["plan"]
    plan.write_text(plan.read_text() + "\n# terraform apply\n")
    with pytest.raises(ValueError, match="prohibited"):
        validate_workflows(tmp_path)
    plan.write_text((ROOT / WORKFLOWS["plan"]).read_text())
    role = tmp_path / WORKFLOWS["role"]
    role.write_text(role.read_text() + "\n# start-query-execution\n")
    with pytest.raises(ValueError, match="role workflow contains prohibited"):
        validate_workflows(tmp_path)
    role.write_text((ROOT / WORKFLOWS["role"]).read_text())
    (tmp_path / WORKFLOWS["recovery"]).unlink()
    with pytest.raises(ValueError, match="regular recovery"):
        validate_workflows(tmp_path)


@pytest.mark.parametrize(
    ("workflow", "mutate", "message"),
    [
        ("static", lambda value: value.replace("actions: read", "id-token: write"), "broader"),
        (
            "recovery",
            lambda value: value.replace(
                "group: ledgerguard-part3-stage6-plan-only-",
                "group: ledgerguard-part3-stage6-recovery-",
            ),
            "concurrency",
        ),
        (
            "plan",
            lambda value: (
                value.replace(
                    "Establish all source and dispatch invariants before OIDC",
                    "Source placeholder before OIDC",
                    1,
                )
                + "\n# Establish all source and dispatch invariants\n"
            ),
            "before offline admission",
        ),
        (
            "role",
            lambda value: (
                value.replace("Admit exact source before OIDC", "Source placeholder", 1)
                + "\n# Admit exact source before OIDC\n"
            ),
            "before offline admission",
        ),
    ],
)
def test_workflow_authority_and_order_fail(
    tmp_path: Path, workflow: str, mutate: object, message: str
) -> None:
    for name, relative in WORKFLOWS.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (ROOT / relative).read_text()
        if name == workflow:
            source = mutate(source)  # type: ignore[operator]
        target.write_text(source)
    with pytest.raises(ValueError, match=message):
        validate_workflows(tmp_path)
