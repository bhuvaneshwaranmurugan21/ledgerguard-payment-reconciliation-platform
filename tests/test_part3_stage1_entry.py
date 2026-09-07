from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from ledgerguard_part3_stage1_validation import EntryRejected, validate_entry

ROOT = Path(__file__).resolve().parents[1]


def test_stage1_entry_owns_all_master_obligations_and_preserves_authority() -> None:
    assert validate_entry(ROOT) == {
        "schema_version": "1.0",
        "base": "cb81704adcfdfac5d93879cd6c189fc2213bbe79",
        "protected_authorities": 127,
        "master_requirements": 99,
        "master_gates_executed": 0,
        "conformance_gaps": 11,
    }


def copy_entry(tmp_path: Path) -> Path:
    # Full source snapshot: checks read the real authority inventory, never a substitute inventory.
    shutil.copytree(
        ROOT,
        tmp_path / "repository",
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "*.egg-info",
        ),
    )
    return tmp_path / "repository"


@pytest.mark.parametrize(
    "alteration",
    [
        "base",
        "freeze",
        "protected",
        "source",
        "source-digest",
        "master-digest",
        "source-lines",
        "fragment",
        "atomic-coverage",
        "classification",
        "requirements",
        "row-binding",
        "future-pass",
        "reverse-missing",
        "reverse-links",
        "artifact-pass",
        "gate-owner",
        "gate-pass",
        "authority",
        "gap-missing",
        "gap-pass",
        "claim",
        "unknown-field",
    ],
)
def test_entry_tampering_is_rejected(tmp_path: Path, alteration: str) -> None:
    root = copy_entry(tmp_path)

    def change(path: str) -> dict[str, Any]:
        return json.loads((root / path).read_text())

    path = "spec/part3-source-index-v1.json"
    if alteration in ("base", "freeze"):
        path = "contracts/part2-part3-handoff-v1.json"
        v = change(path)
        v["base_commit" if alteration == "base" else "external_closure_sha256"] = "0" * 64
    elif alteration in ("protected", "source"):
        path = (
            "contracts/v2/case-revision-v2.schema.json"
            if alteration == "protected"
            else "spec/sources/part3-execution-plan-v1.md"
        )
        (root / path).write_text((root / path).read_text() + "\n")
        with pytest.raises(EntryRejected):
            validate_entry(root)
        return
    elif alteration in (
        "source-digest",
        "master-digest",
        "source-lines",
        "fragment",
        "atomic-coverage",
        "classification",
        "unknown-field",
    ):
        v = change(path)
        if alteration in ("source-digest", "master-digest"):
            v["source_sha256"] = "0" * 64
        elif alteration == "source-lines":
            v["lines"] = v["lines"][1:]
        elif alteration == "fragment":
            v["lines"][2]["source_fragment"] = "altered objective"
        elif alteration == "atomic-coverage":
            v["lines"][2]["requirements"].pop()
        elif alteration == "classification":
            v["lines"][2]["classification"] = "CONTEXT"
        else:
            v["extra"] = True
    elif alteration in ("requirements", "row-binding", "future-pass"):
        path = "spec/part3-requirements-v1.json"
        v = change(path)
        if alteration == "requirements":
            v["requirements"].pop()
        elif alteration == "row-binding":
            v["requirements"][0]["source_line"] = 226
        else:
            v["requirements"][0]["state"] = "EXTERNALLY_VERIFIED"
    elif alteration in ("reverse-missing", "reverse-links", "artifact-pass"):
        path = "spec/part3-traceability-v1.json"
        v = change(path)
        if alteration == "reverse-missing":
            v["artifacts"].pop()
        elif alteration == "reverse-links":
            v["artifacts"][0]["requirements"] = ["unowned"]
        else:
            v["artifacts"][0]["state"] = "LOCAL_VERIFIED"
    elif alteration in ("gate-owner", "gate-pass"):
        path = "spec/part3-master-gates-v1.json"
        v = change(path)
        if alteration == "gate-owner":
            v["gates"][0]["owner_stage"] = 7
        else:
            v["gates"][0]["state"] = "PASSED"
    else:
        path = "spec/part2-master-conformance-addendum-v1.json"
        v = change(path)
        if alteration == "authority":
            v["historical_authority_sha256"] = "0" * 64
        elif alteration == "gap-missing":
            v["gaps"].pop()
        elif alteration == "gap-pass":
            v["gaps"][0]["state"] = "LOCAL_VERIFIED"
        else:
            v["claims"]["project_complete"] = True
    (root / path).write_text(json.dumps(v))
    with pytest.raises(EntryRejected):
        validate_entry(root)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("owner_stage", 1, "owner differs"),
        ("dependencies", [], "dependencies differ"),
        ("inherited_constraints", ["synthetic-only"], "constraints differ"),
    ],
)
def test_master_owner_and_dependencies_cannot_drift(
    tmp_path: Path, field: str, value: Any, message: str
) -> None:
    root = copy_entry(tmp_path)
    path = root / "spec/part3-requirements-v1.json"
    document = json.loads(path.read_text())
    document["requirements"][0][field] = value
    path.write_text(json.dumps(document))
    with pytest.raises(EntryRejected, match=message):
        validate_entry(root)


def test_current_publication_and_automatic_execution_boundary() -> None:
    from ledgerguard_part3_stage1_validation import validate_surfaces

    result = validate_surfaces(ROOT)
    assert result["part2_publication_verified"] is True
    assert result["aws_master_gates_executed"] == 0


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "publication",
        "permissions",
        "oidc",
        "action",
        "toolchain",
        "historical-root",
        "artifact-inventory",
    ],
)
def test_current_surfaces_fail_closed(tmp_path: Path, field: str) -> None:
    from ledgerguard_part3_stage1_validation import validate_surfaces

    root = copy_entry(tmp_path)
    if field in ("status", "publication"):
        path = root / "PROJECT_STATUS.md"
        text = (
            path.read_text().replace("PART3_STAGE1_IN_PROGRESS", "PART3_COMPLETE")
            if field == "status"
            else path.read_text().replace("33904881790", "00000000000")
        )
    else:
        path = root / ".github/workflows/ci.yml"
        text = path.read_text()
        if field == "permissions":
            text = text.replace("contents: read", "contents: write")
        elif field == "oidc":
            text += "\n# id-token: write\n"
        elif field == "action":
            text = text.replace(
                "actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38",
                "actions/setup-python@main",
            )
        elif field == "artifact-inventory":
            text = text.replace("          include-hidden-files: true\n", "")
        elif field == "toolchain":
            text = text.replace('python-version: "3.11.13"', 'python-version: "3.12"')
        else:
            text = text.replace(
                "working-directory: ${{ runner.temp }}/ledgerguard-part2-stage8-external-closure",
                "working-directory: .",
            )
    path.write_text(text)
    with pytest.raises(EntryRejected):
        validate_surfaces(root)


def test_carryover_owner_cannot_move_out_of_its_required_stage(tmp_path: Path) -> None:
    root = copy_entry(tmp_path)
    path = root / "spec/part2-master-conformance-addendum-v1.json"
    v = json.loads(path.read_text())
    v["gaps"][3]["owner_stage"] = 3
    path.write_text(json.dumps(v))
    with pytest.raises(EntryRejected, match="conformance ownership differs"):
        validate_entry(root)
