"""LedgerGuard Part 1 Stage 6 reproducibility-candidate authority."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard_correction_c3 import C3Error, validate_stage5
from ledgerguard_stage6_evidence import payload_digest

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE6_IDS = [f"OP-S6-R{number:03d}" for number in range(1, 36)]
GATE_IDS = [f"OP-GATE-R{number:03d}" for number in range(1, 15)]
REQUIRED_ACTIONS = [
    "exact_dependency_installation",
    "format_verification",
    "lint",
    "strict_typing",
    "json_schema_validation",
    "contract_fixture_suite",
    "semantic_invariant_suite",
    "governance_and_aws_boundary",
    "documentation_consistency",
    "coverage_threshold",
    "targeted_mutation_verification",
    "deterministic_foundation_validation",
]
EXPECTED_BASELINE = {"PASS": 9, "PARTIAL": 1, "FAIL": 18, "NOT_PROVEN": 7}
EXPECTED_BOUNDARY = {
    "aws_api_called": False,
    "aws_workflow_dispatched": False,
    "infrastructure_mutated": False,
    "merge_authorized": False,
    "part2_unlocked": False,
    "phase8_verdict_relabelled": False,
}


class C4Error(ValueError):
    """Raised when the Stage 6 candidate violates its frozen authority."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise C4Error(message)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise C4Error(f"JSON object required: {path}")
    return dict(value)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _validate_lock(path: Path, expected: set[str]) -> dict[str, str]:
    packages: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^ ]+)((?: --hash=sha256:[0-9a-f]{64})+)", line)
        _require(match is not None, f"OP-S6-R002 non-exact lock entry: {line}")
        assert match is not None
        name = match.group(1).lower().replace("_", "-")
        _require(name not in packages, f"duplicate dependency pin: {name}")
        packages[name] = match.group(2)
    _require(set(packages) == expected, f"OP-S6-R002 dependency inventory differs: {path}")
    return dict(sorted(packages.items()))


def _stage6_source_requirements(root: Path) -> list[str]:
    authority = _load(root / "spec/part1-original-requirements-v1.json")
    return [
        str(row["id"])
        for row in authority["requirements"]
        if isinstance(row, Mapping) and str(row.get("id", "")).startswith("OP-S6-")
    ]


def _phase8_baseline(root: Path) -> dict[str, int]:
    phase8 = _load(root / "evidence/part1-phase8-requirement-verdict-v1.json")
    counter = Counter(
        str(row["final_verdict"])
        for row in phase8["requirement_verdicts"]
        if isinstance(row, Mapping) and str(row.get("requirement_id", "")).startswith("OP-S6-")
    )
    return dict(counter)


def _schema_digests(root: Path) -> dict[str, str]:
    registry = _load(root / "contracts/active-contract-set-v1.json")
    result: dict[str, str] = {}
    for raw in registry["contracts"]:
        _require(isinstance(raw, Mapping), "active contract entry invalid")
        relative = str(raw["path"])
        actual = _digest(root / relative)
        _require(actual == raw["sha256"], f"accepted v2 schema bytes differ: {relative}")
        result[relative] = actual
    legacy = registry["legacy_contract_set"]["digests"]
    for filename, expected in legacy.items():
        relative = f"contracts/{filename}"
        actual = _digest(root / relative)
        _require(actual == expected, f"historical v1 schema bytes differ: {relative}")
        result[relative] = actual
    return dict(sorted(result.items()))


def _workflow_controls(root: Path) -> None:
    text = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in (
        "github.event.pull_request.head.sha",
        "git rev-parse HEAD",
        "tools/run_part1_stage6.py",
        '"$RUNNER_TEMP/ledgerguard-stage6/run-1/venv/bin/python"',
        "tools/build_part1_stage6_ci_evidence.py",
        "actions/upload-artifact@",
    ):
        _require(required in text, f"Stage 6 CI control missing: {required}")
    _require("id-token: write" not in text, "Stage 6 CI requests an OIDC token")
    _require("aws-actions/" not in text, "Stage 6 CI contains an AWS action")


