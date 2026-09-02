"""Fail-closed Stage 5 documentation-system validation for LedgerGuard Part 1."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any, cast

from ledgerguard.foundation import FoundationError

PROJECT = "ledgerguard-payment-reconciliation-platform"
PART1_STATE = "PART1_CORRECTION_IN_PROGRESS"
PROJECT_STATE = "PROJECT_IN_PROGRESS"
PART2_STATE = "BLOCKED"
STAGE5_STATE = "STAGE5_DOCUMENTATION_SYSTEM_VALIDATED"
C2_MANIFEST_PATH = "history/part1/c2/manifest-v1.json"
C2_MANIFEST_SHA256 = "6f5d1f0a15a035e6e527de778d7fad12b1f3229dae2765bdc487955f67d5f34c"
C2_FILE_COUNT = 148
C2_MUTABLE_PATHS = {
    "PROJECT_STATUS.md",
    "README.md",
    "docs/architecture.md",
    "docs/failure-model.md",
    "pyproject.toml",
    "tests/test_part1_correction_c2.py",
}
ALL_STAGE5_IDS = [f"OP-S5-R{number:03d}" for number in range(1, 24)]
DIRECT_STAGE5_IDS = [
    "OP-S5-R001",
    "OP-S5-R002",
    "OP-S5-R009",
    "OP-S5-R014",
    "OP-S5-R015",
    "OP-S5-R016",
    "OP-S5-R017",
    "OP-S5-R019",
    "OP-S5-R020",
    "OP-S5-R021",
]
C1_STAGE5_IDS = ["OP-S5-R010", "OP-S5-R023"]
PRESERVED_STAGE5_IDS = sorted(set(ALL_STAGE5_IDS) - set(DIRECT_STAGE5_IDS) - set(C1_STAGE5_IDS))
DOCUMENT_CATEGORIES = [
    "README",
    "PROJECT_STATUS",
    "EXACT_GAP_AUDIT",
    "REQUIREMENTS_LEDGER",
    "ARCHITECTURE",
    "CORRECTNESS_MODEL",
    "FAILURE_MODEL",
    "SCORECARD",
    "ADRS",
    "CONTRACT_REFERENCE",
    "EVIDENCE_AND_CLAIM_BOUNDARY",
]
EXPECTED_EXECUTION_BOUNDARY = {
    "aws_api_called": False,
    "aws_workflow_dispatched": False,
    "infrastructure_mutated": False,
    "reconciliation_runtime_added": False,
    "phase8_verdict_relabelled": False,
    "part1_completion_claimed": False,
    "part2_unlocked": False,
    "merge_authorized": False,
}
EXPECTED_PROMOTION_BOUNDARY = {
    "pull_request_number": 8,
    "pull_request_state": "DRAFT_REQUIRED",
    "exact_head_ci": "REQUIRED",
    "merge_in_stage5": "PROHIBITED",
    "post_merge_main_ci": "DEFERRED_TO_C6_C7",
}


class C3Error(FoundationError):
    """Raised when Stage 5 documentation consistency fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise C3Error(message)


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise C3Error(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise C3Error(message)
    return value


def _load(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key is forbidden: {key}")
            result[key] = value
        return result

    try:
        value: object = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise C3Error(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise C3Error(f"JSON object required: {path}")
    return value


def _safe_file(root: Path, relative: str, label: str) -> Path:
    value = Path(relative)
    _require(
        bool(relative) and not value.is_absolute() and ".." not in value.parts,
        f"{label} path escapes repository",
    )
    path = root / value
    _require(path.is_file() and not path.is_symlink(), f"{label} missing: {relative}")
    _require(path.resolve().is_relative_to(root.resolve()), f"{label} escapes repository")
    return path


def _digest(root: Path, relative: str) -> str:
    return sha256(_safe_file(root, relative, "digest-bound artifact").read_bytes()).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    return sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _validate_c2_manifest(root: Path) -> list[Mapping[str, Any]]:
    path = _safe_file(root, C2_MANIFEST_PATH, "C2 history manifest")
    _require(
        sha256(path.read_bytes()).hexdigest() == C2_MANIFEST_SHA256, "C2 manifest digest differs"
    )
    manifest = _load(path)
    _require(manifest.get("project") == PROJECT, "C2 manifest project differs")
    _require(manifest.get("workstream") == "C2", "C2 manifest workstream differs")
    _require(manifest.get("state") == "C2_EXACT_HEAD_TREE_PRESERVED", "C2 history state differs")
    source = _mapping(manifest.get("source"), "C2 source missing")
    expected_source = {
        "base_main_sha": "2842550d24559a636ff5f15cbd6ea4be1c2ab1c1",
        "branch": "part1-c0-truthful-correction",
        "pr_number": 8,
        "pr_state": "DRAFT",
        "exact_head_sha": "56dd058fc8fd9e8fe336ce682976cd1ecbf1dc5a",
        "tree_sha": "4be81b26c3364d21a7e509751f3d4f2186b1ea42",
        "exact_head_ci_run_id": 33596879824,
        "exact_head_ci_conclusion": "success",
        "c2_sha256": "977f3af4ebaa4759b4ece41160299fd17a751333392e73c8df355b7ff24b33f0",
        "c2_contract_sha256": "b6a39db21dae7c4a98338cfc6fb9dcb3f897ef582906d57da5f50900fa7d50bf",
    }
    _require(dict(source) == expected_source, "C2 manifest source differs")
    files = [
        _mapping(item, "C2 file entry invalid")
        for item in _list(manifest.get("files"), "C2 files missing")
    ]
    _require(
        len(files) == manifest.get("accepted_file_count") == C2_FILE_COUNT, "C2 file count differs"
    )
    logical = [item.get("logical_path") for item in files]
    _require(len(logical) == len(set(logical)), "duplicate C2 logical path")
    snapshots = {
        str(item["logical_path"]) for item in files if isinstance(item.get("snapshot_path"), str)
    }
    _require(snapshots == C2_MUTABLE_PATHS, "C2 snapshot inventory differs")
    _require(
        manifest.get("mutable_snapshot_count") == len(C2_MUTABLE_PATHS), "C2 snapshot count differs"
    )
    return files


def materialize_c2_view(root: Path, destination: Path) -> Path:
    """Materialize the exact 148-file green C2 tree."""

    files = _validate_c2_manifest(root)
    _require(not destination.exists(), "C2 destination already exists")
    destination.mkdir(parents=True)
    for item in files:
        logical = item.get("logical_path")
        if not isinstance(logical, str):
            raise C3Error("C2 logical path invalid")
        snapshot = item.get("snapshot_path")
        source_relative = snapshot if isinstance(snapshot, str) else logical
        data = _safe_file(root, source_relative, "C2 artifact").read_bytes()
        _require(sha256(data).hexdigest() == item.get("sha256"), f"C2 digest drift: {logical}")
        _require(_git_blob_sha(data) == item.get("git_blob_sha"), f"C2 blob drift: {logical}")
        target = destination / logical
        _require(target.resolve().is_relative_to(destination.resolve()), "C2 target escapes")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    actual = sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )
    expected = sorted(str(item["logical_path"]) for item in files)
    _require(actual == expected, "materialized C2 inventory differs")
    return destination


def reproduce_c2(root: Path) -> dict[str, Any]:
    """Run the preserved C2 validator in the exact green C2 tree."""

    with tempfile.TemporaryDirectory(prefix="ledgerguard-c2-view-") as temporary:
        view = materialize_c2_view(root, Path(temporary) / "repository")
        environment = os.environ.copy()
        entries = [str(view / "src")]
        if environment.get("PYTHONPATH"):
            entries.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(entries)
        completed = subprocess.run(
            [sys.executable, "-m", "ledgerguard_correction_c2"],
            cwd=view,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        _require(
            completed.returncode == 0, f"preserved C2 validation failed: {completed.stderr.strip()}"
        )
        try:
            parsed: object = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise C3Error("preserved C2 output is not JSON") from error
    _require(isinstance(parsed, dict), "preserved C2 result must be an object")
    result = cast(dict[str, Any], parsed)
    _require(
        result.get("c2_sha256")
        == "977f3af4ebaa4759b4ece41160299fd17a751333392e73c8df355b7ff24b33f0",
        "C2 digest differs",
    )
    _require(
        result.get("state") == PART1_STATE and result.get("part2_entry") == PART2_STATE,
        "C2 active state differs",
    )
    return result


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[`*_~]", "", lowered)
    lowered = re.sub(r"[^a-z0-9 -]", "", lowered)
    return re.sub(r"[ -]+", "-", lowered).strip("-")


def _active_markdown(root: Path) -> list[Path]:
    return sorted([*root.glob("*.md"), *(root / "docs").rglob("*.md")])


def _validate_links(root: Path) -> int:
    checked = 0
    pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    for document in _active_markdown(root):
        text = document.read_text(encoding="utf-8")
        for raw in pattern.findall(text):
            target = raw.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            path_text, _, fragment = target.partition("#")
            target_path = document if not path_text else (document.parent / path_text)
            _require(
                target_path.resolve().is_relative_to(root.resolve()),
                f"Markdown link escapes repository: {document.relative_to(root)} -> {target}",
            )
            _require(
                target_path.is_file() and not target_path.is_symlink(),
                f"Markdown link target missing: {document.relative_to(root)} -> {target}",
            )
            if fragment and target_path.suffix.lower() == ".md":
                headings = {
                    _slug(line.lstrip("# "))
                    for line in target_path.read_text(encoding="utf-8").splitlines()
                    if line.startswith("#")
                }
                _require(
                    fragment.lower() in headings,
                    f"Markdown link fragment missing: {document.relative_to(root)} -> {target}",
                )
            checked += 1
    _require(checked > 0, "no internal Markdown links checked")
    return checked


def _validate_contracts(root: Path, authority: Mapping[str, Any]) -> int:
    registry = _load(root / "contracts/active-contract-set-v1.json")
    registered = [
        _mapping(item, "active registry item invalid")
        for item in _list(registry.get("contracts"), "active contracts missing")
    ]
    owned = [
        _mapping(item, "Stage 5 contract item invalid")
        for item in _list(authority.get("active_contracts"), "Stage 5 contracts missing")
    ]
    _require(len(owned) == len(registered) == 9, "active contract count differs")
    by_family = {str(item.get("family")): item for item in owned}
    _require(
        set(by_family) == {str(item.get("family")) for item in registered},
        "active contract families differ",
    )
    for item in registered:
        family = str(item["family"])
        candidate = by_family[family]
        path = str(item["path"])
        schema = _load(_safe_file(root, path, "active schema"))
        _require(candidate.get("path") == path, f"active contract path differs: {family}")
        _require(
            candidate.get("filename") == Path(path).name,
            f"active contract filename differs: {family}",
        )
        _require(
            candidate.get("id") == item.get("id") == schema.get("$id"),
            f"active contract ID differs: {family}",
        )
        _require(candidate.get("version") == "2.0", f"active contract version differs: {family}")
        _require(
            _digest(root, path) == item.get("sha256"), f"active contract digest differs: {family}"
        )
    architecture = (root / "docs/architecture-v2.md").read_text(encoding="utf-8")
    diagram_names = set(re.findall(r"[a-z0-9-]+-v2\.schema\.json", architecture))
    _require(
        diagram_names == {str(item["filename"]) for item in owned},
        "OP-S5-R002 architecture contract names differ",
    )
    known_schema_names = {
        path.name
        for base in (root / "contracts", root / "spec")
        for path in base.rglob("*.schema.json")
    }
    for document in _active_markdown(root):
        for name in re.findall(
            r"[a-z0-9-]+-v[0-9]+\.schema\.json", document.read_text(encoding="utf-8")
        ):
            _require(
                name in known_schema_names, f"OP-S5-R014 documented contract does not exist: {name}"
            )
    return len(owned)


def _validate_reasons(root: Path, authority: Mapping[str, Any]) -> int:
    semantics = _load(root / "spec/financial-semantics-v1.json")
    semantic_domains = _mapping(
        semantics.get("failure_ownership"), "financial reason authority missing"
    )
    expected = {
        "ADMISSION": sorted(cast(list[str], semantic_domains["ADMISSION"])),
        "FINANCIAL": sorted(cast(list[str], semantic_domains["FINANCIAL_EXCEPTION"])),
        "EXECUTION": sorted(cast(list[str], semantic_domains["EXECUTION"])),
    }
    actual_domains = _mapping(authority.get("reason_domains"), "Stage 5 reason domains missing")
    _require(
        {key: sorted(cast(list[str], value)) for key, value in actual_domains.items()} == expected,
        "OP-S5-R015 reason domains differ from semantics",
    )
    allowed = {value for values in expected.values() for value in values}
    scenarios = [
        _mapping(item, "failure scenario invalid")
        for item in _list(authority.get("failure_scenarios"), "failure scenarios missing")
    ]
    _require(len(scenarios) == 21, "failure scenario count differs")
    names = [item.get("scenario") for item in scenarios]
    _require(len(names) == len(set(names)), "duplicate failure scenario")
    failure_text = (root / "docs/failure-model-v2.md").read_text(encoding="utf-8")
    for item in scenarios:
        name = str(item.get("scenario"))
        ownership = str(item.get("ownership"))
        codes = [
            str(value) for value in _list(item.get("reason_codes"), f"reason codes invalid: {name}")
        ]
        _require(ownership in expected, f"scenario ownership invalid: {name}")
        _require(set(codes).issubset(allowed), f"OP-S5-R015 unknown reason code: {name}")
        row = next(
            (line for line in failure_text.splitlines() if line.startswith(f"| {name} |")), ""
        )
        _require(bool(row), f"OP-S5-R009 failure scenario undocumented: {name}")
        _require(str(item.get("outcome")) in row, f"OP-S5-R009 failure outcome differs: {name}")
        for code in codes:
            _require(f"`{code}`" in row, f"OP-S5-R009 reason mapping differs: {name}")
        if not codes:
            _require("| — |" in row, f"OP-S5-R009 no-reason outcome not explicit: {name}")
    return len(scenarios)


def _validate_aws_target(root: Path, authority: Mapping[str, Any]) -> None:
    target = _load(root / ".github/ledgerguard-target.json")
    runtime = _mapping(target.get("managed_runtime"), "managed runtime missing")
    expected = {
        "repository": target.get("repository"),
        "default_branch": target.get("default_branch"),
        "account_id": target.get("account_id"),
        "region": target.get("region"),
        "oidc_role_name": target.get("oidc_role_name"),
        "glue_version": runtime.get("glue_version"),
        "spark_version": runtime.get("spark_version"),
        "python_version": runtime.get("python_version"),
    }
    _require(
        authority.get("aws_target_fields") == list(expected), "AWS target field authority differs"
    )
    architecture = (root / "docs/architecture-v2.md").read_text(encoding="utf-8")
    for value in expected.values():
        _require(
            f"`{value}`" in architecture, f"OP-S5-R016 AWS target documentation differs: {value}"
        )
    all_text = "\n".join(path.read_text(encoding="utf-8") for path in _active_markdown(root))
    for account in re.findall(r"(?<![0-9])[0-9]{12}(?![0-9])", all_text):
        _require(
            account == expected["account_id"],
            f"OP-S5-R016 documented AWS account differs: {account}",
        )
    for region in re.findall(r"\b[a-z]{2}-[a-z]+-[0-9]\b", all_text):
        _require(
            region == expected["region"], f"OP-S5-R016 documented AWS region differs: {region}"
        )


def _validate_scorecard(root: Path, authority: Mapping[str, Any]) -> None:
    completion = _load(root / str(authority.get("completion_authority_path")))
    expected = _mapping(completion.get("scorecard"), "completion scorecard missing")
    text = _safe_file(root, str(authority.get("scorecard_path")), "scorecard document").read_text(
        encoding="utf-8"
    )
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---") or " Dimension " in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 6:
            key = re.sub(r"\s+", "_", cells[0].lower())
            rows[key] = cells
    _require(set(rows) == set(expected), "OP-S5-R017 scorecard dimensions differ")
    for dimension, raw in expected.items():
        item = _mapping(raw, f"completion scorecard invalid: {dimension}")
        cells = rows[dimension]
        _require(
            float(cells[1]) == item.get("target"),
            f"OP-S5-R017 scorecard target differs: {dimension}",
        )
        _require(
            cells[2].strip("`") == item.get("current_evidence_level"),
            f"OP-S5-R017 evidence level differs: {dimension}",
        )
        _require(
            (cells[3] == "Yes") is item.get("part1_contributes"),
            f"OP-S5-R017 Part 1 contribution differs: {dimension}",
        )


def _validate_claims_and_status(root: Path, authority: Mapping[str, Any]) -> None:
    policy = _mapping(authority.get("claim_policy"), "claim policy missing")
    text_by_path = {path: path.read_text(encoding="utf-8") for path in _active_markdown(root)}
    combined = "\n".join(text_by_path.values()).lower()
    for phrase in _list(
        policy.get("forbidden_managed_claim_phrases"), "managed claim phrases missing"
    ):
        _require(
            str(phrase).lower() not in combined,
            f"OP-S5-R020 managed-execution claim present: {phrase}",
        )
    for phrase in _list(
        policy.get("forbidden_implementation_claim_phrases"), "implementation claim phrases missing"
    ):
        _require(
            str(phrase).lower() not in combined,
            f"OP-S5-R021 implementation claim present: {phrase}",
        )
    managed_assertion = re.compile(
        r"\b(?:aws|managed)\b[^.\n]{0,80}\b"
        r"(?:is deployed|was executed|is operational|has been deployed)\b",
        re.IGNORECASE,
    )
    implementation_assertion = re.compile(
        r"\breconciliation (?:engine|runtime|job|implementation) "
        r"(?:is|was|has been) (?:implemented|complete|operational)\b",
        re.IGNORECASE,
    )
    _require(
        not managed_assertion.search(combined), "OP-S5-R020 managed-execution prose claim present"
    )
    _require(
        not implementation_assertion.search(combined),
        "OP-S5-R021 implementation prose claim present",
    )
    _require(
        "AWS_VERIFIED_WRONG_TARGET" in text_by_path[root / "README.md"],
        "historical AWS boundary missing",
    )
    for relative in ("README.md", "PROJECT_STATUS.md"):
        text = text_by_path[root / relative]
        _require(
            PART1_STATE in text and PROJECT_STATE in text and PART2_STATE in text,
            f"OP-S5-R018 active status differs: {relative}",
        )
    _require(
        authority.get("execution_boundary")
        == {
            key: value
            for key, value in EXPECTED_EXECUTION_BOUNDARY.items()
            if key != "phase8_verdict_relabelled"
        },
        "Stage 5 authority execution boundary differs",
    )


def _validate_traceability_and_verdict(root: Path) -> None:
    originals = _load(root / "spec/part1-original-requirements-v1.json")
    original_rows = [
        _mapping(item, "original requirement invalid")
        for item in _list(originals.get("requirements"), "original requirements missing")
    ]
    original_ids = [str(item.get("id")) for item in original_rows]
    _require(
        len(original_ids) == len(set(original_ids)) == 331, "original requirement inventory differs"
    )
    ledger = _load(root / "spec/part1-requirement-ledger-v1.json")
    ledger_rows = [
        _mapping(item, "requirement ledger row invalid")
        for item in _list(ledger.get("requirements"), "requirement ledger missing")
    ]
    by_id = {str(item.get("requirement_id")): item for item in ledger_rows}
    _require(set(by_id) == set(original_ids), "requirement ledger coverage differs")
    for requirement_id in original_ids:
        row = by_id[requirement_id]
        _require(
            bool(_list(row.get("rule_refs"), f"rule trace missing: {requirement_id}")),
            f"rule trace empty: {requirement_id}",
        )
        _require(
            bool(
                _list(row.get("contract_schema_paths"), f"schema trace missing: {requirement_id}")
            ),
            f"schema trace empty: {requirement_id}",
        )
        _require(
            bool(_list(row.get("test_paths"), f"test trace missing: {requirement_id}")),
            f"OP-S5-R010 test trace empty: {requirement_id}",
        )
        _require(
            bool(
                _list(
                    row.get("authority_evidence_paths"), f"evidence trace missing: {requirement_id}"
                )
            ),
            f"OP-S5-R023 evidence trace empty: {requirement_id}",
        )
    phase8 = _load(root / "evidence/part1-phase8-requirement-verdict-v1.json")
    baseline = {
        str(item["requirement_id"]): item["final_verdict"]
        for item in _list(phase8.get("requirement_verdicts"), "Phase 8 verdicts missing")
        if isinstance(item, Mapping)
    }
    verdict = _load(root / "evidence/part1-stage5-candidate-verdict-v1.json")
    _require(
        verdict.get("phase8_baseline_immutable") is True
        and verdict.get("final_c7_audit_required") is True,
        "Stage 5 verdict bypasses history or C7",
    )
    results = [
        _mapping(item, "Stage 5 result invalid")
        for item in _list(verdict.get("requirement_results"), "Stage 5 results missing")
    ]
    _require(
        [item.get("requirement_id") for item in results] == ALL_STAGE5_IDS,
        "Stage 5 requirement order differs",
    )
    for item in results:
        requirement_id = str(item["requirement_id"])
        _require(
            item.get("baseline_verdict") == baseline[requirement_id],
            f"Stage 5 baseline differs: {requirement_id}",
        )
        _require(
            item.get("candidate_result") == "PASS", f"Stage 5 candidate nonpass: {requirement_id}"
        )
        _require(
            bool(_list(item.get("controls"), f"Stage 5 controls missing: {requirement_id}")),
            f"Stage 5 controls empty: {requirement_id}",
        )
    summary = _mapping(verdict.get("summary"), "Stage 5 summary missing")
    _require(
        dict(summary)
        == {
            "requirement_count": 23,
            "phase8_pass_preserved": 11,
            "c1_locally_addressed_revalidated": 2,
            "stage5_locally_addressed": 10,
            "candidate_pass": 23,
            "candidate_nonpass": 0,
        },
        "Stage 5 verdict summary differs",
    )
    _require(
        verdict.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
        "Stage 5 verdict execution boundary differs",
    )


def _validate_authority(root: Path) -> tuple[int, int, str]:
    path = _safe_file(
        root, "spec/part1-stage5-documentation-authority-v1.json", "Stage 5 authority"
    )
    authority = _load(path)
    _require(
        authority.get("project") == PROJECT and authority.get("stage") == 5,
        "Stage 5 authority identity differs",
    )
    inventory = [
        _mapping(item, "document inventory item invalid")
        for item in _list(
            authority.get("required_document_inventory"), "document inventory missing"
        )
    ]
    _require(
        [item.get("category") for item in inventory] == DOCUMENT_CATEGORIES,
        "OP-S5-R001 document categories differ",
    )
    paths: list[str] = []
    for item in inventory:
        owned = [
            str(value)
            for value in _list(item.get("paths"), f"document paths missing: {item.get('category')}")
        ]
        _require(bool(owned), f"document category empty: {item.get('category')}")
        for relative in owned:
            _safe_file(root, relative, "required Stage 5 document")
        paths.extend(owned)
    _require(len(paths) == len(set(paths)), "duplicate Stage 5 document ownership")
    contract_count = _validate_contracts(root, authority)
    scenario_count = _validate_reasons(root, authority)
    _validate_aws_target(root, authority)
    _validate_scorecard(root, authority)
    _validate_claims_and_status(root, authority)
    _validate_links(root)
    _validate_traceability_and_verdict(root)
    return contract_count, scenario_count, sha256(path.read_bytes()).hexdigest()


def _validate_contract(root: Path) -> tuple[dict[str, str], str]:
    path = _safe_file(root, "contracts/part1-stage5-correction-v1.json", "Stage 5 contract")
    contract = _load(path)
    _require(
        contract.get("project") == PROJECT
        and contract.get("part") == 1
        and contract.get("stage") == 5,
        "Stage 5 contract identity differs",
    )
    _require(
        contract.get("workstream") == "C3" and contract.get("state") == STAGE5_STATE,
        "Stage 5 contract state differs",
    )
    _require(
        contract.get("part1_state") == PART1_STATE and contract.get("part2_entry") == PART2_STATE,
        "Stage 5 active boundary differs",
    )
    dependency = _mapping(contract.get("c2_dependency"), "C2 dependency missing")
    _require(
        dependency.get("manifest_sha256") == C2_MANIFEST_SHA256
        and dependency.get("exact_head_ci_run_id") == 33596879824,
        "C2 dependency differs",
    )
    _require(
        contract.get("direct_requirement_ids") == DIRECT_STAGE5_IDS, "direct Stage 5 scope differs"
    )
    _require(
        contract.get("all_stage5_requirement_ids") == ALL_STAGE5_IDS, "all Stage 5 scope differs"
    )
    _require(
        contract.get("locally_addressed_count") == 10
        and contract.get("implementation_remaining_count") == 68,
        "Stage 5 correction counts differ",
    )
    _require(
        contract.get("remaining_workstreams") == ["C3", "C4", "C5", "C6", "C7"],
        "Stage 5 remaining workstreams differ",
    )
    _require(
        contract.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
        "Stage 5 contract execution boundary differs",
    )
    _require(
        contract.get("promotion_boundary") == EXPECTED_PROMOTION_BOUNDARY,
        "Stage 5 promotion boundary differs",
    )
    artifacts = _mapping(contract.get("artifacts"), "Stage 5 artifacts missing")
    actual: dict[str, str] = {}
    for name, raw in artifacts.items():
        item = _mapping(raw, f"Stage 5 artifact invalid: {name}")
        relative = item.get("path")
        if not isinstance(relative, str):
            raise C3Error(f"Stage 5 artifact path missing: {name}")
        digest = _digest(root, relative)
        _require(digest == item.get("sha256"), f"Stage 5 artifact digest differs: {relative}")
        actual[str(name)] = digest
    _require(len(actual) == 21, "Stage 5 artifact inventory differs")
    return actual, sha256(path.read_bytes()).hexdigest()


def validate_stage5(root: Path | None = None, *, verify_evidence: bool = True) -> dict[str, Any]:
    """Validate Stage 5 and return deterministic candidate evidence."""

    repository = (root or Path.cwd()).resolve()
    c2 = reproduce_c2(repository)
    contract_count, scenario_count, authority_digest = _validate_authority(repository)
    artifacts, contract_digest = _validate_contract(repository)
    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 5,
        "workstream": "C3",
        "workstream_state": STAGE5_STATE,
        "state": PART1_STATE,
        "project_state": PROJECT_STATE,
        "part2_entry": PART2_STATE,
        "c2_sha256": c2["c2_sha256"],
        "c2_manifest_sha256": C2_MANIFEST_SHA256,
        "documentation_authority_sha256": authority_digest,
        "direct_requirement_ids": DIRECT_STAGE5_IDS,
        "all_stage5_requirement_count": 23,
        "stage5_candidate_pass_count": 23,
        "locally_addressed_count": 10,
        "implementation_remaining_count": 68,
        "remaining_workstreams": ["C3", "C4", "C5", "C6", "C7"],
        "active_contract_count": contract_count,
        "failure_scenario_count": scenario_count,
        "contract_sha256": contract_digest,
        "artifact_digests": artifacts,
        "execution_boundary": EXPECTED_EXECUTION_BOUNDARY,
        "promotion_boundary": EXPECTED_PROMOTION_BOUNDARY,
        "final_c7_audit_required": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage5_sha256"] = sha256(canonical).hexdigest()
    if verify_evidence:
        evidence = _load(
            _safe_file(repository, "evidence/part1-stage5-local.json", "Stage 5 local evidence")
        )
        _require(
            evidence.get("contract_sha256") == contract_digest, "Stage 5 evidence contract differs"
        )
        _require(
            evidence.get("stage5_sha256") == payload["stage5_sha256"],
            "Stage 5 evidence digest differs",
        )
        local = _mapping(evidence.get("local_validation"), "Stage 5 local validation missing")
        for field in (
            "ruff_format",
            "ruff_lint",
            "strict_mypy",
            "pytest",
            "stage5_focused_pytest",
            "c2_reproduction",
            "document_inventory",
            "contract_names_and_versions",
            "reason_code_schema_parity",
            "aws_target_document_parity",
            "scorecard_document_parity",
            "status_parity",
            "markdown_links_and_fragments",
            "managed_claim_rejection",
            "implementation_claim_rejection",
            "forbidden_language_rejection",
            "all_331_test_traceability",
            "all_23_stage5_revalidation",
            "adversarial_mutations",
            "determinism",
        ):
            _require(local.get(field) == "PASS", f"Stage 5 local validation differs: {field}")
        _require(isinstance(local.get("test_count"), int), "Stage 5 test count missing")
        _require(
            evidence.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
            "Stage 5 evidence boundary differs",
        )
        external = _mapping(evidence.get("external_ci"), "Stage 5 external CI missing")
        _require(
            external.get("exact_head_ci") == "REQUIRED_EXTERNAL"
            and external.get("merge") == "PROHIBITED_IN_STAGE5",
            "Stage 5 external boundary differs",
        )
    return payload


def main() -> None:
    print(json.dumps(validate_stage5(Path.cwd()), indent=2, sort_keys=True))


def main_c2() -> None:
    print(json.dumps(reproduce_c2(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
