"""Fail-closed validation for LedgerGuard Part 2 Stage 1."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

PROJECT = "ledgerguard-payment-reconciliation-platform"
CLOSURE_SHA = "3ef17666e3fe3bc655ba1c8733beb3cb00acdbec"
CLOSURE_TREE = "ffe875164eebe0d818545f3580a2085c2700d94a"
CLOSURE_PARENT = "7151eead60e269fa5650e67d65fc8f687ddc281c"
VALIDATED_HEAD_SHA = "7332018c1e7ace25d3ab2cea761fb70c513ba4f2"
FOUNDATION_DIGEST = "3f315ecf51a89d95c77d1b22db4c5cd039a32c752cbd70715097987300031f59"
STAGE7_DIGEST = "604e8e3b75c4050674897f6cd357be71c6eaff999cce2da6305064d9cb77842e"
CLOSURE_EVIDENCE_DIGEST = "ed6ed12d66afaac4e300388f0a880d2ca3a624fce344c31aa6fe4ea3adcde12f"
CLOSURE_FREEZE_DIGEST = "29991475277e4b969c8c46b121c406866e209345b69a31f38b5ab6668bcc60bd"

MASTER_GATES = [
    "independent_oracle_verified",
    "spark_parity_verified",
    "financial_invariants_verified",
    "failure_matrix_verified",
    "deterministic_replay_verified",
    "critical_paths_tested",
]
STAGE_GATES = [f"P2-S1-G{number:03d}" for number in range(1, 7)]
REQUIREMENT_IDS = [f"P2-S1-R{number:03d}" for number in range(1, 27)]
RUNTIME_RESPONSIBILITIES = [
    "BUILD_INDEPENDENT_REFERENCE_ORACLE",
    "IMPLEMENT_TRANSACTION_GRAIN_RECONCILIATION",
    "IMPLEMENT_SETTLEMENT_GRAIN_RECONCILIATION",
    "ENFORCE_CHECKED_SIGNED_64_BIT_ARITHMETIC",
    "ENFORCE_CANONICAL_IDENTITY_REPLAY_AND_CONFLICT",
    "VALIDATE_REFERENCES_AND_CUMULATIVE_APPLICATION",
    "ENFORCE_EXACT_BANK_ALLOCATION_WITH_NO_DOUBLE_USE",
    "EMIT_ATOMIC_GRAIN_SPECIFIC_PROOFS",
    "PRESERVE_APPEND_ONLY_PROOF_AND_CASE_REVISIONS",
    "VERIFY_LOCAL_AND_SPARK_PARITY",
    "EXERCISE_FAILURE_MATRIX_AND_DETERMINISTIC_RECOVERY",
]
FORBIDDEN_REDEFINITIONS = [
    "COLLAPSE_TRANSACTION_AND_SETTLEMENT_GRAINS",
    "KEY_BANK_TRUTH_BY_PAYMENT",
    "USE_NON_INTEGER_OR_CROSS_CURRENCY_MONEY",
    "REPLACE_EXACT_ALLOCATION_WITH_HEURISTIC_MATCHING",
    "REWRITE_HISTORICAL_PROOFS_OR_CASE_REVISIONS",
    "CHANGE_FROZEN_IDENTITY_OR_DIGEST_SCOPES",
    "MUTATE_HISTORICAL_V1_OR_ACCEPTED_V2_SCHEMAS",
    "CLAIM_AWS_OR_MANAGED_EXECUTION",
]
INVARIANT_IDS = [f"CTR-{number:03d}" for number in range(1, 19)]
SCENARIOS = [
    "Identical record replay",
    "Identity reused with changed payload",
    "Unbalanced journal",
    "Cross-currency source combination",
    "Policy version reused with changed digest",
    "Ambiguous bank allocation",
    "Balanced journal with wrong role",
    "Missing processor event",
    "Missing ledger movement",
    "Missing bank deposit for nonzero net",
    "Zero-net settlement without bank record",
    "Split bank deposit",
    "Duplicate bank movement",
    "Disallowed bank account",
    "Unknown bank reference",
    "Out-of-order negative event",
    "Original capture arrives later",
    "Negative application exceeds capture",
    "Processor net formula mismatch",
    "Changed reconciliation policy",
    "Worker fails before finalization",
]
REASON_CODES = {
    "ADMISSION": [
        "AMBIGUOUS_BANK_ALLOCATION",
        "CURRENCY_DOMAIN_VIOLATION",
        "IDENTITY_CONFLICT",
        "POLICY_MISMATCH",
        "SCHEMA_VIOLATION",
        "SOURCE_IDENTITY_MISMATCH",
        "UNBALANCED_JOURNAL",
    ],
    "FINANCIAL": [
        "DUPLICATE_BANK_MOVEMENT",
        "INVALID_ACCOUNT_ROLE",
        "INVALID_BANK_ACCOUNT",
        "LEDGER_BANK_MISMATCH",
        "MISSING_BANK_SETTLEMENT",
        "MISSING_LEDGER_MOVEMENT",
        "MISSING_PROCESSOR_ACTIVITY",
        "OVER_APPLIED_REFERENCE",
        "PROCESSOR_BANK_MISMATCH",
        "PROCESSOR_LEDGER_MISMATCH",
        "SETTLEMENT_FORMULA_MISMATCH",
        "UNALLOCATED_BANK_MOVEMENT",
        "UNRESOLVED_REFERENCE",
    ],
    "EXECUTION": ["EXECUTION_FAILURE"],
}


class Stage1Error(ValueError):
    """Raised when the Part 2 Stage 1 contract is incomplete or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage1Error(message)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage1Error(f"JSON object required: {path}")
    return dict(value)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Stage1Error(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise Stage1Error(message)
    return value


def _validate_closure(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence_path = root / "evidence/part1-stage7-postmerge-closure-v1.json"
    freeze_path = root / "spec/part1-stage7-closure-freeze-v1.json"
    evidence = _load(evidence_path)
    freeze = _load(freeze_path)
    pull_request = _mapping(evidence.get("replacement_pull_request"), "closure PR evidence missing")
    exact_head = _mapping(pull_request.get("exact_head_ci"), "exact-head CI evidence missing")
    merge = _mapping(evidence.get("merge"), "closure merge evidence missing")
    main_ci = _mapping(evidence.get("independent_main_ci"), "main CI evidence missing")
    closure = _mapping(evidence.get("external_closure"), "external closure evidence missing")
    outcome = _mapping(evidence.get("outcome"), "closure outcome missing")

    _require(
        evidence.get("closure_state") == "PART1_OPERATIONALLY_COMPLETE", "closure state differs"
    )
    _require(
        pull_request.get("number") == 9
        and pull_request.get("base_sha") == CLOSURE_PARENT
        and pull_request.get("validated_head_sha") == VALIDATED_HEAD_SHA
        and pull_request.get("validated_head_tree_sha") == CLOSURE_TREE,
        "replacement PR identity differs",
    )
    _require(
        exact_head.get("run_id") == 33626639395
        and exact_head.get("job_id") == 100235833645
        and exact_head.get("event") == "pull_request"
        and exact_head.get("conclusion") == "success"
        and exact_head.get("artifact_id") == 9845159857
        and exact_head.get("artifact_zip_sha256")
        == "f01bcfd7f0c7e9534a3ebd281aec0ebb0efc210c4cb18e038178e3eab85c21ba"
        and exact_head.get("evidence_json_sha256")
        == "18c2f24e97e6f0cfa19bed4836b9e6ca6f423f9b1872e284c228ef723a1860e8",
        "exact-head CI evidence differs",
    )
    _require(
        merge.get("required_strategy") == "SQUASH"
        and merge.get("observed_strategy") == "SQUASH"
        and merge.get("main_sha") == CLOSURE_SHA
        and merge.get("main_tree_sha") == CLOSURE_TREE
        and merge.get("parent_shas") == [CLOSURE_PARENT]
        and merge.get("parent_count") == 1
        and merge.get("validated_tree_matches_main") is True,
        "closure merge topology differs",
    )
    _require(
        main_ci.get("run_id") == 33627452565
        and main_ci.get("job_id") == 100238462488
        and main_ci.get("event") == "push"
        and main_ci.get("head_sha") == CLOSURE_SHA
        and main_ci.get("conclusion") == "success"
        and main_ci.get("python_version") == "3.11.13"
        and main_ci.get("tests") == 242
        and all(main_ci.get(name) == 0 for name in ("failures", "errors", "skips"))
        and main_ci.get("mutation_checks") == 20
        and main_ci.get("mutation_survivors") == 0
        and main_ci.get("foundation_digest") == FOUNDATION_DIGEST
        and main_ci.get("stage7_candidate_digest") == STAGE7_DIGEST,
        "independent main CI evidence differs",
    )
    _require(
        all(
            closure.get(name) is True
            for name in (
                "exact_head_ci_passed",
                "squash_only_validated_head",
                "independent_main_ci_passed",
                "postmerge_foundation_digest_matched",
            )
        )
        and closure.get("open_corrective_pull_requests") == []
        and all(
            closure.get(name) is False
            for name in (
                "aws_workflow_ran_in_closure_window",
                "aws_api_called",
                "infrastructure_mutated",
            )
        ),
        "external closure was not complete and non-AWS",
    )
    _require(
        outcome.get("part1_state") == "PART1_FOUNDATION_COMPLETE"
        and outcome.get("part1_operational_completion") is True
        and outcome.get("part1_remaining_work") == 0
        and outcome.get("part2_entry") == "UNLOCKED"
        and outcome.get("highest_claim") == "LOCAL_VERIFIED",
        "closure outcome differs",
    )
    _require(
        freeze.get("closure_commit") == CLOSURE_SHA
        and freeze.get("closure_tree") == CLOSURE_TREE
        and freeze.get("closure_parent") == CLOSURE_PARENT,
        "closure freeze identity differs",
    )
    validation = _mapping(freeze.get("validation"), "closure validation policy missing")
    _require(
        validation.get("requires_separate_checkout") is True
        and validation.get("active_part2_tree_is_not_closure_tree") is True
        and validation.get("stage6_clean_runs") == 2
        and validation.get("output_must_be_outside_repository") is True,
        "closure validation policy differs",
    )
    protected = _mapping(freeze.get("protected_authorities"), "protected authority set missing")
    _require(len(protected) == 16, "protected authority inventory differs")
    for relative, expected in protected.items():
        path = root / str(relative)
        _require(path.is_file(), f"protected authority missing: {relative}")
        _require(_digest(path) == expected, f"protected authority digest differs: {relative}")
    _require(_digest(evidence_path) == CLOSURE_EVIDENCE_DIGEST, "closure evidence digest differs")
    _require(_digest(freeze_path) == CLOSURE_FREEZE_DIGEST, "closure freeze digest differs")
    return evidence, freeze


def _validate_authority(root: Path) -> dict[str, Any]:
    authority = _load(root / "spec/part2-stage1-authority-v1.json")
    master = _load(root / "contracts/project-completion-v1.json")
    handoff = _load(root / "contracts/part1-part2-handoff-v1.json")
    invariants = _load(root / "spec/contract-invariants-v1.json")
    failures = _load(root / "spec/part1-stage5-documentation-authority-v1.json")
    _require(
        authority.get("state") == "PART2_EXECUTION_AUTHORITY_ACTIVE", "authority state differs"
    )

    parts = _list(master.get("parts"), "master part inventory missing")
    part2 = next((row for row in parts if isinstance(row, Mapping) and row.get("part") == 2), None)
    _require(isinstance(part2, Mapping), "master Part 2 authority missing")
    assert isinstance(part2, Mapping)
    _require(part2.get("required_state") == "LOCAL_RECONCILIATION_VERIFIED", "master state differs")
    _require(part2.get("aws_workload_allowed") is False, "master Part 2 permits AWS workload")
    _require(part2.get("gates") == MASTER_GATES, "master Part 2 gate inventory differs")

    gate_rows = _list(authority.get("master_completion_gates"), "owned master gates missing")
    _require(
        [row.get("gate") for row in gate_rows if isinstance(row, Mapping)] == MASTER_GATES,
        "owned master gate order differs",
    )
    _require(
        all(
            isinstance(row, Mapping)
            and row.get("state") == "UNCLAIMED"
            and str(row.get("owner", "")).startswith("PART2_STAGE")
            for row in gate_rows
        ),
        "master completion gate was claimed or unowned",
    )

    inherited = _mapping(authority.get("inherited_authorities"), "inherited authorities missing")
    _require(inherited == handoff.get("inherited_authorities"), "inherited authority map differs")
    _require(len(inherited) == 8, "inherited authority inventory differs")
    for value in inherited.values():
        row = _mapping(value, "inherited authority row invalid")
        path = root / str(row.get("path"))
        _require(path.is_file(), f"inherited authority missing: {row.get('path')}")
        _require(_digest(path) == row.get("sha256"), f"inherited digest differs: {row.get('path')}")

    ownership = _list(
        authority.get("runtime_responsibility_ownership"), "runtime ownership missing"
    )
    owned = [str(row.get("responsibility")) for row in ownership if isinstance(row, Mapping)]
    _require(owned == RUNTIME_RESPONSIBILITIES, "runtime responsibility inventory differs")
    _require(owned == handoff.get("required_runtime_responsibilities"), "handoff ownership differs")
    _require(
        len({row.get("responsibility") for row in ownership if isinstance(row, Mapping)}) == 11
        and all(
            isinstance(row, Mapping) and str(row.get("owner", "")).startswith("PART2_STAGE")
            for row in ownership
        ),
        "runtime responsibility is duplicate or unowned",
    )
    _require(
        authority.get("forbidden_redefinitions") == FORBIDDEN_REDEFINITIONS
        and handoff.get("forbidden_redefinitions") == FORBIDDEN_REDEFINITIONS,
        "forbidden redefinition inventory differs",
    )
    invariant_rows = _list(invariants.get("invariants"), "runtime invariants missing")
    actual_invariants = [str(row.get("id")) for row in invariant_rows if isinstance(row, Mapping)]
    _require(actual_invariants == INVARIANT_IDS, "source runtime invariants differ")
    _require(authority.get("runtime_invariant_ids") == INVARIANT_IDS, "owned invariants differ")
    _require(
        authority.get("reason_domains") == failures.get("reason_domains"), "reason domains differ"
    )
    _require(authority.get("reason_domains") == REASON_CODES, "closed reason inventory differs")
    scenarios = [
        str(row.get("scenario"))
        for row in _list(failures.get("failure_scenarios"), "failure scenarios missing")
        if isinstance(row, Mapping)
    ]
    _require(scenarios == SCENARIOS, "source behavioral scenarios differ")
    _require(authority.get("required_behavioral_scenarios") == SCENARIOS, "owned scenarios differ")
    claim = _mapping(authority.get("claim_boundary"), "authority claim boundary missing")
    _require(
        claim.get("reference_oracle") == "UNCLAIMED"
        and claim.get("reconciliation_engine") == "UNCLAIMED"
        and claim.get("spark_reconciliation") == "UNCLAIMED"
        and claim.get("aws_execution") is False
        and claim.get("infrastructure_mutation") is False,
        "authority claim boundary is inflated",
    )
    return authority


def _validate_contract_and_traceability(root: Path) -> None:
    contract = _load(root / "contracts/part2-stage1-execution-contract-v1.json")
    gates = _load(root / "spec/part2-stage1-gate-registry-v1.json")
    requirements = _load(root / "spec/part2-stage1-requirements-v1.json")
    traceability = _load(root / "spec/part2-stage1-traceability-v1.json")
    _require(
        contract.get("part") == 2
        and contract.get("stage") == 1
        and contract.get("state") == "PART2_IN_PROGRESS"
        and contract.get("stage_state") == "PART2_STAGE1_EXECUTION_CONTRACT_ESTABLISHED",
        "Stage 1 contract state differs",
    )
    _require(contract.get("stage_gates") == STAGE_GATES, "contract stage gates differ")
    master = _mapping(contract.get("master_part2_completion_gates"), "master gate states missing")
    _require(set(master) == set(MASTER_GATES), "contract master gates differ")
    _require(all(value == "UNCLAIMED" for value in master.values()), "master gate claimed early")
    boundary = _mapping(contract.get("implementation_boundary"), "implementation boundary missing")
    _require(all(value is False for value in boundary.values()), "implementation claim is inflated")
    external = _mapping(contract.get("external_completion"), "external completion policy missing")
    _require(
        bool(external) and all(value is True for value in external.values()),
        "external policy weakened",
    )

    gate_rows = _list(gates.get("gates"), "Stage 1 gate registry missing")
    _require(
        [row.get("gate_id") for row in gate_rows if isinstance(row, Mapping)] == STAGE_GATES,
        "Stage 1 gate registry differs",
    )
    _require(
        all(
            isinstance(row, Mapping) and str(row.get("acceptance", "")).strip() for row in gate_rows
        ),
        "Stage 1 gate acceptance missing",
    )
    requirement_rows = _list(requirements.get("requirements"), "Stage 1 requirements missing")
    ids = [str(row.get("id")) for row in requirement_rows if isinstance(row, Mapping)]
    _require(ids == REQUIREMENT_IDS, "Stage 1 requirement inventory differs")
    _require(
        all(
            isinstance(row, Mapping)
            and row.get("gate_id") in STAGE_GATES
            and str(row.get("statement", "")).strip()
            for row in requirement_rows
        ),
        "Stage 1 requirement is incomplete",
    )
    trace_rows = _list(traceability.get("traceability"), "Stage 1 traceability missing")
    trace_ids = [str(row.get("requirement_id")) for row in trace_rows if isinstance(row, Mapping)]
    _require(trace_ids == REQUIREMENT_IDS, "Stage 1 traceability inventory differs")
    _require(
        [row.get("validation") for row in trace_rows if isinstance(row, Mapping)]
        == [f"P2S1-T{number:03d}" for number in range(1, 27)],
        "Stage 1 validation trace differs",
    )
    for row in trace_rows:
        mapped = _mapping(row, "traceability row invalid")
        authorities = _list(mapped.get("authorities"), "traceability authority missing")
        evidence = _list(mapped.get("evidence"), "traceability evidence missing")
        _require(bool(authorities) and bool(evidence), "traceability row is empty")
        for relative in authorities:
            _require((root / str(relative)).is_file(), f"traceability path missing: {relative}")


def _validate_lock(path: Path) -> list[str]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    _require(bool(lines), f"empty dependency lock: {path.name}")
    _require(
        all("==" in line and "--hash=sha256:" in line for line in lines),
        f"unhashed dependency in {path.name}",
    )
    return lines


def _validate_toolchain(root: Path) -> dict[str, Any]:
    profile = _load(root / "spec/part2-stage1-toolchain-v1.json")
    target = _load(root / ".github/ledgerguard-target.json")
    target_runtime = _mapping(target.get("managed_runtime"), "frozen target runtime missing")
    managed = _mapping(profile.get("managed_target"), "managed target profile missing")
    local = _mapping(profile.get("local_validation"), "local validation profile missing")
    dependencies = _mapping(profile.get("dependency_surface"), "dependency surface missing")
    _require(
        managed
        == {
            "aws_glue": "5.1",
            "apache_spark": "3.5.6",
            "python": "3.11",
            "java_major": 17,
        },
        "managed runtime target differs",
    )
    _require(
        target_runtime.get("glue_version") == managed.get("aws_glue")
        and target_runtime.get("spark_version") == managed.get("apache_spark")
        and target_runtime.get("python_version") == managed.get("python"),
        "frozen target and toolchain differ",
    )
    _require(
        local.get("python") == "3.11.13"
        and local.get("apache_spark") == "3.5.6"
        and local.get("py4j") == "0.10.9.7"
        and local.get("java_major") == 17
        and local.get("spark_master") == "local[1]"
        and local.get("spark_sql_ansi_enabled") is True
        and local.get("spark_sql_session_timezone") == "UTC"
        and local.get("storage_format") == "parquet"
        and local.get("clean_run_count") == 2
        and local.get("driver_worker_python_must_match") is True
        and local.get("output_must_be_outside_repository") is True,
        "local toolchain profile differs",
    )
    _require(
        dependencies.get("require_hashes") is True
        and dependencies.get("pandas_required") is False
        and dependencies.get("pyarrow_required") is False,
        "dependency surface expanded or weakened",
    )
    bootstrap = _validate_lock(root / "requirements/part2-stage1-bootstrap.lock")
    runtime = _validate_lock(root / "requirements/part2-stage1-py311.lock")
    _require(len(bootstrap) == 3, "bootstrap lock inventory differs")
    _require(any(line.startswith("pyspark==3.5.6 ") for line in runtime), "Spark pin missing")
    _require(any(line.startswith("py4j==0.10.9.7 ") for line in runtime), "Py4J pin missing")
    _require(
        not any(line.startswith(("pandas==", "pyarrow==")) for line in runtime),
        "unused data dependency added",
    )
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    _require('spark = [\n  "pyspark==3.5.6",\n]' in pyproject, "Spark project extra differs")
    _require(
        'ledgerguard-part2-stage1 = "ledgerguard_part2_stage1:main"' in pyproject,
        "Stage 1 command is missing",
    )
    return profile


def _validate_surfaces(root: Path) -> None:
    status = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    for required in (
        "Part: 2 — Executable reconciliation system",
        "Stage: 1 — Execution contract and local toolchain",
        "State: `PART2_IN_PROGRESS`",
        "Stage state: `PART2_STAGE1_EXECUTION_CONTRACT_ESTABLISHED`",
        "Reference oracle: `UNCLAIMED`",
        "Reconciliation implementation: `UNCLAIMED`",
        "Spark reconciliation parity: `UNCLAIMED`",
        "AWS execution: false",
        "AWS infrastructure mutated: false",
        "Promotion recovery outcome: `PART1_OPERATIONALLY_COMPLETE`",
    ):
        _require(required in status, f"active status line missing: {required}")
    _require("LOCAL_RECONCILIATION_VERIFIED" not in status, "Part 2 completion claimed early")
    readme = (root / "README.md").read_text(encoding="utf-8")
    _require("Part 2\nis now `PART2_IN_PROGRESS`" in readme, "README Part 2 state differs")
    _require(
        "No reconciliation\noracle or engine is claimed by Stage 1" in readme,
        "README claim boundary differs",
    )

    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    folded_workflow = workflow.casefold()
    for forbidden in (
        "aws-actions/",
        "id-token: write",
        "aws sts",
        "aws s3",
        "aws glue",
        "configure-aws-credentials",
    ):
        _require(
            forbidden.casefold() not in folded_workflow,
            f"automatic CI includes AWS capability: {forbidden}",
        )
    for required in (
        "github.event.pull_request.head.sha || github.sha",
        "actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38",
        'python-version: "3.11.13"',
        "actions/setup-java@dd06d9cba3e5552c54d9f8ea23572deb30010f7c",
        'java-version: "17"',
        CLOSURE_SHA,
        "git worktree add --detach",
        "$RUNNER_TEMP/ledgerguard-part1-closure",
        "--clean-runs 2",
    ):
        _require(required in workflow, f"automatic CI control missing: {required}")
    _require(
        "python tools/run_part2_stage1.py" in workflow
        or 'python "$RUNNER_TEMP/ledgerguard-part2-stage1-closure/tools/run_part2_stage1.py"'
        in workflow,
        "automatic CI Stage 1 execution control missing",
    )
    _require(
        "contents: read" in workflow and "pull-requests: read" in workflow, "CI permissions differ"
    )

    identity = (root / ".github/workflows/aws-oidc-identity.yml").read_text(encoding="utf-8")
    trigger = identity.split("on:\n", 1)[1].split("\npermissions:", 1)[0].strip()
    _require(trigger == "workflow_dispatch:", "AWS identity workflow is not manual-only")
    runner = (root / "tools/run_part2_stage1.py").read_text(encoding="utf-8")
    probe = (root / "tools/validate_part2_stage1_run.py").read_text(encoding="utf-8")
    _require(
        "PYSPARK_PYTHON" in runner and "PYSPARK_DRIVER_PYTHON" in runner,
        "Spark Python binding missing",
    )
    _require("arguments.clean_runs < 2" in runner, "two-run minimum missing")
    _require("repository in workspace.parents" in runner, "external output boundary missing")
    _require(
        "import pandas" not in probe and "import pyarrow" not in probe,
        "unused data dependency imported",
    )


def validate_stage1(root: Path | None = None) -> dict[str, Any]:
    """Validate the complete repository-resident Part 2 Stage 1 candidate."""

    repository = (root or Path.cwd()).resolve()
    closure, freeze = _validate_closure(repository)
    authority = _validate_authority(repository)
    _validate_contract_and_traceability(repository)
    toolchain = _validate_toolchain(repository)
    _validate_surfaces(repository)
    authority_paths = [
        "contracts/part2-stage1-execution-contract-v1.json",
        "evidence/part1-stage7-postmerge-closure-v1.json",
        "spec/part1-stage7-closure-freeze-v1.json",
        "spec/part2-stage1-authority-v1.json",
        "spec/part2-stage1-gate-registry-v1.json",
        "spec/part2-stage1-requirements-v1.json",
        "spec/part2-stage1-toolchain-v1.json",
        "spec/part2-stage1-traceability-v1.json",
        "docs/part2-execution-contract.md",
        "docs/part2-stage1-gap-audit.md",
        "docs/adr/0017-part2-execution-authority-and-local-toolchain.md",
    ]
    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 2,
        "stage": 1,
        "state": "PART2_IN_PROGRESS",
        "stage_state": "PART2_STAGE1_EXECUTION_CONTRACT_ESTABLISHED",
        "part1_closure": {
            "commit": freeze["closure_commit"],
            "tree": freeze["closure_tree"],
            "foundation_digest": closure["independent_main_ci"]["foundation_digest"],
            "stage7_candidate_digest": closure["independent_main_ci"]["stage7_candidate_digest"],
        },
        "inventories": {
            "master_completion_gates": len(authority["master_completion_gates"]),
            "inherited_authorities": len(authority["inherited_authorities"]),
            "runtime_responsibilities": len(authority["runtime_responsibility_ownership"]),
            "forbidden_redefinitions": len(authority["forbidden_redefinitions"]),
            "runtime_invariants": len(authority["runtime_invariant_ids"]),
            "behavioral_scenarios": len(authority["required_behavioral_scenarios"]),
            "closed_reason_codes": sum(
                len(value) for value in authority["reason_domains"].values()
            ),
            "stage1_requirements": len(REQUIREMENT_IDS),
            "stage1_gates": len(STAGE_GATES),
        },
        "toolchain": {
            "python": toolchain["local_validation"]["python"],
            "java_major": toolchain["local_validation"]["java_major"],
            "spark": toolchain["local_validation"]["apache_spark"],
            "py4j": toolchain["local_validation"]["py4j"],
            "parquet": True,
        },
        "master_part2_gates": {gate: "UNCLAIMED" for gate in MASTER_GATES},
        "authority_digests": {path: _digest(repository / path) for path in authority_paths},
        "aws_execution": False,
        "infrastructure_mutation": False,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage1_candidate_digest"] = sha256(encoded).hexdigest()
    return payload


def main() -> None:
    print(json.dumps(validate_stage1(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
