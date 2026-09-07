"""Fail-closed Part 3 entry ownership and immutable-inheritance validation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard.reconciliation import parse_strict_json

BASE = "cb81704adcfdfac5d93879cd6c189fc2213bbe79"
EXTERNAL_FREEZE_SHA = "82f9b6b3a0ab200cd62698017836ad1c3b00e6eb46130defbcce1ee4f2e0ab6d"
SOURCE_DIGESTS = dict(
    zip(
        (
            "spec/sources/master-part3-extract-v1.txt",
            "spec/sources/part3-execution-plan-v1.md",
            "spec/sources/part3-stage1-execution-plan-v1.md",
        ),
        (
            "239c8b0e74946542237287f41674abbf7da5933eda3b4007f17cfd6290b2e577",
            "c05797e39f2659fe28401c1e90ac101093fa852822a9f60b5099974e6567e318",
            "ae9c8d640565cfe70d2aaf04e1be2fbcafe2ecc3425ac893904fa64b98a646ab",
        ),
        strict=True,
    )
)
MASTER_SHA = "0a7f2541d1ab5ce4d0aadabd871ddfe6f75bfdb6b7261efed7f97315b1e874df"
CONTEXT = {221, 222, 224, 225, 240, 241, 254, 255, 265, 280, 281, 292, 293}
MULTIPLICITY = {
    223: 5,
    227: 2,
    228: 2,
    234: 3,
    242: 5,
    243: 2,
    244: 2,
    249: 2,
    252: 2,
    256: 2,
    261: 2,
    266: 2,
    269: 2,
    273: 2,
    275: 2,
    279: 4,
    283: 2,
    291: 2,
    296: 2,
    302: 2,
}
MASTER_GATES = {
    "environment_qualified": 2,
    "live_iam_parity_verified": 2,
    "glue_definition_probe_verified": 2,
    "plan_only_verified": 6,
    "zero_workload_canary_verified": 7,
    "teardown_verified": 7,
}


class EntryRejected(ValueError):
    """Current source does not satisfy the preserved Stage 1 entry contract."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise EntryRejected(message)


def read(root: Path, path: str) -> dict[str, Any]:
    value = parse_strict_json((root / path).read_bytes())
    check(isinstance(value, dict), f"object required: {path}")
    return cast(dict[str, Any], value)


def sha(root: Path, path: str) -> str:
    return hashlib.sha256((root / path).read_bytes()).hexdigest()