def materialize_stage5_view(root: Path, view: Path) -> Path:
    """Create an exact Stage 5 view while preserving the active Stage 6 tree."""

    manifest = _load(root / "history/part1/stage5/manifest-v1.json")
    shutil.copytree(
        root,
        view,
        ignore=shutil.ignore_patterns(
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
        ),
    )
    stage6_snapshots = {
        "README.md": "eebbf5b19b5c0ef33d590263d92fc39a317b0df321f7ef3d5605fc699f776970",
        "PROJECT_STATUS.md": "b1ccedaaee3c8e9c7905c63e16ac837d30f5d66052c141061fd044359a9fcd7d",
    }
    for logical_path, expected_digest in stage6_snapshots.items():
        source = root / "history/part1/stage6/snapshots" / logical_path
        _require(_digest(source) == expected_digest, f"Stage 6 snapshot differs: {logical_path}")
        shutil.copyfile(source, view / logical_path)
    for raw in manifest["configuration_snapshots"]:
        _require(isinstance(raw, Mapping), "Stage 5 configuration snapshot invalid")
        source = root / str(raw["snapshot_path"])
        destination = view / str(raw["logical_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    c0_test = view / "tests/test_part1_correction.py"
    c0_text = c0_test.read_text(encoding="utf-8")
    c0_text = c0_text.replace(
        "from ledgerguard_correction_c4 import materialize_stage5_view\n", ""
    ).replace(
        '_STAGE5_ROOT = materialize_stage5_view(ACTIVE_ROOT, Path(_C0_TEMPORARY.name) / "stage5")\n'
        'ROOT = materialize_c0_view(_STAGE5_ROOT, Path(_C0_TEMPORARY.name) / "repository")',
        'ROOT = materialize_c0_view(ACTIVE_ROOT, Path(_C0_TEMPORARY.name) / "repository")',
    )
    c0_test.write_text(c0_text, encoding="utf-8")
    _require(
        _digest(c0_test) == "156a61591c497803283378cd2668910632c5b8e80da28aee5d5f62724b36f8d2",
        "Stage 5 C0 test replay differs",
    )
    c1_test = view / "tests/test_part1_correction_c1.py"
    c1_text = c1_test.read_text(encoding="utf-8")
    c1_text = c1_text.replace(
        "from ledgerguard_correction_c4 import materialize_stage5_view\n", ""
    ).replace(
        '_STAGE5_ROOT = materialize_stage5_view(ACTIVE_ROOT, Path(_C1_TEMPORARY.name) / "stage5")\n'
        'ROOT = materialize_c1_view(_STAGE5_ROOT, Path(_C1_TEMPORARY.name) / "repository")',
        'ROOT = materialize_c1_view(ACTIVE_ROOT, Path(_C1_TEMPORARY.name) / "repository")',
    )
    c1_test.write_text(c1_text, encoding="utf-8")
    _require(
        _digest(c1_test) == "a743de521ef08866251df4aad7c7681edb56bf99aade028778c404ab6833a16e",
        "Stage 5 C1 test replay differs",
    )
    c2_test = view / "tests/test_part1_correction_c2.py"
    c2_text = c2_test.read_text(encoding="utf-8")
    c2_text = c2_text.replace(
        "from ledgerguard_correction_c4 import materialize_stage5_view\n", ""
    ).replace(
        '_STAGE5_ROOT = materialize_stage5_view(ACTIVE_ROOT, Path(_C2_TEMPORARY.name) / "stage5")\n'
        'ROOT = materialize_c2_view(_STAGE5_ROOT, Path(_C2_TEMPORARY.name) / "repository")',
        'ROOT = materialize_c2_view(ACTIVE_ROOT, Path(_C2_TEMPORARY.name) / "repository")',
    )
    c2_test.write_text(c2_text, encoding="utf-8")
    _require(
        _digest(c2_test) == "6613d5f4f944ce2e75c0331fc2ee2ef5a2b3abe15c75577eb940e6d9d7da843d",
        "Stage 5 C2 compatibility-test replay differs",
    )
    c3_test = view / "tests/test_part1_correction_c3.py"
    c3_text = c3_test.read_text(encoding="utf-8")
    c3_text = (
        c3_text.replace("import tempfile\n", "")
        .replace("from ledgerguard_correction_c4 import materialize_stage5_view\n", "")
        .replace(
            "ACTIVE_ROOT = Path(__file__).resolve().parents[1]\n"
            '_STAGE5_TEMPORARY = tempfile.TemporaryDirectory(prefix="ledgerguard-stage5-tests-")\n'
            "ROOT = materialize_stage5_view("
            'ACTIVE_ROOT, Path(_STAGE5_TEMPORARY.name) / "repository")',
            "ROOT = Path(__file__).resolve().parents[1]",
        )
    )
    c3_test.write_text(c3_text, encoding="utf-8")
    _require(
        _digest(c3_test) == "be0d5b70ecadebe21f1f14e2d7cce2f2db85d61d590f8e78bd41bccca6b54411",
        "Stage 5 test replay differs",
    )
    stage4_test = view / "tests/test_part1_stage4.py"
    stage4_text = stage4_test.read_text(encoding="utf-8")
    stage4_text = stage4_text.replace(
        "from ledgerguard_correction_c4 import materialize_stage5_view\n", ""
    ).replace(
        "_STAGE5_ROOT = materialize_stage5_view(\n"
        '    ACTIVE_ROOT, Path(_STAGE4_TEMPORARY_DIRECTORY.name) / "stage5"\n'
        ")\n"
        "ROOT = materialize_stage4_view("
        '_STAGE5_ROOT, Path(_STAGE4_TEMPORARY_DIRECTORY.name) / "repository")',
        "ROOT = materialize_stage4_view("
        'ACTIVE_ROOT, Path(_STAGE4_TEMPORARY_DIRECTORY.name) / "repository")',
    )
    stage4_test.write_text(stage4_text, encoding="utf-8")
    _require(
        _digest(stage4_test) == "4f12ebfcd7cf280b551cca8847a74a8ba59a7b97af83aeb936e8e19160153e1a",
        "Stage 5 Stage 4 test replay differs",
    )
    coherence_test = view / "tests/test_contract_coherence.py"
    coherence_text = coherence_test.read_text(encoding="utf-8")
    coherence_text = (
        coherence_text.replace("import tempfile\n", "")
        .replace("from ledgerguard_correction_c4 import materialize_stage5_view\n", "")
        .replace(
            "ACTIVE_ROOT = Path(__file__).resolve().parents[1]\n"
            "_STAGE5_TEMPORARY = tempfile.TemporaryDirectory("
            'prefix="ledgerguard-coherence-tests-")\n'
            "ROOT = materialize_stage5_view("
            'ACTIVE_ROOT, Path(_STAGE5_TEMPORARY.name) / "repository")',
            "ROOT = Path(__file__).resolve().parents[1]",
        )
    )
    coherence_test.write_text(coherence_text, encoding="utf-8")
    _require(
        _digest(coherence_test)
        == "1c530a14cb53e3e462847dd57c13060eeb14b195a9c501ff6efd4093cf4ff6bb",
        "Stage 5 coherence-test replay differs",
    )
    stage3_test = view / "tests/test_part1_stage3.py"
    stage3_text = stage3_test.read_text(encoding="utf-8")
    stage3_text = (
        stage3_text.replace("import tempfile\n", "")
        .replace("from ledgerguard_correction_c4 import materialize_stage5_view\n", "")
        .replace(
            "ACTIVE_ROOT = Path(__file__).resolve().parents[1]\n"
            "_STAGE5_TEMPORARY = tempfile.TemporaryDirectory("
            'prefix="ledgerguard-stage3-tests-")\n'
            "ROOT = materialize_stage5_view("
            'ACTIVE_ROOT, Path(_STAGE5_TEMPORARY.name) / "repository")',
            "ROOT = Path(__file__).resolve().parents[1]",
        )
    )
    stage3_test.write_text(stage3_text, encoding="utf-8")
    _require(
        _digest(stage3_test) == "5e3ac46944c7d7627bf6c3a42cb30dfdb357a1d428e69268003a29fb434dab78",
        "Stage 5 Stage 3 test replay differs",
    )
    return view


def _reproduce_stage5(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ledgerguard-stage5-replay-") as temporary:
        view = materialize_stage5_view(root, Path(temporary) / "repository")
        try:
            return validate_stage5(view)
        except C3Error as error:
            raise C4Error(f"Stage 5 checkpoint replay failed: {error}") from error


def validate_stage6(root: Path | None = None) -> dict[str, Any]:
    """Validate the deterministic repository-resident Stage 6 candidate."""

    repository = (root or Path.cwd()).resolve()
    stage5 = _reproduce_stage5(repository)
    profile = _load(repository / "spec/part1-stage6-validation-profile-v1.json")
    contract = _load(repository / "contracts/part1-stage6-candidate-v1.json")
    _require(
        profile.get("project") == PROJECT and profile.get("stage") == 6, "profile identity differs"
    )
    _require(
        contract.get("project") == PROJECT and contract.get("stage") == 6,
        "contract identity differs",
    )
    _require(profile.get("requirement_ids") == STAGE6_IDS, "Stage 6 profile inventory differs")
    _require(
        _stage6_source_requirements(repository) == STAGE6_IDS, "source Stage 6 inventory differs"
    )
    _require(_phase8_baseline(repository) == EXPECTED_BASELINE, "Stage 6 Phase 8 baseline differs")
    _require(profile.get("phase8_baseline") == EXPECTED_BASELINE, "profile baseline differs")
    _require(
        profile.get("complete_command_actions") == REQUIRED_ACTIONS, "12-action inventory differs"
    )
    _require(profile.get("boundaries") == EXPECTED_BOUNDARY, "Stage 6 boundary differs")
    _require(contract.get("part1_state") == "PART1_CORRECTION_IN_PROGRESS", "Part 1 state inflated")
    _require(contract.get("part2_entry") == "BLOCKED", "Part 2 was unlocked")
    _require(
        contract.get("pull_request") == {"number": 8, "required_state": "DRAFT"},
        "PR boundary differs",
    )
    raw_gate_results = contract.get("gate_results")
    if not isinstance(raw_gate_results, list):
        raise C4Error("Stage 6 gate results missing")
    gate_results = raw_gate_results
    _require([row.get("gate_id") for row in gate_results] == GATE_IDS, "14-gate inventory differs")
    bootstrap = _validate_lock(
        repository / "requirements/part1-stage6-bootstrap.lock", {"pip", "setuptools", "wheel"}
    )
    dependencies = _validate_lock(
        repository / "requirements/part1-stage6-py311.lock",
        {
            "ast-serialize",
            "attrs",
            "coverage",
            "iniconfig",
            "jsonschema",
            "jsonschema-specifications",
            "librt",
            "mypy",
            "mypy-extensions",
            "packaging",
            "pathspec",
            "pluggy",
            "pygments",
            "pytest",
            "referencing",
            "rpds-py",
            "ruff",
            "typing-extensions",
        },
    )
    pyproject = (repository / "pyproject.toml").read_text(encoding="utf-8")
    _require('requires = ["setuptools==80.9.0", "wheel==0.45.1"]' in pyproject, "build pins differ")
    makefile = (repository / "Makefile").read_text(encoding="utf-8")
    _require(
        "python tools/run_part1_stage6.py --clean-runs 2" in makefile, "complete command missing"
    )
    _workflow_controls(repository)
    target = _load(repository / ".github/ledgerguard-target.json")
    completion = _load(repository / "contracts/part1-completion-authority-v2.json")
    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 6,
        "state": "STAGE6_REPRODUCIBLE_CANDIDATE",
        "part1_state": "PART1_CORRECTION_IN_PROGRESS",
        "part2_entry": "BLOCKED",
        "stage5_digest": stage5["stage5_sha256"],
        "schema_inventory": sorted(_schema_digests(repository)),
        "schema_digests": _schema_digests(repository),
        "requirement_inventory": STAGE6_IDS,
        "target": target,
        "scorecard_targets": {name: row["target"] for name, row in completion["scorecard"].items()},
        "evidence_levels": {
            name: row["current_evidence_level"] for name, row in completion["scorecard"].items()
        },
        "part1_gate_results": gate_results,
        "dependency_versions": {**bootstrap, **dependencies},
        "stage6_authority_digests": {
            relative: _digest(repository / relative)
            for relative in (
                "contracts/part1-stage6-candidate-v1.json",
                "spec/part1-stage6-ci-evidence-v1.schema.json",
                "spec/part1-stage6-validation-profile-v1.json",
            )
        },
        "execution_boundary": contract["execution_boundary"],
    }
    payload["foundation_digest"] = payload_digest(payload)
    return payload


def main() -> None:
    print(json.dumps(validate_stage6(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
