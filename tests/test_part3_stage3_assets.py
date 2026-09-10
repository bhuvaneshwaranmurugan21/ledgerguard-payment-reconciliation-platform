from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from ledgerguard.stage3.arguments import parse_job_arguments, parser_contract
from ledgerguard.stage3.campaign import PROPERTIES, case_id, run_campaign
from ledgerguard.stage3.canonical import (
    canonical_bytes,
    canonical_digest,
    normalize,
    semantic_id,
)
from ledgerguard.stage3.errors import Stage3Rejected
from ledgerguard.stage3.expectations import verify_assets
from ledgerguard.stage3.generator import generate_profile
from ledgerguard.stage3.paths import parse_s3_uri, validate_job_paths
from ledgerguard.stage3.profiles import PROFILES, get_profile, profile_identity, validate_profile
from ledgerguard.stage3.runtime_admission import admit_runtime_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "d0fb01392f7f975909229f418c13a9c73ba8395e"


@pytest.fixture()
def small_asset(tmp_path: Path) -> Path:
    root = tmp_path / "asset"
    generate_profile(get_profile("correctness-small"), root, SOURCE_COMMIT)
    return root


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _arguments() -> list[str]:
    run = "run-00000001"
    attempt = "attempt-00000001"
    bucket = "ledgerguard-workload-857229544428"
    values = {
        "run-id": run,
        "attempt-id": attempt,
        "policy-sha256": "1" * 64,
        "source-bundle-sha256": "2" * 64,
        "manifest-sha256": "3" * 64,
        "input-prefix": f"s3://{bucket}/runs/{run}/inputs",
        "candidate-output-prefix": f"s3://{bucket}/runs/{run}/attempts/{attempt}/candidates",
        "evidence-prefix": f"s3://{bucket}/runs/{run}/attempts/{attempt}/evidence",
        "control-record-identity": "control-00000001",
        "source-commit": SOURCE_COMMIT,
        "source-tree": "4" * 40,
        "runtime-package-sha256": "5" * 64,
        "workload-bucket": bucket,
    }
    return [item for key, value in values.items() for item in (f"--{key}", value)]


def test_canonical_semantics_are_nfc_ordered_and_type_strict() -> None:
    assert canonical_bytes({"z": "e\u0301", "a": 1}) == b'{"a":1,"z":"\xc3\xa9"}'
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})
    assert semantic_id("unit", {"a": 1}).startswith("unit-")
    with pytest.raises(Stage3Rejected, match="unsupported value"):
        normalize(1.5)


def test_frozen_profile_registry_and_exact_counts() -> None:
    assert list(PROFILES) == ["correctness-small", "local-10k", "local-100k", "managed-1m"]
    assert [value.processor_event_count for value in PROFILES.values()] == [
        16,
        10_000,
        100_000,
        1_000_000,
    ]
    assert profile_identity("local-10k") == get_profile("local-10k").dataset_id
    assert get_profile("local-10k").dataset_id.startswith("dataset-")
    with pytest.raises(Stage3Rejected, match="unknown profile"):
        get_profile("missing")
    with pytest.raises(Stage3Rejected, match="unknown profile"):
        profile_identity("missing")
    with pytest.raises(Stage3Rejected, match="not a frozen registry"):
        validate_profile(replace(get_profile("local-10k"), seed=1))


@pytest.mark.parametrize(
    "change",
    [
        {"processor_event_count": 0},
        {"events_per_settlement": 0},
        {"shard_rows": 0},
        {"merchant_count": 0},
        {"currencies": ()},
        {"currencies": ("USD", "USD")},
        {"negative_event_cycle": ("REFUND",)},
        {"split_every_settlements": 0},
        {"skew_hotspot_slots": 0},
        {"skew_hotspot_slots": 4},
    ],
)
def test_profile_guard_matrix(change: dict[str, object]) -> None:
    with pytest.raises(Stage3Rejected, match="PROFILE_VIOLATION"):
        validate_profile(replace(get_profile("correctness-small"), **change))


