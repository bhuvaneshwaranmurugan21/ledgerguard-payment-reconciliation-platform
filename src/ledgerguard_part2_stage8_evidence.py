"""Semantic mutation evidence for LedgerGuard Part 2 Stage 8."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ledgerguard_part2_stage8_validation import MUTATION_CLASSES, Stage8Error, validate_stage8

IGNORED = shutil.ignore_patterns(
    ".git",
    ".rsync-tmp",
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


def _json(root: Path, relative: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((root / relative).read_text(encoding="utf-8")))


def _write(root: Path, relative: str, value: dict[str, Any]) -> None:
    (root / relative).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _closure_field(relative: str, field: str, value: object) -> Callable[[Path], None]:
    def mutate(root: Path) -> None:
        document = _json(root, relative)
        document[field] = value
        _write(root, relative, document)

    return mutate


def _remove_requirement(root: Path) -> None:
    relative = "spec/part2-stage8-requirements-v1.json"
    document = _json(root, relative)
    cast(list[dict[str, Any]], document["requirements"]).pop()
    _write(root, relative, document)


def _duplicate_requirement(root: Path) -> None:
    relative = "spec/part2-stage8-requirements-v1.json"
    document = _json(root, relative)
    requirements = cast(list[dict[str, Any]], document["requirements"])
    requirements.append(dict(requirements[-1]))
    _write(root, relative, document)


def _remove_gate(root: Path) -> None:
    relative = "spec/part2-stage8-gate-registry-v1.json"
    document = _json(root, relative)
    cast(list[dict[str, Any]], document["gates"]).pop()
    _write(root, relative, document)


def _master_field(gate: str, field: str, value: object) -> Callable[[Path], None]:
    def mutate(root: Path) -> None:
        relative = "spec/part2-master-gate-adjudication-v1.json"
        document = _json(root, relative)
        rows = cast(list[dict[str, Any]], document["master_gates"])
        row = next(item for item in rows if item["gate"] == gate)
        row[field] = value
        _write(root, relative, document)

    return mutate


def _claim_complete(root: Path) -> None:
    relative = "contracts/part2-stage8-promotion-v1.json"
    document = _json(root, relative)
    document["state"] = "LOCAL_RECONCILIATION_VERIFIED"
    _write(root, relative, document)


def _claim_aws(root: Path) -> None:
    relative = "contracts/part2-stage8-promotion-v1.json"
    document = _json(root, relative)
    cast(dict[str, Any], document["implementation_boundary"])["aws_execution"] = True
    _write(root, relative, document)


def _stale_documentation(root: Path) -> None:
    path = root / "README.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nStage 6 is now the local candidate.\n")


def _weaken_coverage(root: Path) -> None:
    relative = "spec/part2-stage8-coverage-v1.json"
    document = _json(root, relative)
    document["minimum_branch_percent"] = 99.0
    _write(root, relative, document)


def _drop_terminal_publication(root: Path) -> None:
    relative = "contracts/part2-stage8-promotion-v1.json"
    document = _json(root, relative)
    protocol = cast(dict[str, Any], document["promotion_protocol"])
    attestation = cast(dict[str, Any], protocol["closure_attestation_pull_request"])
    attestation["repository_record_required"] = False
    _write(root, relative, document)


def run_mutation_checks(repository: Path) -> dict[str, Any]:
    """Prove that representative Stage 8 authority corruptions fail closed."""
    mutations: dict[str, Callable[[Path], None]] = {
        "ACCEPT_STAGE7_COMMIT_DRIFT": _closure_field(
            "spec/part2-stage7-closure-freeze-v1.json", "squash_merge_commit", "0" * 40
        ),
        "ACCEPT_STAGE7_TREE_DRIFT": _closure_field(
            "spec/part2-stage7-closure-freeze-v1.json", "squash_merge_tree", "0" * 40
        ),
        "ACCEPT_NON_SQUASH_STAGE7": _closure_field(
            "spec/part2-stage7-closure-freeze-v1.json", "squash_merge_parent", "0" * 40
        ),
        "ACCEPT_STAGE7_ARTIFACT_DRIFT": _closure_field(
            "spec/part2-stage7-closure-freeze-v1.json", "ci_artifact_zip_sha256", "0" * 64
        ),
        "ALLOW_MISSING_REQUIREMENT": _remove_requirement,
        "ALLOW_DUPLICATE_REQUIREMENT": _duplicate_requirement,
        "ALLOW_MISSING_GATE": _remove_gate,
        "PROMOTE_UNSUPPORTED_MASTER_GATE": _master_field(
            "spark_parity_verified", "state", "VERIFIED_CANDIDATE"
        ),
        "ALLOW_FAILURE_OWNER_REASSIGNMENT": _master_field(
            "failure_matrix_verified", "implementation_owner", "PART2_STAGE7"
        ),
        "CLAIM_PART2_COMPLETE_PREMERGE": _claim_complete,
        "CLAIM_AWS_EXECUTION": _claim_aws,
        "ALLOW_STALE_ACTIVE_DOCUMENTATION": _stale_documentation,
        "WEAKEN_COVERAGE_THRESHOLD": _weaken_coverage,
        "DROP_TERMINAL_PUBLICATION": _drop_terminal_publication,
    }
    if list(mutations) != MUTATION_CLASSES:
        raise ValueError("Stage 8 mutation execution order differs from authority")
    killed: list[str] = []
    for name, mutate in mutations.items():
        with tempfile.TemporaryDirectory(prefix="ledgerguard-stage8-mutation-") as temporary:
            root = Path(temporary) / "repository"
            shutil.copytree(repository, root, ignore=IGNORED)
            mutate(root)
            try:
                validate_stage8(root)
            except Stage8Error:
                killed.append(name)
    survivors = [name for name in mutations if name not in killed]
    if survivors:
        raise ValueError(f"Stage 8 semantic mutants survived: {survivors}")
    return {"checks": len(mutations), "survivors": 0, "killed": killed}
