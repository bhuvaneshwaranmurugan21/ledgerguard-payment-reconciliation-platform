"""Semantic mutation evidence for the LedgerGuard Part 2 closure attestation."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ledgerguard_part2_stage8_closure import (
    MUTATION_CLASSES,
    Stage8ClosureError,
    validate_stage8_closure,
)

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


def _field(relative: str, field: str, value: object) -> Callable[[Path], None]:
    def mutate(root: Path) -> None:
        document = _json(root, relative)
        document[field] = value
        _write(root, relative, document)

    return mutate


def _protected_digest(root: Path) -> None:
    relative = "spec/part2-stage8-promotion-closure-freeze-v1.json"
    document = _json(root, relative)
    protected = cast(dict[str, str], document["protected_authorities"])
    protected["contracts/part2-stage8-promotion-v1.json"] = "0" * 64
    _write(root, relative, document)


def _master_gate(root: Path) -> None:
    relative = "spec/part2-completion-authority-v1.json"
    document = _json(root, relative)
    gates = cast(dict[str, str], document["master_part2_completion_gates"])
    gates["spark_parity_verified"] = "VERIFIED_CANDIDATE"
    _write(root, relative, document)


def _claim_aws(root: Path) -> None:
    relative = "spec/part2-completion-authority-v1.json"
    document = _json(root, relative)
    boundary = cast(dict[str, bool], document["claim_boundary"])
    boundary["aws_execution"] = True
    _write(root, relative, document)


def _completion_total(root: Path) -> None:
    relative = "spec/part2-completion-authority-v1.json"
    document = _json(root, relative)
    outcome = cast(dict[str, int], document["outcome"])
    outcome["requirements_pass"] = 202
    _write(root, relative, document)


def _stale_documentation(root: Path) -> None:
    path = root / "README.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "PR #17 completed the Stage 8 promotion audit",
            "PR #17 promotion remains pending",
        ),
        encoding="utf-8",
    )


def _recursive_attestation(root: Path) -> None:
    relative = "spec/part2-completion-authority-v1.json"
    document = _json(root, relative)
    publication = cast(dict[str, object], document["closure_attestation"])
    publication["method"] = "SELF_REFERENTIAL_POSTMERGE_RECORD"
    _write(root, relative, document)


def run_closure_mutation_checks(repository: Path) -> dict[str, Any]:
    """Prove representative closure corruption fails closed."""
    freeze = "spec/part2-stage8-promotion-closure-freeze-v1.json"
    authority = "spec/part2-completion-authority-v1.json"
    mutations: dict[str, Callable[[Path], None]] = {
        "ACCEPT_PROMOTION_COMMIT_DRIFT": _field(freeze, "squash_merge_commit", "0" * 40),
        "ACCEPT_PROMOTION_TREE_DRIFT": _field(freeze, "squash_merge_tree", "0" * 40),
        "ACCEPT_NON_SQUASH_PROMOTION": _field(freeze, "parent_count", 2),
        "ACCEPT_PROMOTION_ARTIFACT_DRIFT": _field(freeze, "ci_artifact_zip_sha256", "0" * 64),
        "ACCEPT_FAILED_POSTMERGE_MAIN": _field(freeze, "postmerge_main_ci_run", 0),
        "ACCEPT_PROMOTION_AUTHORITY_DRIFT": _protected_digest,
        "ALLOW_NONTERMINAL_PART2_STATE": _field(authority, "state", "PART2_IN_PROGRESS"),
        "ALLOW_UNVERIFIED_MASTER_GATE": _master_gate,
        "CLAIM_AWS_EXECUTION": _claim_aws,
        "ALLOW_INCORRECT_COMPLETION_TOTAL": _completion_total,
        "ALLOW_STALE_FINAL_DOCUMENTATION": _stale_documentation,
        "ALLOW_RECURSIVE_SELF_ATTESTATION": _recursive_attestation,
    }
    if list(mutations) != MUTATION_CLASSES:
        raise ValueError("closure mutation execution order differs from authority")
    killed: list[str] = []
    for name, mutate in mutations.items():
        with tempfile.TemporaryDirectory(
            prefix="ledgerguard-stage8-closure-mutation-"
        ) as temporary:
            root = Path(temporary) / "repository"
            shutil.copytree(repository, root, ignore=IGNORED)
            mutate(root)
            try:
                validate_stage8_closure(root)
            except Stage8ClosureError:
                killed.append(name)
    survivors = [name for name in mutations if name not in killed]
    if survivors:
        raise ValueError(f"closure semantic mutants survived: {survivors}")
    return {"checks": len(mutations), "survivors": 0, "killed": killed}