def test_small_generation_is_byte_reproducible_and_independently_verified(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    first = generate_profile(get_profile("correctness-small"), left, SOURCE_COMMIT)
    second = generate_profile(get_profile("correctness-small"), right, SOURCE_COMMIT)
    assert _tree(left) == _tree(right)
    assert first == replace(second, root=left)
    readback = verify_assets(left)
    assert readback.counts == {
        "PROCESSOR_EVENTS": 16,
        "PROCESSOR_SETTLEMENTS": 4,
        "LEDGER_JOURNALS": 20,
        "BANK_ENTRIES": 5,
    }
    assert readback.dataset_id == first.dataset_id
    assert readback.run_id == first.run_id
    scenario = json.loads((left / "scenario-inventory.json").read_text())
    assert len(scenario["scenarios"]) == 21
    assert scenario["parameters"] == {
        "negative_event_cycle": ["REFUND", "CHARGEBACK", "REVERSAL"],
        "split_every_settlements": 10,
        "skew_cycle": 4,
        "skew_hotspot_slots": 3,
        "late_data_strategy": "NEW_IMMUTABLE_REVISION",
        "identical_replay": "SAME_IDENTITY_SAME_PAYLOAD",
        "identity_conflict": "SAME_IDENTITY_DIFFERENT_PAYLOAD",
        "missing_source": "ONE_FAMILY_RECORD_REMOVED",
        "policy_change": "NOT_A_SOURCE_CORRECTION",
    }
    event_rows = [
        json.loads(line)
        for path in sorted((left / "canonical/processor-events").glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["merchant_id"] for row in event_rows].count("merchant-000") == 12
    assert all(
        values["processor_settlement_minor"]
        == values["ledger_settlement_minor"]
        == values["bank_minor"]
        for values in readback.currency_totals.values()
    )


def test_generation_rejects_bad_commit_existing_and_partial_destinations(tmp_path: Path) -> None:
    profile = get_profile("correctness-small")
    with pytest.raises(Stage3Rejected, match="source commit"):
        generate_profile(profile, tmp_path / "bad", "ABC")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(Stage3Rejected, match="destination already exists"):
        generate_profile(profile, existing, SOURCE_COMMIT)
    partial_target = tmp_path / "partial"
    (tmp_path / ".partial.partial").mkdir()
    with pytest.raises(Stage3Rejected, match="partial destination"):
        generate_profile(profile, partial_target, SOURCE_COMMIT)


def test_asset_manifest_or_completion_tampering_is_rejected(small_asset: Path) -> None:
    completion = small_asset / "COMPLETED.json"
    completion.write_text("{}\n", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="completion marker mismatch"):
        verify_assets(small_asset)


def test_scenario_inventory_tampering_is_rejected(small_asset: Path) -> None:
    scenario = small_asset / "scenario-inventory.json"
    value = json.loads(scenario.read_text())
    value["campaign_seed"] += 1
    scenario.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(Stage3Rejected, match="scenario inventory digest mismatch"):
        verify_assets(small_asset)


def test_source_object_tampering_is_rejected_by_runtime_and_reader(small_asset: Path) -> None:
    source = next((small_asset / "raw/processor-events").glob("*.jsonl"))
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(Stage3Rejected, match="file identity mismatch"):
        verify_assets(small_asset)
    with pytest.raises(Stage3Rejected, match="object identity"):
        admit_runtime_bundle(ROOT, small_asset)


def test_runtime_admission_binds_all_four_source_families(small_asset: Path) -> None:
    admitted = admit_runtime_bundle(ROOT, small_asset)
    assert set(admitted.raw_paths) == {
        "PROCESSOR_EVENTS",
        "PROCESSOR_SETTLEMENTS",
        "LEDGER_JOURNALS",
        "BANK_ENTRIES",
    }
    assert admitted.policy["policy_sha256"] == admitted.source_bundle["policy_sha256"]


def test_campaign_is_complete_and_reproducible(small_asset: Path) -> None:
    first = run_campaign(small_asset)
    second = run_campaign(small_asset)
    assert first == second
    assert first.case_count == len(PROPERTIES) == 13
    assert tuple(row["property"] for row in first.cases) == PROPERTIES
    assert all(row["passed"] for row in first.cases)
    assert case_id("ordering") == first.cases[0]["case_id"]
    with pytest.raises(Stage3Rejected, match="invalid property"):
        case_id("unknown")


@pytest.mark.parametrize(
    "uri",
    [
        "https://bucket/key",
        "s3://bucket/key/",
        "s3://bucket/a//b",
        "s3://bucket/a/../b",
        "s3://bucket/latest/x",
        "s3://bucket/current/x",
        "s3://bucket/a%2fb",
        "s3://user:pass@bucket/key",
        "s3://127.0.0.1/key",
        "s3://UPPER/key",
        "s3://bucket/key?query=x",
        "s3://bucket/key#fragment",
        "s3://bucket/a\\b",
    ],
)
def test_s3_uri_negative_matrix(uri: str) -> None:
    with pytest.raises(Stage3Rejected, match="PATH_VIOLATION"):
        parse_s3_uri(uri)


def test_job_path_confinement_accepts_only_exact_run_attempt_prefixes() -> None:
    parsed = parse_job_arguments(_arguments())
    assert parsed.run_id == "run-00000001"
    assert parser_contract().parse_args(_arguments()).run_id == "run-00000001"
    locations = validate_job_paths(
        parsed.workload_bucket,
        parsed.run_id,
        parsed.attempt_id,
        parsed.input_prefix,
        parsed.candidate_output_prefix,
        parsed.evidence_prefix,
    )
    assert locations[0].uri == parsed.input_prefix


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda values: values[:-1], "every flag requires"),
        (lambda values: [*values, "--run-id", "run-00000002"], "duplicate flag"),
        (lambda values: ["--unknown", "x", *values], "unknown flag"),
        (lambda values: values[2:], "missing flags"),
        (lambda values: ["run-id", "x", *values[2:]], "malformed flag"),
    ],
)
def test_argument_structure_negative_matrix(
    mutate: Callable[[list[str]], list[str]], message: str
) -> None:
    with pytest.raises(Stage3Rejected, match=message):
        parse_job_arguments(mutate(_arguments()))


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("run-id", "BAD", "invalid run-id"),
        ("policy-sha256", "x", "invalid policy-sha256"),
        ("source-commit", "A" * 40, "invalid source-commit"),
        ("source-tree", "A" * 40, "invalid source-tree"),
        ("input-prefix", "s3://other/runs/run-00000001/inputs", "wrong workload bucket"),
        (
            "candidate-output-prefix",
            "s3://ledgerguard-workload-857229544428/current",
            "mutable path alias",
        ),
    ],
)
def test_argument_value_negative_matrix(flag: str, value: str, message: str) -> None:
    arguments = _arguments()
    arguments[arguments.index(f"--{flag}") + 1] = value
    with pytest.raises(Stage3Rejected, match=message):
        parse_job_arguments(arguments)


def test_stage3_contract_schemas_are_valid_and_instances_validate(small_asset: Path) -> None:
    from jsonschema import Draft202012Validator

    instance_map = {
        "profile": json.loads((small_asset / "profile-lock.json").read_text())["profile"],
        "source-bundle": json.loads((small_asset / "source-bundle.json").read_text()),
        "asset-manifest": json.loads((small_asset / "asset-manifest.json").read_text()),
        "expectations": json.loads((small_asset / "expectations.json").read_text()),
    }
    for name, instance in instance_map.items():
        schema = json.loads(
            (ROOT / f"contracts/part3-stage3/{name}-v1.schema.json").read_text()
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(instance)
