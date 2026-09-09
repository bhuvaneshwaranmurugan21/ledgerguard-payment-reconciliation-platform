"""Semantic mutation evidence for the Part 3 Stage 2 closure candidate."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ledgerguard_part3_stage2_closure import (
    MUTATION_CLASSES,
    Stage2ClosureError,
    validate_stage2_closure,
)

IGNORED = shutil.ignore_patterns(
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "*.egg-info",
    "build",
    "dist",
    ".coverage",
)


def _read(root: Path, relative: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((root / relative).read_text(encoding="utf-8")))


def _write(root: Path, relative: str, value: dict[str, Any]) -> None:
    (root / relative).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _qualified_commit(root: Path) -> None:
    relative = "spec/part3-stage2-operational-freeze-v1.json"
    value = _read(root, relative)
    value["qualified_commit"] = "0" * 40
    _write(root, relative, value)


def _operational_byte(root: Path) -> None:
    path = root / ".github/workflows/part3-stage2-read-only.yml"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")


def _receipt_commit(root: Path) -> None:
    relative = "evidence/part3-stage2/read-only-receipt-v1.json"
    value = _read(root, relative)
    value["commit"] = "0" * 40
    _write(root, relative, value)


def _iam_parity(root: Path) -> None:
    relative = "evidence/part3-stage2/read-only-receipt-v1.json"
    value = _read(root, relative)
    cast(dict[str, Any], value["iam"])["permissions_equal"] = False
    _write(root, relative, value)


def _cost(root: Path) -> None:
    relative = "evidence/part3-stage2/read-only-receipt-v1.json"
    value = _read(root, relative)
    cast(dict[str, Any], value["cost"])["verdict"] = "BLOCKED"
    _write(root, relative, value)


def _cleanup(root: Path) -> None:
    relative = "evidence/part3-stage2/capability-receipt-v1.json"
    value = _read(root, relative)
    cast(dict[str, Any], value["cleanup"])["complete"] = False
    _write(root, relative, value)


def _workload(root: Path) -> None:
    relative = "evidence/part3-stage2/capability-receipt-v1.json"
    value = _read(root, relative)
    value["glue_job_runs"] = 1
    _write(root, relative, value)


def _requirement(root: Path) -> None:
    relative = "spec/part3-stage2-requirement-adjudication-executed-v1.json"
    value = _read(root, relative)
    rows = cast(list[dict[str, Any]], value["requirements"])
    rows[0]["verdict"] = "NOT_EXECUTED"
    _write(root, relative, value)


def _external_gate(root: Path) -> None:
    relative = "spec/part3-stage2-gate-adjudication-v1.json"
    value = _read(root, relative)
    rows = cast(list[dict[str, Any]], value["gates"])
    rows[-1]["state"] = "EXTERNALLY_VERIFIED"
    _write(root, relative, value)


def _master_gate(root: Path) -> None:
    relative = "spec/part3-stage2-master-gate-adjudication-v1.json"
    value = _read(root, relative)
    rows = cast(list[dict[str, Any]], value["gates"])
    rows[-1]["state"] = "AWS_VERIFIED"
    _write(root, relative, value)


def _carryover(root: Path) -> None:
    relative = "spec/part3-gap-adjudication-v1.json"
    value = _read(root, relative)
    rows = cast(list[dict[str, Any]], value["gaps"])
    rows[0]["state"] = "OWNED_OPEN"
    _write(root, relative, value)


def _claim(root: Path) -> None:
    relative = "contracts/part3-stage2-stage3-handoff-v1.json"
    value = _read(root, relative)
    cast(dict[str, Any], value["claim_boundary"])["project_complete"] = True
    _write(root, relative, value)


def _quality(root: Path) -> None:
    relative = "spec/part3-stage2-closure-coverage-v1.json"
    value = _read(root, relative)
    value["minimum_branch_percent"] = 99.0
    _write(root, relative, value)


def run_closure_mutation_checks(repository: Path) -> dict[str, Any]:
    """Prove representative closure corruption is rejected."""
    mutations: dict[str, Callable[[Path], None]] = {
        "ACCEPT_QUALIFIED_COMMIT_DRIFT": _qualified_commit,
        "ACCEPT_OPERATIONAL_BYTE_DRIFT": _operational_byte,
        "ACCEPT_LIVE_RECEIPT_COMMIT_DRIFT": _receipt_commit,
        "ACCEPT_IAM_PARITY_FAILURE": _iam_parity,
        "ACCEPT_COST_HEADROOM_FAILURE": _cost,
        "ACCEPT_INCOMPLETE_CLEANUP": _cleanup,
        "ACCEPT_WORKLOAD_EXECUTION": _workload,
        "ALLOW_UNVERIFIED_REQUIREMENT": _requirement,
        "PREMATURELY_CLOSE_EXTERNAL_GATE": _external_gate,
        "ALLOW_EXCESS_MASTER_GATE": _master_gate,
        "LEAVE_OWNED_CARRYOVER_OPEN": _carryover,
        "ALLOW_INFLATED_HANDOFF_CLAIM": _claim,
        "ALLOW_WEAKENED_QUALITY_AUTHORITY": _quality,
    }
    if list(mutations) != MUTATION_CLASSES:
        raise ValueError("closure mutation order differs from authority")
    killed: list[str] = []
    for name, mutate in mutations.items():
        with tempfile.TemporaryDirectory(prefix="ledgerguard-part3-stage2-closure-") as temporary:
            root = Path(temporary) / "repository"
            shutil.copytree(repository, root, ignore=IGNORED)
            mutate(root)
            try:
                validate_stage2_closure(root)
            except Stage2ClosureError:
                killed.append(name)
    survivors = [name for name in mutations if name not in killed]
    if survivors:
        raise ValueError(f"closure semantic mutants survived: {survivors}")
    return {"checks": len(mutations), "survivors": 0, "killed": killed}
