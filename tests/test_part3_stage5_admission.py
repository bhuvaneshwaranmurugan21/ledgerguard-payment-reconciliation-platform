"""Real parsing/hash checks on isolated bytes; never AWS/runtime packaging evidence."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from hashlib import sha256
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard.stage3.errors import Stage3Rejected
from ledgerguard_control.admission import Release, admit_execution, verify_release
from ledgerguard_control.contracts import (
    MAX_DOCUMENT_BYTES,
    SCHEMAS,
    ControlRejected,
    exact_amount,
    job_arguments,
    strict_json,
    validate,
)
from ledgerguard_control.glue_arguments import GlueServiceContract, adapt_glue_arguments


def fixture() -> tuple[dict[str, Any], bytes, dict[str, bytes], Release]:
    artifacts = {
        "runtime.zip": b"isolated runtime identity test bytes",
        "ledgerguard_stage5_job.py": b"isolated script identity test bytes",
        "ledgerguard.gluewheels.zip": b"isolated wheels identity test bytes",
    }
    runtime = {
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "runtime_package_sha256": sha256(artifacts["runtime.zip"]).hexdigest(),
        "script_sha256": sha256(artifacts["ledgerguard_stage5_job.py"]).hexdigest(),
        "wheels_sha256": sha256(artifacts["ledgerguard.gluewheels.zip"]).hexdigest(),
    }
    raw = canonical_bytes({"schema_version": "ledgerguard.release.v1", "runtime": runtime})
    release = verify_release(raw, sha256(raw).hexdigest(), artifacts)
    job = {
        "run_id": "run-test1",
        "attempt_id": "attempt-1",
        "control_record_identity": "control-1",
        "policy_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "source_bundle_sha256": "3" * 64,
        "source_commit": "c" * 40,
        "source_tree": release.source_tree,
        "runtime_package_sha256": release.runtime_package_sha256,
        "workload_bucket": "ledgerguard-test",
        "input_prefix": "s3://ledgerguard-test/runs/run-test1/inputs",
        "candidate_output_prefix": "s3://ledgerguard-test/runs/run-test1/attempts/attempt-1/candidates",
        "evidence_prefix": "s3://ledgerguard-test/runs/run-test1/attempts/attempt-1/evidence",
    }

    def ref(name: str) -> dict[str, Any]:
        return {
            "uri": f"{job['input_prefix']}/{name}.json",
            "version_id": "version-1",
            "sha256": "d" * 64,
            "size_bytes": 5,
        }

    value = {
        "schema_version": "ledgerguard.execution-input.v1",
        "job": job,
        "runtime": runtime,
        "release_manifest_sha256": release.manifest_sha256,
        "namespace": "namespace-1",
        "predecessor": None,
        "expected_results": ref("expected"),
        "input_inventory": ref("inventory"),
    }
    return value, raw, artifacts, release


def admit(value: dict[str, Any], release: Release) -> dict[str, Any]:
    return admit_execution(
        canonical_bytes(value),
        release,
        job_arguments(value["job"]),
        value["expected_results"],
        value["input_inventory"],
    )


def test_release_input_provenance_and_exact_snapshot() -> None:
    value, raw, artifacts, release = fixture()
    assert verify_release(raw, release.manifest_sha256, artifacts) == release
    assert value["job"]["source_commit"] != release.source_commit
    result = admit(value, release)
    assert result == value
    value["runtime"]["source_commit"] = "f" * 40
    assert result["runtime"]["source_commit"] == release.source_commit
    with pytest.raises(ControlRejected, match="qualified release"):
        admit(value, release)


@pytest.mark.parametrize(
    "name",
    [
        "runtime.zip",
        "ledgerguard_stage5_job.py",
        "ledgerguard.gluewheels.zip",
    ],
)
def test_release_actual_artifact_corruption(name: str) -> None:
    _, raw, artifacts, release = fixture()
    artifacts[name] += b"changed"
    with pytest.raises(ControlRejected, match="artifact digest mismatch"):
        verify_release(raw, release.manifest_sha256, artifacts)


def test_release_rejects_unpinned_malformed_and_incomplete_inventory() -> None:
    _, raw, artifacts, release = fixture()
    with pytest.raises(ControlRejected, match="manifest digest"):
        verify_release(raw + b" ", release.manifest_sha256, artifacts)
    raw = b'{"schema_version":"wrong"}'
    with pytest.raises(ControlRejected, match="invalid release"):
        verify_release(raw, sha256(raw).hexdigest(), artifacts)
    _, raw, artifacts, release = fixture()
    del artifacts["runtime.zip"]
    with pytest.raises(ControlRejected, match="inventory"):
        verify_release(raw, release.manifest_sha256, artifacts)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":1.0}',
        b'{"a":1e3}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"[]",
        b"null",
        b'"text"',
        b"\xff",
        b"{",
        b'{"a":"\\u0001"}',
        b'{"a":"\\ud800"}',
        '{"a":"e\u0301"}'.encode(),
        b"\xef\xbb\xbf{}",
        b'{"a":' + b"[" * 40 + b"0" + b"]" * 40 + b"}",
        b'{"a":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}",
        b" " * (MAX_DOCUMENT_BYTES + 1),
    ],
)
def test_strict_json_rejects_ambiguous_or_unbounded_transport(raw: bytes) -> None:
    with pytest.raises(ControlRejected):
        strict_json(raw)


def test_strict_json_preserves_large_integers_and_canonical_unicode() -> None:
    raw = '{"amount":99999999999999999999999999999999999999,"s":"é","v":[true,null]}'.encode()
    value = strict_json(raw)
    assert value["amount"] == 10**38 - 1
    assert value["s"] == "é"
    assert value["v"] == [True, None]


@pytest.mark.parametrize("value", ["0", "1", "-1", "9" * 38, "-" + "9" * 38])
def test_exact_amount_boundaries(value: str) -> None:
    assert exact_amount(value) == int(value)


@pytest.mark.parametrize("value", ["-0", "+1", "01", "1.0", "1e3", "9" * 39, "", " 1", 1, True])
def test_exact_amount_rejection(value: Any) -> None:
    with pytest.raises(ControlRejected):
        exact_amount(value)


@pytest.mark.parametrize("kind", sorted(SCHEMAS))
def test_all_contracts_are_closed_and_versioned(kind: str) -> None:
    schema = SCHEMAS[kind]
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == f"ledgerguard.{kind}.v1"
    assert set(schema["properties"]) == set(schema["required"])


@pytest.mark.parametrize(
    "edit",
    [
        lambda v: v.update(extra=True),
        lambda v: v["job"].update(extra=True),
        lambda v: v["job"].update(run_id="invalid"),
        lambda v: v["expected_results"].update(size_bytes=True),
        lambda v: v["expected_results"].update(size_bytes=1.0),
        lambda v: v["expected_results"].update(size_bytes=2**63),
        lambda v: v["expected_results"].update(size_bytes=-1),
        lambda v: v.update(predecessor="not-a-hash"),
        lambda v: v["runtime"].update(source_tree="f" * 64),
    ],
)
def test_execution_shape_rejections(edit: Any) -> None:
    value, _, _, _ = fixture()
    edit(value)
    with pytest.raises(ControlRejected):
        validate("execution-input", value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_tree", "e" * 40),
        ("runtime_package_sha256", "e" * 64),
    ],
)
def test_job_runtime_binding(field: str, value: str) -> None:
    document, _, _, release = fixture()
    document["job"][field] = value
    with pytest.raises(ControlRejected, match="job runtime"):
        admit(document, release)


def test_admission_trust_is_external_to_request() -> None:
    value, _, _, release = fixture()
    registered = job_arguments(value["job"])
    expected = copy.deepcopy(value["expected_results"])
    inventory = copy.deepcopy(value["input_inventory"])
    for key in ("expected_results", "input_inventory"):
        altered = copy.deepcopy(value)
        altered[key]["sha256"] = "e" * 64
        with pytest.raises(ControlRejected, match="untrusted"):
            admit_execution(canonical_bytes(altered), release, registered, expected, inventory)
    value["job"]["policy_sha256"] = "f" * 64
    with pytest.raises(ControlRejected, match="independently admitted"):
        admit_execution(canonical_bytes(value), release, registered, expected, inventory)
    value, _, _, release = fixture()
    value["release_manifest_sha256"] = "f" * 64
    with pytest.raises(ControlRejected, match="unqualified"):
        admit(value, release)


@pytest.mark.parametrize(
    "uri",
    [
        "s3://other-bucket/runs/run-test1/inputs/expected.json",
        "s3://ledgerguard-test/runs/other-run/inputs/expected.json",
        "s3://ledgerguard-test/runs/run-test1/inputs/nested/expected.json",
        "s3://ledgerguard-test/runs/run-test1/inputs/../expected.json",
        "s3://ledgerguard-test/runs/run-test1/inputs/expected.json/",
    ],
)
def test_reference_confinement(uri: str) -> None:
    value, _, _, release = fixture()
    value["expected_results"]["uri"] = uri
    with pytest.raises((ControlRejected, Stage3Rejected)):
        admit(value, release)


def test_input_versions_and_distinct_references() -> None:
    value, _, _, release = fixture()
    value["expected_results"]["version_id"] = "null"
    with pytest.raises(ControlRejected, match="versioned input"):
        admit(value, release)
    value["expected_results"] = dict(value["input_inventory"])
    with pytest.raises(ControlRejected, match="distinct"):
        admit(value, release)


def service_fixture() -> tuple[list[str], GlueServiceContract, Any]:
    value, _, _, release = fixture()
    admitted = job_arguments(value["job"])
    contract = GlueServiceContract(
        "ledgerguard-test-job",
        admitted.workload_bucket,
        "/lg/glue",
        release,
    )
    values = {key.replace("_", "-"): item for key, item in asdict(admitted).items()}
    values.update(contract.configured())
    values["JOB_RUN_ID"] = "jr_" + "d" * 64
    argv = [item for key, value in values.items() for item in (f"--{key}", value)]
    return argv, contract, admitted


def test_service_adapter_handles_installer_and_presence_flag() -> None:
    argv, contract, admitted = service_fixture()
    assert adapt_glue_arguments(argv, contract, admitted) == (admitted, "jr_" + "d" * 64)
    argv.remove("")
    assert adapt_glue_arguments(argv, contract, admitted)[0] == admitted


@pytest.mark.parametrize(
    "tail",
    [
        ["--unknown", "true"],
        ["--enable-metrics"],
        ["--run-id", "run-test1"],
        ["value"],
        ["--JOB_NAME", ""],
    ],
)
def test_service_unknown_duplicate_or_unframed_arguments(tail: list[str]) -> None:
    argv, contract, admitted = service_fixture()
    with pytest.raises(ControlRejected):
        adapt_glue_arguments(argv + tail, contract, admitted)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--python-modules-installer-option", "--index-url=evil"),
        ("--additional-python-modules", "unqualified-package"),
        ("--enable-metrics", "false"),
        ("--enable-metrics", "true"),
        ("--JOB_NAME", "other-job"),
        ("--JOB_RUN_ID", "jr_fake"),
        ("--TempDir", "s3://other-bucket/tmp/"),
        ("--runtime-source-commit", "f" * 40),
        ("--run-id", "run-else"),
        ("--policy-sha256", "--unknown"),
    ],
)
def test_service_conflicts_and_business_rejections(flag: str, value: str) -> None:
    argv, contract, admitted = service_fixture()
    argv[argv.index(flag) + 1] = value
    with pytest.raises((ControlRejected, Stage3Rejected)):
        adapt_glue_arguments(argv, contract, admitted)


def test_service_missing_and_runtime_binding() -> None:
    argv, contract, admitted = service_fixture()
    with pytest.raises(ControlRejected, match="requires one value"):
        adapt_glue_arguments(argv[:-1], contract, admitted)
    with pytest.raises(ControlRejected, match="missing"):
        adapt_glue_arguments(argv[2:], contract, admitted)
    argv[argv.index("--JOB_NAME") + 1] = ""
    with pytest.raises(ControlRejected, match="requires one value"):
        adapt_glue_arguments(argv, contract, admitted)
    argv, contract, admitted = service_fixture()
    altered = replace(admitted, source_tree="f" * 40)
    argv[argv.index("--source-tree") + 1] = altered.source_tree
    with pytest.raises(ControlRejected, match="runtime provenance"):
        adapt_glue_arguments(argv, contract, altered)


def test_in_memory_contract_rejects_non_json_keys_values_and_oversize() -> None:
    for extra in ({1: "key"}, {"x": (1,)}, {"x": b"bytes"}):
        with pytest.raises(ControlRejected):
            validate("execution-input", extra)
    with pytest.raises(ControlRejected, match="unknown document"):
        validate("unknown", {})
    with pytest.raises(ControlRejected, match="byte bound"):
        validate("execution-input", {"x": "a" * MAX_DOCUMENT_BYTES})
    with pytest.raises(ControlRejected, match="job argument"):
        job_arguments({"x": True})
    with pytest.raises(ControlRejected):
        strict_json(json.dumps({"x": 1.5}).encode())


def test_valid_but_different_business_identity_is_rejected() -> None:
    argv, contract, admitted = service_fixture()
    argv[argv.index("--policy-sha256") + 1] = "f" * 64
    with pytest.raises(ControlRejected, match="differ from admitted"):
        adapt_glue_arguments(argv, contract, admitted)