def document(root: Path, name: str) -> dict[str, Any]:
    schema = read(root, f"contracts/part3/{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    value = read(root, f"spec/{name}.json")
    errors = list(Draft202012Validator(schema).iter_errors(value))
    check(not errors, f"schema violation: {name}: {errors[:1]}")
    return value


def validate_entry(root: Path) -> dict[str, Any]:
    """Verify obligations and source bytes; never infer execution from ownership."""
    handoff = read(root, "contracts/part2-part3-handoff-v1.json")
    check(handoff["base_commit"] == BASE, "entry base differs")
    check(
        set(handoff)
        == {
            "base_commit",
            "base_tree",
            "claim_boundary",
            "external_closure",
            "external_closure_sha256",
            "project",
            "required_carryovers",
            "schema_version",
            "sources",
            "state",
            "original_master",
        },
        "handoff fields differ",
    )
    check(handoff["sources"] == SOURCE_DIGESTS, "source document identities differ")
    freeze_path = handoff["external_closure"]
    check(
        freeze_path == "spec/part2-stage8-external-closure-freeze-v1.json", "closure path differs"
    )
    check(sha(root, freeze_path) == handoff["external_closure_sha256"], "closure freeze differs")
    check(handoff["external_closure_sha256"] == EXTERNAL_FREEZE_SHA, "closure identity differs")
    freeze = read(root, freeze_path)
    for path, expected in freeze["protected_authorities"].items():
        check(sha(root, path) == expected, f"protected authority changed: {path}")
    check(len(freeze["protected_authorities"]) >= 127, "protected inventory is incomplete")
    for path, expected in handoff["sources"].items():
        check(sha(root, path) == expected, f"source changed: {path}")
    index = document(root, "part3-source-index-v1")
    check(index["source_sha256"] == MASTER_SHA, "master identity differs")
    check(sha(root, index["source_path"]) == index["extract_sha256"], "master extract bytes differ")
    check(handoff["original_master"]["sha256"] == MASTER_SHA, "original master digest differs")
    source = (root / index["source_path"]).read_text().splitlines()
    lines = index["lines"]
    check([row["line"] for row in lines] == list(range(221, 304)), "source line inventory differs")
    expected_ids: dict[str, int] = {}
    for row in lines:
        number = row["line"]
        check(row["source_fragment"] == source[number - 221], "source fragment differs")
        expected = (
            []
            if number in CONTEXT
            else [f"P3-M-L{number:03d}-{i:02d}" for i in range(1, MULTIPLICITY.get(number, 1) + 1)]
        )
        check(row["requirements"] == expected, "atomic source coverage differs")
        check(
            row["classification"] == ("CONTEXT" if number in CONTEXT else "NORMATIVE"),
            "source classification differs",
        )
        expected_ids.update(dict.fromkeys(expected, number))
    requirements = document(root, "part3-requirements-v1")["requirements"]
    check(
        [row["requirement_id"] for row in requirements] == list(expected_ids),
        "requirement inventory differs",
    )
    forward: dict[str, list[str]] = {}
    for row in requirements:
        identifier = row["requirement_id"]
        number = expected_ids[identifier]
        check(
            row["source_line"] == number
            and row["source_sha256"] == MASTER_SHA
            and row["source_path"] == index["source_path"]
            and row["source_fragment"] == source[number - 221],
            "requirement source binding differs",
        )
        check(
            row["state"] == "OWNED_OPEN" and not row["implementation"] and not row["tests"],
            "future obligation falsely executed",
        )
        owner = (
            2
            if number <= 239
            else 4
            if number <= 253
            else 5
            if number <= 264
            else 4
            if number <= 279
            else 6
            if number <= 283
            else 7
            if number <= 291
            else 8
        )
        if number == 223:
            owner = 8
        if number in (266, 267, 276):
            owner = 2
        if number in (277, 278):
            owner = 7
        check(row["owner_stage"] == owner, "requirement owner differs")
        check(
            row["dependencies"] == ([] if owner == 2 else [f"part3-stage{owner - 1}"]),
            "requirement dependencies differ",
        )
        check(
            row["inherited_constraints"]
            == [
                "frozen-v1-v2-authorities",
                "gross-project-usd-10",
                "synthetic-only",
                "no-workload-before-part4",
            ],
            "inherited constraints differ",
        )
        for path in row["expected_evidence"]:
            forward.setdefault(path, []).append(identifier)
    reverse = document(root, "part3-traceability-v1")["artifacts"]
    check(len(reverse) == len(forward), "reverse traceability inventory differs")
    check(
        {row["path"]: row["requirements"] for row in reverse} == forward,
        "reverse traceability links differ",
    )
    check(all(row["state"] == "PLANNED" for row in reverse), "planned artifact falsely executed")
    gates = document(root, "part3-master-gates-v1")["gates"]
    check(
        {row["gate_id"]: row["owner_stage"] for row in gates} == MASTER_GATES,
        "master gate ownership differs",
    )
    addendum = read(root, "spec/part2-master-conformance-addendum-v1.json")
    check(
        sha(root, addendum["historical_authority"]) == addendum["historical_authority_sha256"],
        "historical completion authority differs",
    )
    gaps = addendum["gaps"]
    check(
        [row["gap_id"] for row in gaps] == [f"LG-P3-G{i:03d}" for i in range(1, 12)],
        "conformance gap inventory differs",
    )
    check(all(row["state"] == "OWNED_OPEN" for row in gaps), "open conformance gap falsely closed")
    check(
        [(row["owner_part"], row["owner_stage"]) for row in gaps]
        == [(3, 2), (3, 1), (3, 3), (3, 1), (3, 3), (4, 3), (4, 3), (3, 4), (4, 1), (5, 1), (3, 3)],
        "conformance ownership differs",
    )
    check(
        addendum["claims"]
        == dict(
            part2_local=True,
            part3_complete=False,
            aws_verified=False,
            scale_verified=False,
            project_complete=False,
        ),
        "claim boundary differs",
    )
    return {
        "schema_version": "1.0",
        "base": BASE,
        "protected_authorities": len(freeze["protected_authorities"]),
        "master_requirements": len(requirements),
        "master_gates_executed": 0,
        "conformance_gaps": len(gaps),
    }


def validate_surfaces(root: Path) -> dict[str, Any]:
    """Check current publication facts and the approved local-only execution surface."""
    import re

    status = (root / "PROJECT_STATUS.md").read_text()
    active = status.split("## Active boundary\n", 1)[1].split("\n## ", 1)[0]
    for marker in (
        "Part: 3 — Managed AWS platform",
        "Stage: 1 — Entry and conformance correction",
        "Stage state: `PART3_STAGE1_IN_PROGRESS`",
        "AWS execution: false",
        "AWS infrastructure mutated: false",
    ):
        check(marker in active, f"current active status differs: {marker}")
    readme = (root / "README.md").read_text()
    completion = (root / "docs/part2-completion.md").read_text()
    for text in (status, readme, completion):
        check(
            BASE in text and "33879453002" in text and "33904881790" in text,
            "current PR 18 publication facts missing",
        )
    check("not yet active on `main`" not in completion, "stale closure candidate claim")
    check("overall project remains in progress" in readme, "project boundary missing")
    workflow = (root / ".github/workflows/ci.yml").read_text()
    check(
        "permissions:\n  contents: read\n  pull-requests: read\n" in workflow,
        "automatic permissions differ",
    )
    for forbidden in (
        "id-token:",
        "aws-actions/",
        "pull_request_target:",
        "secrets.",
        "continue-on-error:",
        "workflow_call:",
        "uses: ./",
    ):
        check(forbidden not in workflow, f"automatic execution boundary differs: {forbidden}")
    actions = re.findall(r"uses: ([^\s]+)", workflow)
    allowed = {
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
        "actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38",
        "actions/setup-java@dd06d9cba3e5552c54d9f8ea23572deb30010f7c",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    }
    check(set(actions) == allowed, "automatic action inventory differs")
    for marker in (
        "github.event.pull_request.head.sha || github.sha",
        "fetch-depth: 0",
        'python-version: "3.11.13"',
        'java-version: "17"',
        "--clean-runs 2",
        "PYSPARK_PYTHON",
        "PYSPARK_DRIVER_PYTHON",
    ):
        combined = workflow + (root / "tools/run_part3_stage1.py").read_text()
        check(marker in combined, f"current toolchain or checkout control missing: {marker}")
    check(
        "working-directory: ${{ runner.temp }}/ledgerguard-part2-stage8-external-closure"
        in workflow,
        "complete PR 18 historical execution root missing",
    )
    check(
        "path: ${{ runner.temp }}/ledgerguard-part3-stage1-artifact\n"
        "          include-hidden-files: true\n" in workflow,
        "artifact upload omits required workflow evidence",
    )
    manifest = read(root, "spec/part3-stage1-test-execution-v1.json")
    check(len(manifest["historical_nodes"]) == 11, "historical governance mapping differs")
    check(
        len({r["node"] for r in manifest["historical_nodes"]}) == 11,
        "historical governance mapping duplicates",
    )
    for row in manifest["historical_nodes"]:
        check((root / row["node"].split("::")[0]).is_file(), "historical test removed")
        check(
            row["current_equivalent"]
            == (
                "tests/test_part3_stage1_entry.py::"
                "test_current_publication_and_automatic_execution_boundary"
            ),
            "historical obligation has no current equivalent",
        )
    return {
        "part2_publication_verified": True,
        "stage1_state": "IN_PROGRESS",
        "automatic_actions": sorted(set(actions)),
        "aws_master_gates_executed": 0,
    }
