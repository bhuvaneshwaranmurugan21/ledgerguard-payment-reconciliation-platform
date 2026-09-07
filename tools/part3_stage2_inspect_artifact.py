#!/usr/bin/env python3
"""Independently inspect an extracted Stage 2 artifact."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from ledgerguard.stage2.control import read_object, scan_safe_evidence, validate_manifest

REPOSITORY = "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform"
FAILED_TERMINAL_CONCLUSIONS = {"failure", "cancelled", "timed_out", "stale"}
AUTHORITY_PATHS = {
    ".github/ledgerguard-target.json",
    "contracts/part3-stage2-control-plane-v1.json",
    "contracts/part3-stage2-cost-v1.json",
    "contracts/part3-stage2-glue-probe-v1.json",
    "contracts/part3-stage2-iam-permissions-v1.json",
    "contracts/part3-stage2-inventory-v1.json",
    "contracts/part3-stage2-oidc-trust-v1.json",
    "contracts/part3-stage2-operation-allowlist-v1.json",
    "contracts/part3/stage2-live-evidence-v1.schema.json",
    "fixtures/part3-stage2/inert_glue_probe_script.py",
    "fixtures/part3-stage2/qualification.asl.json",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-run-attempt", required=True)
    parser.add_argument("--expected-classification", required=True)
    parser.add_argument("--expected-state", choices=("PASSED", "FAILED"), default="PASSED")
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--expected-workflow-path", required=True)
    parser.add_argument(
        "--expected-conclusion-class",
        choices=("SUCCESS", "FAILED_TERMINAL"),
        required=True,
    )
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-zip-sha256", required=True)
    parser.add_argument("--expected-journal-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifact = args.artifact.resolve()
    run = read_object(args.run_metadata)
    workflow_path = str(run.get("path", "")).split("@", 1)[0]
    conclusion = run.get("conclusion")
    if (
        str(run.get("id")) != args.expected_run_id
        or run.get("head_sha") != args.expected_sha
        or str(run.get("run_attempt")) != args.expected_run_attempt
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("status") != "completed"
        or workflow_path != args.expected_workflow_path
        or run.get("repository", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError("producer workflow run identity differs")
    if args.expected_conclusion_class == "SUCCESS":
        if conclusion != "success":
            raise ValueError("producer workflow run did not succeed")
    elif conclusion not in FAILED_TERMINAL_CONCLUSIONS:
        raise ValueError("producer workflow run is not a recoverable terminal failure")
    run_binding = {
        "id": str(run["id"]),
        "head_sha": run["head_sha"],
        "run_attempt": str(run["run_attempt"]),
        "event": run["event"],
        "head_branch": run["head_branch"],
        "status": run["status"],
        "conclusion": conclusion,
        "workflow_path": workflow_path,
        "repository": run["repository"]["full_name"],
    }
    evidence = read_object(artifact / "evidence.json")
    schema = read_object(root / "contracts/part3/stage2-live-evidence-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(evidence)
    if (
        len(args.artifact_zip_sha256) != 64
        or any(c not in "0123456789abcdef" for c in args.artifact_zip_sha256)
        or not args.artifact_id.isdigit()
    ):
        raise ValueError("artifact identity input is malformed")
    if evidence["commit"] != args.expected_sha:
        raise ValueError("artifact commit differs")
    if evidence["checkout_commit"] != args.expected_sha:
        raise ValueError("artifact checkout commit differs")
    if evidence["workflow_path"] != args.expected_workflow_path:
        raise ValueError("artifact workflow path differs")
    if evidence["credential_mode"] != "GITHUB_OIDC":
        raise ValueError("artifact credential mode differs")
    expected_authority_paths = AUTHORITY_PATHS | {args.expected_workflow_path}
    if set(evidence["authority_digests"]) != expected_authority_paths:
        raise ValueError("artifact authority path inventory differs")
    for path, digest in evidence["authority_digests"].items():
        if sha256((root / path).read_bytes()).hexdigest() != digest:
            raise ValueError("artifact authority digest differs: " + path)
    if evidence["run_id"] != args.expected_run_id:
        raise ValueError("artifact run differs")
    if evidence["run_attempt"] != args.expected_run_attempt:
        raise ValueError("artifact run attempt differs")
    if evidence["classification"] != args.expected_classification:
        raise ValueError("artifact classification differs")
    if evidence["checks"]["state"] != args.expected_state:
        raise ValueError("producer state differs")
    if evidence["managed_reconciliation_started"] is not False:
        raise ValueError("managed workload boundary differs")
    if args.expected_state == "PASSED" and not all(
        evidence["identity"].get(key) for key in ("account_match", "region_match", "role_match")
    ):
        raise ValueError("successful evidence has unverified identity")
    manifest = read_object(artifact / "manifest.json")
    integrity = validate_manifest(artifact, manifest)
    safety = scan_safe_evidence(artifact)
    journal = json.loads((artifact / "api-journal.json").read_text())
    mutation_journal = json.loads((artifact / "mutation-journal.json").read_text())
    if journal != evidence["api_journal"]:
        raise ValueError("API journal file and evidence differ")
    if mutation_journal != evidence["mutation_journal"]:
        raise ValueError("mutation journal file and evidence differ")
    if [row["sequence"] for row in journal] != list(range(1, len(journal) + 1)):
        raise ValueError("API journal sequence differs")
    mutating = {
        "S3_PUT_OBJECT",
        "S3_DELETE_OBJECT",
        "DDB_PUT_ITEM",
        "DDB_DELETE_ITEM",
        "GLUE_CREATE_JOB",
        "GLUE_DELETE_JOB",
    }
    if mutation_journal != [row for row in journal if row["operation"] in mutating]:
        raise ValueError("mutation journal is not the exact API journal subset")
    journal_sha256 = sha256((artifact / "mutation-journal.json").read_bytes()).hexdigest()
    if args.expected_journal_sha256 and journal_sha256 != args.expected_journal_sha256:
        raise ValueError("journal digest differs")
    forbidden = {
        "GLUE_START_JOB",
        "SFN_START_EXECUTION",
        "ATHENA_START_QUERY",
    }
    if any(row.get("operation") in forbidden for row in journal):
        raise ValueError("forbidden managed workload operation in journal")
    if args.expected_state == "PASSED" and evidence["cleanup"].get("complete") is not True:
        raise ValueError("successful producer cleanup is incomplete")
    result = {
        "schema_version": "1.0",
        "classification": evidence["classification"],
        "commit": args.expected_sha,
        "producer_run_id": evidence["run_id"],
        "producer_run_attempt": evidence["run_attempt"],
        "producer_state": evidence["checks"]["state"],
        "producer_run_conclusion": conclusion,
        "producer_workflow_path": workflow_path,
        "run_binding_sha256": sha256(
            json.dumps(run_binding, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "artifact_id": args.artifact_id,
        "artifact_zip_sha256": args.artifact_zip_sha256,
        "journal_sha256": journal_sha256,
        "manifest_sha256": sha256((artifact / "manifest.json").read_bytes()).hexdigest(),
        "integrity": integrity,
        "safety": safety,
        "independently_accepted": True,
    }
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
