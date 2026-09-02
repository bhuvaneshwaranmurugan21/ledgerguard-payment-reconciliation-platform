from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.part1 import (
    Part1CompletionError,
    reproduce_stage3,
    validate_part1_completion,
)
from ledgerguard_correction import materialize_stage4_view
from ledgerguard_correction_c4 import materialize_stage5_view

ACTIVE_ROOT = Path(__file__).resolve().parents[1]
_STAGE4_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory(prefix="ledgerguard-stage4-tests-")
_STAGE5_ROOT = materialize_stage5_view(
    ACTIVE_ROOT, Path(_STAGE4_TEMPORARY_DIRECTORY.name) / "stage5"
)
ROOT = materialize_stage4_view(_STAGE5_ROOT, Path(_STAGE4_TEMPORARY_DIRECTORY.name) / "repository")
Mutation = Callable[[dict[str, Any]], None]


def _copy_repository(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "*.egg-info",
        ),
    )
    return destination


def _mutate_json(root: Path, relative: str, mutation: Mutation) -> None:
    path = root / relative
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _rebind_completion_artifact(root: Path, relative: str) -> None:
    path = root / "contracts/part1-stage4-completion-v1.json"
    contract: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    matches = [
        artifact
        for artifact in contract["completion_artifacts"].values()
        if artifact["path"] == relative
    ]
    assert len(matches) == 1
    matches[0]["sha256"] = sha256((root / relative).read_bytes()).hexdigest()
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")


def test_p1c_t001_exact_stage3_baseline_and_provenance_are_bound() -> None:
    manifest = json.loads((ROOT / "history/part1/stage3/manifest-v1.json").read_text())
    source = manifest["source"]
    assert source["merge_sha"] == "e83ff73ea725fd930dc3bdd85442506da4248efa"
    assert source["tree_sha"] == "4607f15c133972f168b4fdab9257c4fdbffce6bb"
    assert source["exact_head_ci_run_id"] == 33520421011
    assert source["post_merge_main_ci_run_id"] == 33521251470


def test_p1c_t002_historical_stage_authorities_are_byte_preserved() -> None:
    profile = json.loads((ROOT / "spec/part1-foundation-freeze-v1.json").read_text())
    for stage in profile["stage_authorities"]:
        number = stage["stage"]
        completion = ROOT / f"contracts/part1-stage{number}-completion-v1.json"
        evidence = ROOT / f"evidence/part1-stage{number}-local.json"
        assert sha256(completion.read_bytes()).hexdigest() == stage["completion_sha256"]
        assert sha256(evidence.read_bytes()).hexdigest() == stage["evidence_sha256"]


def test_p1c_t003_v1_and_v2_schema_bytes_are_preserved_and_fail_closed(
    tmp_path: Path,
) -> None:
    result = reproduce_stage3(ROOT)
    assert len(result["schema_digests"]) == 8
    assert len(result["active_schema_digests"]) == 9

    legacy = _copy_repository(tmp_path / "legacy")
    path = legacy / "contracts/processor-event-v1.schema.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Part1CompletionError, match="preserved stage validation failed"):
        reproduce_stage3(legacy)

    active = _copy_repository(tmp_path / "active")
    path = active / "contracts/v2/processor-event-v2.schema.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Part1CompletionError, match="active contract digest differs"):
        reproduce_stage3(active)


def test_p1c_t004_all_prior_stage_digests_reproduce_exactly() -> None:
    result = reproduce_stage3(ROOT)
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
    assert (
        result["stage3_sha256"]
        == "7df73e3b2cbcd5a000c3a6238ff5801eed05d51024c90a6a861d390ac2c750cf"
    )


def test_p1c_t005_six_part1_project_gates_have_exact_owners() -> None:
    project = json.loads((ROOT / "contracts/project-completion-v1.json").read_text())
    profile = json.loads((ROOT / "spec/part1-foundation-freeze-v1.json").read_text())
    expected = project["parts"][0]["gates"]
    resolved = [item["gate"] for item in profile["resolved_project_gates"]]
    assert resolved == expected
    assert len(resolved) == len(set(resolved)) == 6


def test_p1c_t006_historical_snapshots_match_sha256_and_git_blob_identity() -> None:
    manifest = json.loads((ROOT / "history/part1/stage3/manifest-v1.json").read_text())
    for item in manifest["snapshots"]:
        data = (ROOT / item["snapshot_path"]).read_bytes()
        header = f"blob {len(data)}\0".encode()
        assert sha256(data).hexdigest() == item["sha256"]
        assert sha1(header + data).hexdigest() == item["git_blob_sha"]


