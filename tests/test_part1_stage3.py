from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.foundation import FoundationError, validate_contract_coherence

ROOT = Path(__file__).resolve().parents[1]
Mutation = Callable[[dict[str, Any]], None]


def _copy_repository(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"
        ),
    )
    return destination


def _mutate_json(root: Path, relative: str, mutation: Mutation) -> None:
    path = root / relative
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _rebind_stage3_artifact(root: Path, relative: str) -> None:
    completion_path = root / "contracts/part1-stage3-completion-v1.json"
    evidence_path = root / "evidence/part1-stage3-local.json"
    completion: dict[str, Any] = json.loads(completion_path.read_text(encoding="utf-8"))
    matches = [
        (name, artifact)
        for name, artifact in completion["coherence_artifacts"].items()
        if artifact["path"] == relative
    ]
    assert len(matches) == 1
    name, artifact = matches[0]
    artifact["sha256"] = sha256((root / relative).read_bytes()).hexdigest()
    completion_path.write_text(json.dumps(completion, indent=2) + "\n", encoding="utf-8")

    evidence: dict[str, Any] = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["coherence_artifact_digests"][name] = artifact["sha256"]
    evidence["completion_contract_sha256"] = sha256(completion_path.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


def test_coh_t013_traceability_is_bidirectional_and_has_no_orphans() -> None:
    profile = json.loads((ROOT / "spec/contract-coherence-v1.json").read_text())
    traceability = json.loads((ROOT / "spec/contract-coherence-traceability-v1.json").read_text())
    completion = json.loads((ROOT / "contracts/part1-stage3-completion-v1.json").read_text())
    requirement_ids = [item["id"] for item in profile["requirements"]]
    assert [item["id"] for item in traceability["requirements"]] == requirement_ids
    mapped_gates = [
        gate for requirement in traceability["requirements"] for gate in requirement["gates"]
    ]
    assert mapped_gates == completion["required_gates"]
    assert len(mapped_gates) == len(set(mapped_gates))
    owned = {
        requirement
        for artifact in traceability["artifact_ownership"]
        for requirement in artifact["requirement_ids"]
    }
    assert owned == set(requirement_ids)


@pytest.mark.parametrize(
    "relative,mutation,match",
    [
        (
            "contracts/part1-stage3-completion-v1.json",
            lambda value: value["baseline"].update({"main_sha": "0" * 40}),
            "Stage 3 baseline differs",
        ),
        (
            "contracts/part1-stage3-completion-v1.json",
            lambda value: value["required_gates"].remove("EXACT_HEAD_CI_SUCCESS"),
            "completion gates and traceability differ",
        ),
        (
            "spec/contract-coherence-v1.json",
            lambda value: value.update({"unresolved_coherence_decisions": ["OPEN"]}),
            "coherence decisions remain",
        ),
        (
            "spec/contract-coherence-v1.json",
            lambda value: value["execution_boundary"].update({"aws_execution": True}),
            "coherence profile aws_execution must be false",
        ),
        (
            "spec/contract-coherence-v1.json",
            lambda value: value["manifest_family_contracts"].update(
                {"BANK_ENTRIES": "urn:ledgerguard:unknown:v2"}
            ),
            "manifest family contract bindings differ",
        ),
        (
            "spec/contract-coherence-vectors-v1.json",
            lambda value: value["source_digest"].update({"expected_sha256": "0" * 64}),
            "source golden digest differs",
        ),
        (
            "spec/contract-coherence-traceability-v1.json",
            lambda value: value["requirements"][0]["gates"].append("UNOWNED_GATE"),
            "completion gates and traceability differ",
        ),
    ],
)
def test_coh_t014_stage3_mutations_fail_closed(
    tmp_path: Path, relative: str, mutation: Mutation, match: str
) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(repository, relative, mutation)
    if relative.startswith("spec/"):
        _rebind_stage3_artifact(repository, relative)
    with pytest.raises(FoundationError, match=match):
        validate_contract_coherence(repository)


def test_coh_t015_stage3_foundation_is_deterministic() -> None:
    first = validate_contract_coherence(ROOT)
    second = validate_contract_coherence(ROOT)
    assert first == second
    assert first["stage"] == 3
    assert len(first["stage3_sha256"]) == 64
    assert len(first["foundation_sha256"]) == 64


def test_coh_t016_prior_stages_and_all_schema_bytes_are_preserved(tmp_path: Path) -> None:
    result = validate_contract_coherence(ROOT)
    assert (
        result["stage0_sha256"]
        == "3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b"
    )
    assert (
        result["stage1_sha256"]
        == "4234ac61999de769b87b2329512a8741761023b6c258dfd2207beb66f7dbc191"
    )
    assert (
        result["stage2_sha256"]
        == "3e8a3cdb753d94d013f592429bd8691f5ad100221496eb17e61864dc8d3b270c"
    )

    repository = _copy_repository(tmp_path)
    v1 = repository / "contracts/processor-event-v1.schema.json"
    v1.write_text(v1.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(FoundationError, match="preserved stage validation failed"):
        validate_contract_coherence(repository)

    repository = _copy_repository(tmp_path / "active")
    v2 = repository / "contracts/v2/processor-event-v2.schema.json"
    v2.write_text(v2.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(FoundationError, match="active contract digest differs"):
        validate_contract_coherence(repository)


def test_coh_t017_completion_evidence_and_scope_are_digest_bound(tmp_path: Path) -> None:
    completion_path = ROOT / "contracts/part1-stage3-completion-v1.json"
    completion = json.loads(completion_path.read_text())
    evidence = json.loads((ROOT / "evidence/part1-stage3-local.json").read_text())
    for artifact in completion["coherence_artifacts"].values():
        assert sha256((ROOT / artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]
    assert (
        evidence["completion_contract_sha256"] == sha256(completion_path.read_bytes()).hexdigest()
    )
    assert all(value is False for value in completion["execution_boundary"].values())

    repository = _copy_repository(tmp_path)
    runtime = repository / "src/ledgerguard/engine.py"
    runtime.write_text("# runtime is outside Part 1 Stage 3\n", encoding="utf-8")
    with pytest.raises(FoundationError, match="preserved stage validation failed"):
        validate_contract_coherence(repository)
