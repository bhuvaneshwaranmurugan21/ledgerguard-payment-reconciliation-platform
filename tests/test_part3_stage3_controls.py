from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from ledgerguard.stage3.profiles import PROFILES
from ledgerguard.stage3.scenarios import SCENARIO_SEED, SCENARIOS

ROOT = Path(__file__).resolve().parents[1]


def _json(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha(relative: str) -> str:
    return sha256((ROOT / relative).read_bytes()).hexdigest()


def test_stage2_closure_receipt_is_exact_and_correction_is_append_only() -> None:
    receipt = "spec/part3-stage2-external-closure-v1.json"
    correction = _json("spec/part3-stage2-external-closure-correction-v1.json")
    assert _sha(receipt) == "5be2b65d425278ba0d19c5cf34cf3cf8e15737a751f9d686b00a467dec594764"
    assert correction["original_receipt_sha256"] == _sha(receipt)
    assert correction["original_receipt_mutated"] is False
    assert correction["unaffected_fields_remain_authoritative"] is True


def test_stage3_baseline_protects_every_inherited_authority() -> None:
    freeze = _json("spec/part3-stage3-baseline-freeze-v1.json")
    assert freeze["base"] == {
        "commit": "d0fb01392f7f975909229f418c13a9c73ba8395e",
        "tree": "6be2444b583fde20d6fd84d47a87cde9432e2952",
        "sole_parent": "aa136331e44dcd181f766b42d76ee2616a22f435",
    }
    for relative, digest in freeze["protected_authorities"].items():  # type: ignore[union-attr]
        assert _sha(relative) == digest
    implementation = {
        "production_admission": "src/ledgerguard/reconciliation/admission.py",
        "production_transaction": "src/ledgerguard/reconciliation/transaction.py",
        "production_settlement": "src/ledgerguard/reconciliation/settlement.py",
        "production_correction": "src/ledgerguard/reconciliation/correction.py",
        "reference_oracle": "src/ledgerguard_reference_oracle/oracle.py",
        "historical_stage7_spark": "src/ledgerguard_part2_stage7_spark.py",
    }
    for name, relative in implementation.items():
        assert _sha(relative) == freeze["implementation_baseline"][name]  # type: ignore[index]


def test_requirement_gate_and_traceability_sets_are_total_and_bidirectional() -> None:
    requirement_authority = _json("spec/part3-stage3-requirements-v1.json")
    gate_authority = _json("spec/part3-stage3-gate-registry-v1.json")
    trace = _json("spec/part3-stage3-traceability-v1.json")
    requirement_ids = [
        row["requirement_id"]
        for row in requirement_authority["requirements"]  # type: ignore[union-attr]
    ]
    gate_ids = [row["gate_id"] for row in gate_authority["gates"]]  # type: ignore[index]
    assert requirement_ids == [f"P3-S3-R{index:03d}" for index in range(1, 31)]
    assert gate_ids == [f"P3-S3-G{index:03d}" for index in range(1, 25)]
    traced_requirements = trace["requirements"]  # type: ignore[assignment]
    traced_gates = trace["gates"]  # type: ignore[assignment]
    assert [row["requirement_id"] for row in traced_requirements] == requirement_ids
    assert [row["gate_id"] for row in traced_gates] == gate_ids
    assert all(
        row["gate_ids"] and row["implementation"] and row["tests"] and row["evidence"]
        for row in traced_requirements
    )
    for gate in traced_gates:
        assert gate["requirement_ids"]
        reverse = {
            row["requirement_id"]
            for row in traced_requirements
            if gate["gate_id"] in row["gate_ids"]
        }
        assert reverse == set(gate["requirement_ids"])


def test_only_three_master_gaps_are_owned_and_downstream_owners_remain_open() -> None:
    requirements = _json("spec/part3-stage3-requirements-v1.json")
    execution = _json("contracts/part3-stage3-execution-v1.json")
    assert requirements["owned_master_gaps"] == ["LG-P3-G003", "LG-P3-G005", "LG-P3-G011"]
    assert execution["owned_master_gaps"] == requirements["owned_master_gaps"]
    master = _json("spec/part3-master-gates-v1.json")
    states = {row["gate_id"]: row["state"] for row in master["gates"]}  # type: ignore[index]
    assert states["plan_only_verified"] == "NOT_EXECUTED"
    assert states["zero_workload_canary_verified"] == "NOT_EXECUTED"
    assert states["teardown_verified"] == "NOT_EXECUTED"


def test_profile_registry_matches_immutable_code_values() -> None:
    authority = _json("spec/part3-stage3-profile-registry-v1.json")
    rows = authority["profiles"]  # type: ignore[assignment]
    for row, profile in zip(rows, PROFILES.values(), strict=True):
        assert {
            key: value for key, value in row.items() if key != "scale_unit"
        } == profile.semantic_value()
        assert row["scale_unit"] == "PROCESSOR_EVENT"


def test_scenario_registry_contains_every_required_semantic_family() -> None:
    authority = _json("spec/part3-stage3-scenario-registry-v1.json")
    assert authority["campaign_seed"] == SCENARIO_SEED
    assert [
        (row["scenario_id"], row["title"], row["expected"])
        for row in authority["scenarios"]  # type: ignore[union-attr]
    ] == list(SCENARIOS)
    titles = " ".join(row["title"] for row in authority["scenarios"])  # type: ignore[index]
    for token in (
        "multi-currency",
        "mismatch",
        "formula",
        "missing",
        "invalid",
        "split",
        "replay",
        "conflict",
        "reference",
        "partition",
        "isolation",
        "late-data",
        "corrected-source",
        "policy",
        "skewed",
        "duplicate",
        "unknown",
    ):
        assert token in titles


def test_stage3_schemas_are_draft_2020_12_and_closed() -> None:
    for path in sorted((ROOT / "contracts/part3-stage3").glob("*.schema.json")):
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False


def test_stage3_runtime_and_ci_have_no_aws_sdk_or_oidc_permission() -> None:
    forbidden_modules = {"boto3", "botocore", "awswrangler"}
    for path in sorted((ROOT / "src/ledgerguard/stage3").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert imported.isdisjoint(forbidden_modules)
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "part3-stage3-current:" in workflow
    stage3 = workflow.split("part3-stage3-current:", 1)[1]
    assert "part3-stage3-artifact-inspection:" in stage3
    assert "inspect_part3_stage3_ci_artifact.py" in stage3
    assert "id-token: write" not in stage3
    assert "aws-actions/configure-aws-credentials" not in stage3


def test_status_claims_stage2_external_and_stage3_non_aws_candidate() -> None:
    status = (ROOT / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "PART3_STAGE3_IMPLEMENTED_PENDING_EXACT_HEAD_CI" in status
    assert "Stage 3 AWS execution: false" in status
    assert "P3-S2-G020 EXTERNALLY_VERIFIED" in status
    assert "Part 3 Stage 3 | `IMPLEMENTED_PENDING_EXACT_HEAD_CI`" in readme
    assert "The overall project remains in progress" in readme


def test_stage3_test_execution_authority_lists_the_complete_owned_suite() -> None:
    authority = _json("spec/part3-stage3-test-execution-v1.json")
    assert [row["path"] for row in authority["suites"]] == [  # type: ignore[index]
        "tests/test_part3_stage3_assets.py",
        "tests/test_part3_stage3_spark.py",
        "tests/test_part3_stage3_failures.py",
        "tests/test_part3_stage3_job.py",
        "tests/test_part3_stage3_package.py",
        "tests/test_part3_stage3_controls.py",
        "tests/test_part3_stage3_tooling.py",
    ]