def test_p1c_t007_active_status_is_consistent() -> None:
    readme = (ROOT / "README.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    for value in (readme, status):
        assert "PART1_FOUNDATION_COMPLETE" in value
        assert "PROJECT_IN_PROGRESS" in value
        assert "UNCLAIMED" in value
        assert "Stage 4" in value


def test_p1c_t008_scorecard_targets_are_not_claimed_as_achieved() -> None:
    profile = json.loads((ROOT / "spec/part1-foundation-freeze-v1.json").read_text())
    interpretation = profile["scorecard_interpretation"]
    assert interpretation["numeric_values"] == "PROJECT_TARGETS_NOT_ACHIEVED_SCORES"
    assert interpretation["final_achievement_audit_owner"] == "PART5"
    assert profile["claim_boundary"]["performance_and_scale"] == "UNCLAIMED"


def test_p1c_t009_evidence_claims_remain_honest() -> None:
    evidence = json.loads((ROOT / "evidence/part1-stage4-local.json").read_text())
    claims = evidence["claim_boundary"]
    assert claims["reconciliation_execution"] == "UNCLAIMED"
    assert claims["aws_execution"] is False
    assert claims["infrastructure_mutation"] is False
    assert evidence["external_ci"]["exact_head_ci"] == "REQUIRED_EXTERNAL"


def test_p1c_t010_no_reconciliation_runtime_or_aws_authority_is_added() -> None:
    package_files = {path.name for path in (ROOT / "src/ledgerguard").glob("*.py")}
    assert package_files == {
        "__init__.py",
        "foundation.py",
        "part1.py",
        "stage0.py",
        "stage1.py",
    }
    profile = json.loads((ROOT / "spec/part1-foundation-freeze-v1.json").read_text())
    assert all(value is False for value in profile["execution_boundary"].values())


def test_p1c_t011_part2_handoff_is_complete_and_digest_bound() -> None:
    handoff = json.loads((ROOT / "contracts/part1-part2-handoff-v1.json").read_text())
    assert handoff["state"] == "PART2_ENTRY_AUTHORITY_FROZEN"
    assert len(handoff["required_runtime_responsibilities"]) == 11
    assert len(handoff["forbidden_redefinitions"]) == 8
    for artifact in handoff["inherited_authorities"].values():
        assert sha256((ROOT / artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]


def test_p1c_t012_completion_traceability_is_bidirectional() -> None:
    traceability = json.loads((ROOT / "spec/part1-completion-traceability-v1.json").read_text())
    contract = json.loads((ROOT / "contracts/part1-stage4-completion-v1.json").read_text())
    assert [item["id"] for item in traceability["requirements"]] == [
        f"P1C-{number:03d}" for number in range(1, 15)
    ]
    gates = [gate for item in traceability["requirements"] for gate in item["gates"]]
    tests = [test for item in traceability["requirements"] for test in item["tests"]]
    assert gates == contract["required_gates"]
    assert sorted(tests) == traceability["expected_test_ids"]
    for field in ("unmapped_requirements", "unowned_gates", "orphan_tests", "orphan_artifacts"):
        assert traceability[field] == []


def test_p1c_t013_part1_completion_validator_is_deterministic() -> None:
    first = validate_part1_completion(ROOT)
    second = validate_part1_completion(ROOT)
    assert first == second
    assert len(first["stage4_sha256"]) == 64
    assert len(first["part1_sha256"]) == 64


@pytest.mark.parametrize(
    "relative,mutation,rebind,match",
    [
        (
            "contracts/part1-stage4-completion-v1.json",
            lambda value: value["baseline"].update({"main_sha": "0" * 40}),
            False,
            "Stage 4 baseline differs",
        ),
        (
            "spec/part1-foundation-freeze-v1.json",
            lambda value: value.update({"unresolved_completion_decisions": ["OPEN"]}),
            False,
            "completion decisions remain",
        ),
        (
            "spec/part1-foundation-freeze-v1.json",
            lambda value: value["claim_boundary"].update({"aws_execution": True}),
            False,
            "claims AWS execution",
        ),
        (
            "contracts/part1-part2-handoff-v1.json",
            lambda value: value["claim_boundary"].update(
                {"part2_reconciliation_execution": "LOCAL_VERIFIED"}
            ),
            False,
            "handoff claim inflated",
        ),
        (
            "spec/part1-completion-traceability-v1.json",
            lambda value: value["requirements"][0]["gates"].append("UNOWNED_GATE"),
            True,
            "completion gates and traceability differ",
        ),
        (
            "evidence/part1-stage4-local.json",
            lambda value: value["claim_boundary"].update({"aws_execution": True}),
            False,
            "claims AWS execution",
        ),
    ],
)
def test_p1c_t014_adversarial_authority_mutations_fail_closed(
    tmp_path: Path,
    relative: str,
    mutation: Mutation,
    rebind: bool,
    match: str,
) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(repository, relative, mutation)
    if rebind:
        _rebind_completion_artifact(repository, relative)
    with pytest.raises(Part1CompletionError, match=match):
        validate_part1_completion(repository)


def test_p1c_t014_snapshot_and_runtime_mutations_fail_closed(tmp_path: Path) -> None:
    snapshot_repository = _copy_repository(tmp_path / "snapshot")
    path = snapshot_repository / "history/part1/stage3/README.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Part1CompletionError, match="historical snapshot drift"):
        validate_part1_completion(snapshot_repository)

    runtime_repository = _copy_repository(tmp_path / "runtime")
    (runtime_repository / "src/ledgerguard/engine.py").write_text(
        "# executable runtime is outside Part 1\n", encoding="utf-8"
    )
    with pytest.raises(Part1CompletionError, match="historical Stage 3 validation failed"):
        validate_part1_completion(runtime_repository)


def test_p1c_t015_part1_is_complete_while_project_remains_in_progress() -> None:
    result = validate_part1_completion(ROOT)
    assert result["state"] == "PART1_FOUNDATION_COMPLETE"
    assert result["project_state"] == "PROJECT_IN_PROGRESS"
    assert result["remaining_part1_work"] == []
    assert result["external_ci_required"] is True


def test_p1c_t016_completion_evidence_requires_external_ci_and_preserves_scope() -> None:
    contract_path = ROOT / "contracts/part1-stage4-completion-v1.json"
    contract = json.loads(contract_path.read_text())
    evidence = json.loads((ROOT / "evidence/part1-stage4-local.json").read_text())
    assert evidence["completion_contract_sha256"] == sha256(contract_path.read_bytes()).hexdigest()
    assert contract["external_completion_rule"] == {
        "candidate_state": "LOCAL_VERIFIED_AFTER_CI",
        "exact_head_ci": "REQUIRED",
        "manual_merge": "REQUIRED",
        "post_merge_main_ci": "REQUIRED",
    }
    assert all(value is False for value in contract["execution_boundary"].values())
