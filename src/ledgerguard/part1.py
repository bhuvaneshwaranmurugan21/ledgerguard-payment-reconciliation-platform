"""Fail-closed validation for the LedgerGuard Part 1 completion freeze."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any

from .foundation import FoundationError, parse_contract_json, validate_contract_coherence

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE_STATE = "PART1_COMPLETION_GOVERNANCE_FROZEN"
PART1_STATE = "PART1_FOUNDATION_COMPLETE"
PROJECT_STATE = "PROJECT_IN_PROGRESS"
EXPECTED_BASELINE = {
    "main_sha": "e83ff73ea725fd930dc3bdd85442506da4248efa",
    "main_tree_sha": "4607f15c133972f168b4fdab9257c4fdbffce6bb",
    "accepted_stage3_head_sha": "0d42a71af0295728ad5745f130ddf7710c317ad7",
    "stage3_pr_number": 6,
    "stage3_pr_ci_run_id": 33520421011,
    "stage3_post_merge_ci_run_id": 33521251470,
}
EXPECTED_STAGE_DIGESTS = {
    "stage0_sha256": "3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b",
    "stage1_sha256": "4234ac61999de769b87b2329512a8741761023b6c258dfd2207beb66f7dbc191",
    "stage2_sha256": "3e8a3cdb753d94d013f592429bd8691f5ad100221496eb17e61864dc8d3b270c",
    "stage3_sha256": "7df73e3b2cbcd5a000c3a6238ff5801eed05d51024c90a6a861d390ac2c750cf",
}
EXPECTED_STAGE3_FOUNDATION_SHA256 = (
    "10754ed611ef0bca50c741821de2aa9a699826e03da2e3a436866c2028d2b6ab"
)
PRESERVED_AUTHORITIES = {
    "stage0_completion": (
        "contracts/part1-stage0-completion-v1.json",
        "81fb7b9863b255cdc19768e80972e2174f940e0d0be97c31cf6ab0cecd4b66c5",
    ),
    "stage1_completion": (
        "contracts/part1-stage1-completion-v1.json",
        "d766641ccd150f3a188b1d156b912cde7473752c7af911b13876ad2c50a61ece",
    ),
    "stage2_completion": (
        "contracts/part1-stage2-completion-v1.json",
        "8464ce66ddc8dcf153f8a09915d0676778caf140e28533a864ab14e40adb7fe9",
    ),
    "stage3_completion": (
        "contracts/part1-stage3-completion-v1.json",
        "91135fd72ef6ebd8275cac6172d27a44cf9751c213d79dd2abf407478854fc98",
    ),
    "stage0_evidence": (
        "evidence/part1-stage0-local.json",
        "1e17b6034731ccf59a44d6f28dc3fd9a87840e08794b72b339ac8ddc20bdc4e7",
    ),
    "stage1_evidence": (
        "evidence/part1-stage1-local.json",
        "f7a3b39edbdc952942c760820a562ad67b1a810b33732f26f948df9ae047e1f2",
    ),
    "stage2_evidence": (
        "evidence/part1-stage2-local.json",
        "2c2ba56ffa26158edc152ecef3077c618f3532ece2a5681e71da5806058923db",
    ),
    "stage3_evidence": (
        "evidence/part1-stage3-local.json",
        "bc1e11be4995d8748e50f687ade5ed139758952d49232f29b5680a42c423bcc8",
    ),
    "project_completion": (
        "contracts/project-completion-v1.json",
        "9a323c8b7800c90fc3ad1697ec407f6756ceebba8df266ab88deba97fe6017b6",
    ),
    "aws_target": (
        ".github/ledgerguard-target.json",
        "d9dccdc0dbae17638f02ac6596be1b1f0a8c24dddc57974f97024ed1cc415058",
    ),
    "ci_workflow": (
        ".github/workflows/ci.yml",
        "fa33b7e798875f32f06629fb2b958df40a527989c2b04a7c8f2d0649bf65b521",
    ),
    "stage3_validator": (
        "src/ledgerguard/foundation.py",
        "9dfef400c294017d0ac5eeac32cd7ed6602f6c45cf19403e3dbe3419814d181b",
    ),
}
EXPECTED_SNAPSHOTS = {
    "README.md": (
        "history/part1/stage3/README.md",
        "3950b52c0f68b127ea602eca9eb3d38bfb6c6739e7886024220eaf35f3614687",
        "8e2c874dab58ce16826892c907c46a4030448032",
    ),
    "PROJECT_STATUS.md": (
        "history/part1/stage3/PROJECT_STATUS.md",
        "74d3a2250d872dcf32fec050a2e9e7cf8d146875ec5831330b3e3a8875d30c4f",
        "0c5dc0b8c9b2ee6e6652e2e651bd8a03efb4a9a1",
    ),
    "tests/test_contract_coherence.py": (
        "history/part1/stage3/tests/test_contract_coherence.py",
        "16202874220a81e1add901dfb637397b6408ced46cc84ba2324b6f86c9c32772",
        "bd13e273047992bb6f3b8b19c3a3de69b9efc2b3",
    ),
    "tests/test_part1_stage3.py": (
        "history/part1/stage3/tests/test_part1_stage3.py",
        "7f3542ba781f6213fdc2545ab578dfe44f4e649acaaea20b18b6239da68a0f7f",
        "d91538315e371973a0949a3a340a548ae6daff9a",
    ),
}
EXPECTED_PROJECT_GATES = [
    "draft_disposition_audited",
    "two_grain_model_frozen",
    "contracts_valid",
    "scorecard_frozen",
    "aws_target_correct",
    "foundation_ci_success",
]
EXPECTED_REQUIREMENT_IDS = [f"P1C-{number:03d}" for number in range(1, 15)]
EXPECTED_TEST_IDS = [f"P1C-T{number:03d}" for number in range(1, 17)]
EXPECTED_REQUIRED_GATES = [
    "EXACT_STAGE3_BASELINE_BOUND",
    "STAGE0_TO_STAGE3_PROVENANCE_COMPLETE",
    "HISTORICAL_STAGE_BYTES_PRESERVED",
    "HISTORICAL_V1_AND_ACTIVE_V2_BYTES_PRESERVED",
    "STAGE0_TO_STAGE3_DIGESTS_REPRODUCED",
    "PART1_PROJECT_GATES_EXACTLY_RESOLVED",
    "MUTABLE_STAGE3_SURFACES_SNAPSHOTTED",
    "ACTIVE_STATUS_CONSISTENT",
    "TARGET_SCORES_NOT_CLAIMED_AS_ACHIEVED",
    "EVIDENCE_CLAIMS_ARE_HONEST",
    "NO_RECONCILIATION_RUNTIME_OR_AWS_MUTATION",
    "PART2_HANDOFF_FROZEN",
    "PART1_TRACEABILITY_BIDIRECTIONAL",
    "PART1_VALIDATOR_DETERMINISTIC",
    "ADVERSARIAL_MUTATIONS_FAIL_CLOSED",
    "REMAINING_PART1_WORK_ZERO",
    "PROJECT_REMAINS_IN_PROGRESS",
    "FULL_REGRESSION_AND_FRESH_INSTALL_PASS",
    "EXACT_HEAD_CI_SUCCESS",
    "POST_MERGE_MAIN_CI_SUCCESS",
]
ALLOWED_PACKAGE_FILES = {
    "__init__.py",
    "foundation.py",
    "part1.py",
    "stage0.py",
    "stage1.py",
}


class Part1CompletionError(FoundationError):
    """Raised when the checked-in Part 1 completion authority fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Part1CompletionError(message)


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Part1CompletionError(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise Part1CompletionError(message)
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        value = parse_contract_json(path.read_text(encoding="utf-8"))
    except (OSError, FoundationError) as error:
        raise Part1CompletionError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise Part1CompletionError(f"JSON object required: {path}")
    return value


def _load_preserved_json(path: Path) -> dict[str, Any]:
    """Load an immutable historical authority after its exact digest is verified."""

    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Part1CompletionError(f"cannot load preserved authority {path}: {error}") from error
    if not isinstance(value, dict):
        raise Part1CompletionError(f"preserved JSON object required: {path}")
    return value


def _safe_file(root: Path, relative: str, label: str) -> Path:
    relative_path = Path(relative)
    _require(
        not relative_path.is_absolute() and ".." not in relative_path.parts,
        f"{label} path escapes repository",
    )
    path = root / relative_path
    _require(path.is_file(), f"{label} missing: {relative}")
    return path


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return sha1(header + data).hexdigest()


def _validate_preserved_authorities(root: Path) -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, (relative, expected) in PRESERVED_AUTHORITIES.items():
        digest = sha256(_safe_file(root, relative, name).read_bytes()).hexdigest()
        _require(digest == expected, f"preserved authority drift: {relative}")
        actual[name] = digest
    return actual


def _validate_history_manifest(root: Path) -> dict[str, str]:
    manifest = _load(root / "history/part1/stage3/manifest-v1.json")
    _require(manifest.get("project") == PROJECT, "history manifest project differs")
    _require(manifest.get("part") == 1 and manifest.get("stage") == 3, "history stage differs")
    source = _mapping(manifest.get("source"), "history source missing")
    expected_source = {
        "pr_number": 6,
        "accepted_head_sha": EXPECTED_BASELINE["accepted_stage3_head_sha"],
        "merge_sha": EXPECTED_BASELINE["main_sha"],
        "tree_sha": EXPECTED_BASELINE["main_tree_sha"],
        "exact_head_ci_run_id": EXPECTED_BASELINE["stage3_pr_ci_run_id"],
        "post_merge_main_ci_run_id": EXPECTED_BASELINE["stage3_post_merge_ci_run_id"],
        "completion_contract_sha256": PRESERVED_AUTHORITIES["stage3_completion"][1],
        "evidence_sha256": PRESERVED_AUTHORITIES["stage3_evidence"][1],
        "stage3_sha256": EXPECTED_STAGE_DIGESTS["stage3_sha256"],
        "foundation_sha256": EXPECTED_STAGE3_FOUNDATION_SHA256,
    }
    _require(dict(source) == expected_source, "history source provenance differs")

    snapshots = _list(manifest.get("snapshots"), "history snapshots missing")
    _require(len(snapshots) == len(EXPECTED_SNAPSHOTS), "history snapshot count differs")
    actual: dict[str, str] = {}
    for item_value in snapshots:
        item = _mapping(item_value, "history snapshot entry must be an object")
        logical = item.get("logical_path")
        if not isinstance(logical, str) or logical not in EXPECTED_SNAPSHOTS:
            raise Part1CompletionError("snapshot path differs")
        snapshot, expected_digest, expected_blob = EXPECTED_SNAPSHOTS[logical]
        _require(item.get("snapshot_path") == snapshot, f"snapshot location differs: {logical}")
        _require(
            item.get("sha256") == expected_digest, f"snapshot digest record differs: {logical}"
        )
        _require(
            item.get("git_blob_sha") == expected_blob, f"snapshot blob record differs: {logical}"
        )
        data = _safe_file(root, snapshot, "historical snapshot").read_bytes()
        digest = sha256(data).hexdigest()
        _require(digest == expected_digest, f"historical snapshot drift: {snapshot}")
        _require(_git_blob_sha(data) == expected_blob, f"historical blob drift: {snapshot}")
        _require(logical not in actual, f"duplicate historical snapshot: {logical}")
        actual[logical] = digest
    _require(set(actual) == set(EXPECTED_SNAPSHOTS), "historical snapshot inventory differs")
    boundary = _mapping(manifest.get("execution_boundary"), "history execution boundary missing")
    _require(all(value is False for value in boundary.values()), "history boundary claims mutation")
    return actual


def stage3_artifact_path(root: Path, logical: str) -> Path:
    """Resolve accepted Stage 3 bytes for a logical artifact path."""

    snapshot = EXPECTED_SNAPSHOTS.get(logical)
    return root / (snapshot[0] if snapshot is not None else logical)


def reproduce_stage3(root: Path, *, verify_preserved_authorities: bool = True) -> dict[str, Any]:
    """Reproduce accepted Stage 3 from its append-only historical view."""

    if verify_preserved_authorities:
        _validate_preserved_authorities(root)
    _validate_history_manifest(root)
    with tempfile.TemporaryDirectory(prefix="ledgerguard-stage3-view-") as temporary:
        view = Path(temporary) / "repository"
        shutil.copytree(
            root,
            view,
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
        for logical, (snapshot, _, _) in EXPECTED_SNAPSHOTS.items():
            shutil.copyfile(root / snapshot, view / logical)
        try:
            result = validate_contract_coherence(view)
        except FoundationError as error:
            raise Part1CompletionError(f"historical Stage 3 validation failed: {error}") from error
    for key, expected in EXPECTED_STAGE_DIGESTS.items():
        _require(result.get(key) == expected, f"historical {key} differs")
    _require(
        result.get("foundation_sha256") == EXPECTED_STAGE3_FOUNDATION_SHA256,
        "historical Stage 3 foundation digest differs",
    )
    return result


def _artifact_digests(root: Path, artifacts: Mapping[str, Any]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, artifact_value in artifacts.items():
        artifact = _mapping(artifact_value, f"completion artifact {name} must be an object")
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(relative, str) or not relative:
            raise Part1CompletionError(f"artifact path missing: {name}")
        digest = sha256(_safe_file(root, relative, "completion artifact").read_bytes()).hexdigest()
        _require(expected == digest, f"completion artifact digest differs: {relative}")
        actual[name] = digest
    return actual


def _validate_project_contract(root: Path, profile: Mapping[str, Any]) -> str:
    completion_path = root / "contracts/project-completion-v1.json"
    completion = _load_preserved_json(completion_path)
    parts = _list(completion.get("parts"), "project completion parts missing")
    part1 = _mapping(parts[0], "Part 1 project contract missing")
    _require(part1.get("part") == 1, "Part 1 project contract identity differs")
    _require(part1.get("required_state") == PART1_STATE, "Part 1 required state differs")
    _require(part1.get("aws_workload_allowed") is False, "Part 1 authorizes AWS workload")
    _require(part1.get("gates") == EXPECTED_PROJECT_GATES, "Part 1 project gates differ")

    resolved = _list(profile.get("resolved_project_gates"), "resolved project gates missing")
    resolved_names = [
        _mapping(item, "resolved project gate invalid").get("gate") for item in resolved
    ]
    _require(resolved_names == EXPECTED_PROJECT_GATES, "resolved project gates differ")
    _require(len(resolved_names) == len(set(resolved_names)), "project gate has multiple owners")

    scorecard = _mapping(completion.get("scorecard"), "project scorecard missing")
    _require(len(scorecard) == 12, "project scorecard dimension count differs")
    for dimension, value in scorecard.items():
        _require(
            isinstance(value, (int, float)) and not isinstance(value, bool) and 7 < value <= 10,
            f"scorecard target differs: {dimension}",
        )
    interpretation = _mapping(
        profile.get("scorecard_interpretation"), "scorecard interpretation missing"
    )
    _require(
        interpretation.get("numeric_values") == "PROJECT_TARGETS_NOT_ACHIEVED_SCORES",
        "scorecard targets are misrepresented",
    )
    _require(
        interpretation.get("final_achievement_audit_owner") == "PART5",
        "final scorecard audit owner differs",
    )
    return sha256(completion_path.read_bytes()).hexdigest()


def _validate_handoff(root: Path) -> str:
    path = root / "contracts/part1-part2-handoff-v1.json"
    handoff = _load(path)
    _require(handoff.get("project") == PROJECT, "handoff project differs")
    _require(handoff.get("from_part") == 1 and handoff.get("to_part") == 2, "handoff parts differ")
    _require(handoff.get("state") == "PART2_ENTRY_AUTHORITY_FROZEN", "handoff state differs")
    authorities = _mapping(handoff.get("inherited_authorities"), "handoff authorities missing")
    _artifact_digests(root, authorities)
    responsibilities = _list(
        handoff.get("required_runtime_responsibilities"), "runtime responsibilities missing"
    )
    forbidden = _list(handoff.get("forbidden_redefinitions"), "forbidden redefinitions missing")
    entry_gates = _list(handoff.get("entry_gates"), "Part 2 entry gates missing")
    _require(len(responsibilities) == 11, "runtime responsibility inventory differs")
    _require(
        len(responsibilities) == len(set(responsibilities)), "runtime responsibility duplicated"
    )
    _require(len(forbidden) == 8, "forbidden-redefinition inventory differs")
    _require(len(forbidden) == len(set(forbidden)), "forbidden redefinition duplicated")
    _require(
        entry_gates
        == [
            "PART1_FOUNDATION_COMPLETE",
            "PART1_AUTHORITIES_DIGEST_BOUND",
            "PART1_REMAINING_WORK_ZERO",
            "PART2_RUNTIME_RESPONSIBILITIES_OWNED",
            "NO_AWS_AUTHORITY_INHERITED",
        ],
        "Part 2 entry gates differ",
    )
    claims = _mapping(handoff.get("claim_boundary"), "handoff claim boundary missing")
    _require(claims.get("part2_reconciliation_execution") == "UNCLAIMED", "handoff claim inflated")
    _require(claims.get("aws_execution") is False, "handoff claims AWS execution")
    _require(claims.get("infrastructure_mutation") is False, "handoff claims mutation")
    return sha256(path.read_bytes()).hexdigest()


def _validate_traceability(
    traceability: Mapping[str, Any], required_gates: list[Any]
) -> tuple[int, int]:
    mappings = _list(traceability.get("requirements"), "completion traceability missing")
    ids = [_mapping(item, "traceability entry invalid").get("id") for item in mappings]
    _require(ids == EXPECTED_REQUIREMENT_IDS, "completion requirement IDs differ")
    mapped_gates: list[Any] = []
    mapped_tests: list[Any] = []
    for item_value in mappings:
        item = _mapping(item_value, "traceability entry invalid")
        profile_paths = _list(item.get("profile_paths"), "traceability profile paths missing")
        tests = _list(item.get("tests"), "traceability tests missing")
        gates = _list(item.get("gates"), "traceability gates missing")
        _require(bool(profile_paths and tests and gates), "traceability mapping incomplete")
        mapped_tests.extend(tests)
        mapped_gates.extend(gates)
    _require(mapped_gates == required_gates, "completion gates and traceability differ")
    _require(len(mapped_gates) == len(set(mapped_gates)), "completion gate has multiple owners")
    _require(sorted(mapped_tests) == EXPECTED_TEST_IDS, "completion test IDs differ")
    _require(
        traceability.get("expected_test_ids") == EXPECTED_TEST_IDS,
        "expected completion tests differ",
    )
    ownership = _list(traceability.get("artifact_ownership"), "artifact ownership missing")
    owned_requirements = {
        requirement
        for item_value in ownership
        for requirement in _list(
            _mapping(item_value, "artifact ownership invalid").get("requirement_ids"),
            "artifact requirement ownership missing",
        )
    }
    _require(owned_requirements == set(EXPECTED_REQUIREMENT_IDS), "requirement ownership differs")
    for field in (
        "unmapped_requirements",
        "unowned_gates",
        "orphan_tests",
        "orphan_artifacts",
    ):
        _require(traceability.get(field) == [], f"{field} must be empty")
    return len(ids), len(mapped_tests)


def _validate_active_status(root: Path) -> None:
    readme = (root / "README.md").read_text(encoding="utf-8")
    status = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    for text, label in ((readme, "README"), (status, "project status")):
        _require(PART1_STATE in text, f"active {label} Part 1 state differs")
        _require(PROJECT_STATE in text, f"active {label} project state differs")
        _require("UNCLAIMED" in text, f"active {label} claim boundary missing")
    _require("Stage 4" in readme and "Stage 4" in status, "active Stage 4 status missing")


def _validate_package_boundary(root: Path) -> None:
    package_files = {path.name for path in (root / "src/ledgerguard").glob("*.py")}
    _require(package_files == ALLOWED_PACKAGE_FILES, "Part 1 package boundary differs")


def _validate_profile(profile: Mapping[str, Any], stage3: Mapping[str, Any]) -> None:
    _require(profile.get("project") == PROJECT, "foundation freeze project differs")
    _require(profile.get("part") == 1 and profile.get("stage") == 4, "freeze identity differs")
    _require(profile.get("stage_state") == STAGE_STATE, "freeze Stage 4 state differs")
    _require(profile.get("part1_state") == PART1_STATE, "freeze Part 1 state differs")
    _require(profile.get("project_state") == PROJECT_STATE, "freeze project state differs")
    _require(profile.get("baseline") == EXPECTED_BASELINE, "freeze baseline differs")
    authorities = _list(profile.get("stage_authorities"), "stage authorities missing")
    _require(len(authorities) == 4, "stage authority count differs")
    for number, authority_value in enumerate(authorities):
        authority = _mapping(authority_value, "stage authority invalid")
        _require(authority.get("stage") == number, "stage authority order differs")
        _require(
            authority.get("validator_sha256") == EXPECTED_STAGE_DIGESTS[f"stage{number}_sha256"],
            f"Stage {number} validator digest differs",
        )
    for key, expected in EXPECTED_STAGE_DIGESTS.items():
        _require(stage3.get(key) == expected, f"reproduced {key} differs")
    claims = _mapping(profile.get("claim_boundary"), "freeze claim boundary missing")
    _require(claims.get("reconciliation_execution") == "UNCLAIMED", "runtime claim inflated")
    _require(claims.get("spark_parity") == "UNCLAIMED", "Spark claim inflated")
    _require(claims.get("aws_execution") is False, "freeze claims AWS execution")
    _require(claims.get("performance_and_scale") == "UNCLAIMED", "scale claim inflated")
    _require(claims.get("measured_cost") == "UNCLAIMED", "cost claim inflated")
    _require(profile.get("unresolved_completion_decisions") == [], "completion decisions remain")
    _require(profile.get("remaining_part1_work") == [], "profile Part 1 work remains")
    boundary = _mapping(profile.get("execution_boundary"), "freeze execution boundary missing")
    _require(all(value is False for value in boundary.values()), "freeze boundary claims execution")


def _validate_stage4(
    root: Path,
    stage3: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    contract_path = root / "contracts/part1-stage4-completion-v1.json"
    contract = _load(contract_path)
    profile = _load(root / "spec/part1-foundation-freeze-v1.json")
    traceability = _load(root / "spec/part1-completion-traceability-v1.json")
    _require(contract.get("project") == PROJECT, "Stage 4 project differs")
    _require(contract.get("part") == 1 and contract.get("stage") == 4, "Stage 4 identity differs")
    _require(contract.get("state") == STAGE_STATE, "Stage 4 state differs")
    _require(contract.get("part1_state") == PART1_STATE, "Stage 4 Part 1 state differs")
    _require(contract.get("project_state") == PROJECT_STATE, "Stage 4 project state differs")
    baseline = _mapping(contract.get("baseline"), "Stage 4 baseline missing")
    expected_contract_baseline = EXPECTED_BASELINE | EXPECTED_STAGE_DIGESTS
    _require(dict(baseline) == expected_contract_baseline, "Stage 4 baseline differs")
    _validate_profile(profile, stage3)
    _validate_project_contract(root, profile)
    _validate_handoff(root)
    _validate_history_manifest(root)
    artifacts = _mapping(contract.get("completion_artifacts"), "completion artifacts missing")
    artifact_digests = _artifact_digests(root, artifacts)
    required_gates = _list(contract.get("required_gates"), "Stage 4 gates missing")
    _require(required_gates == EXPECTED_REQUIRED_GATES, "Stage 4 required gates differ")
    requirement_count, test_id_count = _validate_traceability(traceability, required_gates)
    inventory = _mapping(contract.get("acceptance_inventory"), "Stage 4 inventory missing")
    expected_inventory = {
        "accepted_prior_stage_count": 4,
        "historical_completion_contract_count": 4,
        "historical_evidence_count": 4,
        "historical_snapshot_count": 4,
        "historical_v1_schema_count": 8,
        "accepted_v2_schema_count": 9,
        "project_gate_count": 6,
        "completion_requirement_count": requirement_count,
        "completion_test_id_count": test_id_count,
        "unresolved_completion_decision_count": 0,
        "unmapped_requirement_count": 0,
        "unowned_gate_count": 0,
        "orphan_test_count": 0,
        "orphan_artifact_count": 0,
    }
    _require(dict(inventory) == expected_inventory, "Stage 4 acceptance inventory differs")
    boundary = _mapping(contract.get("execution_boundary"), "Stage 4 execution boundary missing")
    _require(
        all(value is False for value in boundary.values()), "Stage 4 boundary claims execution"
    )
    external = _mapping(
        contract.get("external_completion_rule"), "external completion rule missing"
    )
    _require(
        dict(external)
        == {
            "candidate_state": "LOCAL_VERIFIED_AFTER_CI",
            "exact_head_ci": "REQUIRED",
            "manual_merge": "REQUIRED",
            "post_merge_main_ci": "REQUIRED",
        },
        "external completion rule differs",
    )
    _require(contract.get("remaining_part1_work") == [], "Stage 4 Part 1 work remains")
    _validate_active_status(root)
    _validate_package_boundary(root)

    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 4,
        "stage_state": STAGE_STATE,
        "part1_state": PART1_STATE,
        "project_state": PROJECT_STATE,
        "baseline_main_sha": EXPECTED_BASELINE["main_sha"],
        "baseline_main_tree_sha": EXPECTED_BASELINE["main_tree_sha"],
        **EXPECTED_STAGE_DIGESTS,
        "completion_contract_sha256": sha256(contract_path.read_bytes()).hexdigest(),
        "completion_artifact_digests": artifact_digests,
        "completion_requirement_count": requirement_count,
        "completion_test_id_count": test_id_count,
        "project_gate_count": 6,
        "historical_snapshot_count": 4,
        "remaining_part1_work": [],
        "aws_execution": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage4_sha256"] = sha256(canonical).hexdigest()
    return payload, artifact_digests


def validate_part1_completion(root: Path | None = None) -> dict[str, Any]:
    """Validate Part 1 completion and return deterministic candidate evidence."""

    repository = root or Path.cwd()
    stage3 = reproduce_stage3(repository)
    stage4, artifact_digests = _validate_stage4(repository, stage3)
    evidence = _load(repository / "evidence/part1-stage4-local.json")
    _require(evidence.get("project") == PROJECT, "Stage 4 evidence project differs")
    _require(evidence.get("part") == 1 and evidence.get("stage") == 4, "evidence stage differs")
    _require(evidence.get("stage_state") == STAGE_STATE, "Stage 4 evidence state differs")
    _require(evidence.get("part1_state") == PART1_STATE, "evidence Part 1 state differs")
    _require(evidence.get("project_state") == PROJECT_STATE, "evidence project state differs")
    _require(evidence.get("baseline") == EXPECTED_BASELINE, "Stage 4 evidence baseline differs")
    _require(
        evidence.get("completion_contract_sha256") == stage4["completion_contract_sha256"],
        "Stage 4 completion contract evidence differs",
    )
    _require(
        evidence.get("completion_artifact_digests") == artifact_digests,
        "Stage 4 artifact evidence differs",
    )
    preserved = _mapping(evidence.get("preserved_authorities"), "preserved evidence missing")
    expected_preserved = {
        name: {"path": path, "sha256": digest}
        for name, (path, digest) in PRESERVED_AUTHORITIES.items()
    }
    _require(dict(preserved) == expected_preserved, "preserved authority evidence differs")
    local = _mapping(evidence.get("local_validation"), "Stage 4 local validation missing")
    _require(
        isinstance(local.get("test_count"), int) and local["test_count"] > 119,
        "Stage 4 test count must exceed Stage 3",
    )
    for field in (
        "ruff_format",
        "ruff_lint",
        "strict_mypy",
        "pytest",
        "stage4_focused_pytest",
        "historical_stage3_reproduction",
        "schema_preservation",
        "authority_preservation",
        "bidirectional_traceability",
        "adversarial_mutations",
        "determinism",
        "exact_tree_archive",
        "wheel_build",
        "fresh_install",
        "diff_check",
        "secret_scan",
        "markdown_links",
    ):
        _require(local.get(field) == "PASS", f"Stage 4 local validation {field} differs")
    _require(
        local.get("stage4_validator_sha256") == stage4["stage4_sha256"],
        "Stage 4 validator digest differs",
    )
    external = _mapping(evidence.get("external_ci"), "Stage 4 external CI evidence missing")
    _require(
        dict(external)
        == {
            "exact_head_ci": "REQUIRED_EXTERNAL",
            "manual_merge": "REQUIRED_EXTERNAL",
            "post_merge_main_ci": "REQUIRED_EXTERNAL",
        },
        "Stage 4 external CI evidence differs",
    )
    claims = _mapping(evidence.get("claim_boundary"), "Stage 4 evidence claims missing")
    _require(claims.get("part1_completion_governance") == "LOCAL_VERIFIED", "claim differs")
    _require(claims.get("reconciliation_execution") == "UNCLAIMED", "runtime claim inflated")
    _require(claims.get("aws_execution") is False, "evidence claims AWS execution")
    _require(claims.get("infrastructure_mutation") is False, "evidence claims mutation")

    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 4,
        "stage_state": STAGE_STATE,
        "state": PART1_STATE,
        "project_state": PROJECT_STATE,
        "stage0_sha256": stage3["stage0_sha256"],
        "stage1_sha256": stage3["stage1_sha256"],
        "stage2_sha256": stage3["stage2_sha256"],
        "stage3_sha256": stage3["stage3_sha256"],
        "stage4_sha256": stage4["stage4_sha256"],
        "completion_contract_sha256": stage4["completion_contract_sha256"],
        "remaining_part1_work": [],
        "reconciliation_execution": "UNCLAIMED",
        "aws_execution": False,
        "infrastructure_mutation": False,
        "external_ci_required": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["part1_sha256"] = sha256(canonical).hexdigest()
    _require(
        local.get("part1_candidate_sha256") == payload["part1_sha256"],
        "Part 1 candidate digest differs",
    )
    return payload


def main() -> None:
    print(json.dumps(validate_part1_completion(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
