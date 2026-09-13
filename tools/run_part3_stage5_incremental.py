"""Reproducible incremental qualification, explicitly not Stage 5 acceptance.

Two fresh workspaces run the actual control modules. Source mutations must fail
assertions rather than imports/collection. Reuse the accepted JUnit verifier.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from tools.run_part3_stage4_mutations import evaluate_test_result, prepare_mutation, require_killed

MUTATIONS = (
    ("release-pin", "admission.py", "sha256(raw).hexdigest() != trusted_sha256", "False"),
    (
        "release-artifact",
        "admission.py",
        'sha256(artifacts[name]).hexdigest() != value["runtime"][field]',
        "False",
    ),
    ("registered-input", "admission.py", "arguments != registered_input", "False"),
    ("qualified-runtime", "admission.py", 'value["runtime"] != release.runtime()', "False"),
    ("duplicate-json", "contracts.py", "if key in result:", "if False:"),
    ("decimal-bound", "contracts.py", "[0-9]{0,37}", "[0-9]{0,38}"),
    ("glue-config", "glue_arguments.py", "values[name] != expected", "False"),
    ("marker-canonical", "candidates.py", 'raw != canonical_bytes(value) + b"\\n"', "False"),
    ("candidate-hash", "candidates.py", 'reference["sha256"] != row["sha256"]', "False"),
    ("version-stability", "objects.py", "snapshot(store, prefix) != before", "False"),
    ("version-identity", "aws_objects.py", 'response.get("VersionId") != version_id', "False"),
    ("truncated-stream", "aws_objects.py", "size != length", "False"),
    ("run-identity", "authority.py", "row[0] != identity or row[2] != namespace", "False"),
    ("attempt-owner-fence", "authority.py", "if row != expected:", "if False:"),
    (
        "namespace-cas",
        "authority.py",
        "(None if root is None else root[0]) != predecessor",
        "False",
    ),
    ("terminal-authority", "authority.py", 'run != ("COMMITTED", digest)', "False"),
    (
        "early-transaction-commit",
        "authority.py",
        'fault("before_run_terminal")',
        'connection.commit(); fault("before_run_terminal")',
    ),
    (
        "read-integrity",
        "authority.py",
        'canonical_digest(value) != digest or value.get("namespace") != namespace',
        "False",
    ),
    ("immutable-body", "objects.py", "bytes(rows[0][2]) != raw", "False"),
    ("snapshot-body", "publication.py", "sha256(raw).hexdigest() != digest", "False"),
    ("snapshot-head", "publication.py", 'store.read_head() != root["financial_head"]', "False"),
    ("snapshot-offset", "publication.py", 'entry["offset"] != offset', "False"),
    ("snapshot-order", "publication.py", "name < previous", "False"),
    (
        "financial-expected-pin",
        "financial_rows.py",
        "digest.hexdigest() != trusted_expected_sha256",
        "False",
    ),
    (
        "financial-family-inventory",
        "financial_rows.py",
        "member_families != expected_families",
        "False",
    ),
    (
        "financial-delta",
        "financial_rows.py",
        "amounts[name] != amount",
        "False",
    ),
    (
        "financial-key",
        "financial_rows.py",
        "row[\"reconciliation_key\"] != expected_key",
        "False",
    ),
    (
        "financial-post-read-identity",
        "financial_rows.py",
        'if _hash_file(member.path) != (member.size_bytes, member.sha256):\n'
        '        raise ControlRejected("Parquet changed during read")',
        "if False:\n        raise ControlRejected(\"Parquet changed during read\")",
    ),
    (
        "athena-expectation-pin",
        "athena.py",
        'if digest.hexdigest() != trusted_sha256:\n'
        '        raise ControlRejected("Athena expectation digest differs")',
        'if False:\n        raise ControlRejected("Athena expectation digest differs")',
    ),
    (
        "athena-scan-bound",
        "athena.py",
        "execution.scanned_bytes <= SCAN_LIMIT_BYTES",
        "execution.scanned_bytes <= SCAN_LIMIT_BYTES + 1",
    ),
    (
        "athena-pagination-chain",
        "athena.py",
        "page.request_token != expected_token",
        "False",
    ),
    (
        "athena-exact-rows",
        "athena.py",
        "rows != list(expected)",
        "False",
    ),
    (
        "athena-partition-confinement",
        "athena.py",
        'f" WHERE run_id = \'{run_id}\' AND attempt_id = \'{attempt_id}\'"',
        'f" WHERE run_id = \'{run_id}\'"',
    ),
    (
        "candidate-glue-run-binding",
        "candidates.py",
        'or completion["glue_job_run_id"] != manifest["glue_job_run_id"]',
        "or False",
    ),
    (
        "glue-terminal-state",
        "glue_run.py",
        'run.get("JobRunState") != "SUCCEEDED"',
        "False",
    ),
    (
        "glue-start-arguments",
        "glue_run.py",
        '_arguments(run.get("Arguments")) != expected_arguments',
        "False",
    ),
    (
        "glue-effective-config",
        "glue_run.py",
        "run.get(name) != expected",
        "False",
    ),
    (
        "glue-recovery-unique",
        "glue_run.py",
        "len(matches) != 1",
        "False",
    ),
    (
        "glue-release-shape",
        "glue_arguments.py",
        "pattern.fullmatch(value) is None",
        "False",
    ),
    (
        "glue-business-completeness",
        "glue_arguments.py",
        "if not business.issubset(values):",
        "if False:",
    ),
    (
        "successor-bucket-binding",
        "successor_job.py",
        "_BUCKET.fullmatch(admitted.workload_bucket)",
        're.fullmatch(r"ledgerguard-(.*)", admitted.workload_bucket)',
    ),
    (
        "successor-marker-job-run",
        "successor_writer.py",
        "_JOB_RUN.fullmatch(glue_job_run_id) is None",
        "False",
    ),
    (
        "athena-aws-execution-identity",
        "athena_aws.py",
        'raw.get("QueryExecutionId") != query_execution_id',
        "False",
    ),
    (
        "athena-aws-pagination-token",
        "athena_aws.py",
        "not next_token or next_token in seen",
        "False",
    ),
    (
        "athena-proof-family-binding",
        "athena_aws.py",
        "family != query.family",
        "False",
    ),
    (
        "athena-proof-sql-binding",
        "athena_aws.py",
        'verification.get("sql_sha256") != query.sha256',
        "False",
    ),
    (
        "athena-proof-scan-binding",
        "athena_aws.py",
        'verification.get("scanned_bytes") != execution.scanned_bytes',
        "False",
    ),
    (
        "athena-proof-time-binding",
        "athena_aws.py",
        'verification.get("execution_ms") != execution.execution_ms',
        "False",
    ),
    (
        "athena-proof-execution-sql-binding",
        "athena_aws.py",
        "sha256(execution.sql.encode()).hexdigest() != query.sha256",
        "False",
    ),
    (
        "athena-proof-output-binding",
        "athena_aws.py",
        'execution.output_location != result.get("uri")',
        "False",
    ),
    (
        "athena-proof-account-binding",
        "athena_aws.py",
        "execution.expected_bucket_owner != account_id",
        "False",
    ),
    (
        "athena-proof-encryption-binding",
        "athena_aws.py",
        'execution.encryption_option != "SSE_S3"',
        "False",
    ),
    (
        "athena-proof-retention-prefix",
        "athena_aws.py",
        'f"s3://{bucket}/publications/query-proofs/{identity[\'run_id\']}/"',
        'f"s3://{bucket}/runs/query-proofs/{identity[\'run_id\']}/"',
    ),
    (
        "immutable-publication-prefix",
        "aws_objects.py",
        'or not key.startswith("publications/")',
        "or False",
    ),
    (
        "immutable-conditional-create",
        "aws_objects.py",
        'IfNoneMatch="*",',
        'IfNoneMatch="changed",',
    ),
    (
        "immutable-readback-body",
        "aws_objects.py",
        "self.read(uri, history[0].version_id) != raw",
        "False",
    ),
    (
        "dynamodb-registration-identity",
        "aws_authority.py",
        'or self._s(item, "identity") != identity',
        "or False",
    ),
    (
        "dynamodb-active-fence",
        "aws_authority.py",
        'or self._n(run, "fence") != attempt.fence',
        "or False",
    ),
    (
        "dynamodb-terminal-authority",
        "aws_authority.py",
        'self._s(run, "status") != "COMMITTED" or self._s(run, "commit") != digest',
        "False",
    ),
    (
        "dynamodb-reachable-identity",
        "aws_authority.py",
        'identity is not None and value.get("identity_sha256") != identity',
        "False",
    ),
    (
        "workflow-target-account",
        "workflow.py",
        'ACCOUNT_ID = "857229544428"',
        'ACCOUNT_ID = "857229544429"',
    ),
    (
        "workflow-success-bypass",
        "workflow.py",
        'states["ValidateCandidate"]["Next"] = "RunTransactionsQuery"',
        'states["ValidateCandidate"]["Next"] = "PreparePublication"',
    ),
    (
        "workflow-retry-bound",
        "workflow.py",
        '"MaxAttempts": 3,',
        '"MaxAttempts": 4,',
    ),
    (
        "workflow-failure-ownership",
        "workflow.py",
        'return {"Type": "Pass", "Parameters": parameters, "Next": "RecordFailure"}',
        'return {"Type": "Pass", "Parameters": parameters, "Next": "WorkflowFailed"}',
    ),
    (
        "handler-config-digest",
        "execution.py",
        "sha256(raw).hexdigest() != trusted_sha256",
        "False",
    ),
    (
        "handler-execution-input-binding",
        "execution.py",
        'state != {"execution_input_sha256": config.execution_input["sha256"]}',
        "False",
    ),
    (
        "handler-operation-bucket-binding",
        "execution.py",
        "arguments.workload_bucket != config.bucket",
        "False",
    ),
    (
        "handler-query-token-family-binding",
        "execution.py",
        '{"identity": identity, "family": family}',
        '{"identity": identity}',
    ),
    (
        "handler-committed-replay",
        "execution.py",
        "if committed is not None:",
        "if False:",
    ),
    (
        "handler-registered-namespace",
        "execution.py",
        'control["namespace"] = namespace',
        'control["namespace"] = "wrong-namespace"',
    ),
    (
        "handler-replay-cannot-admit",
        "execution.py",
        'if control.get("replay_committed") is not False or "committed_sha256" in control:',
        "if False:",
    ),
    (
        "expected-summary-input-digest",
        "athena.py",
        'if digest.hexdigest() != trusted_sha256:\n'
        '        raise ControlRejected("financial expectation digest differs")',
        'if False:\n        raise ControlRejected("financial expectation digest differs")',
    ),
    (
        "expected-summary-family-confinement",
        "athena.py",
        "if row_family != evidence_family:",
        "if False:",
    ),
    (
        "handler-runtime-bucket-binding",
        "runtime.py",
        'values.get("WORKLOAD_BUCKET") != config.bucket',
        "False",
    ),
    (
        "handler-runtime-table-binding",
        "runtime.py",
        'values.get("CONTROL_TABLE") != config.table',
        "False",
    ),
    (
        "handler-runtime-region-binding",
        "runtime.py",
        "region_name=REGION",
        'region_name="us-east-1"',
    ),
    (
        "validator-candidate-action-dispatch",
        "validator.py",
        '"validate-candidate",',
        '"wrong-candidate",',
    ),
    (
        "controller-attempt-action-dispatch",
        "controller.py",
        '"admit-attempt",',
        '"wrong-attempt",',
    ),
    (
        "workflow-attempt-admission-order",
        "workflow.py",
        '"Default": "AdmitAttempt",',
        '"Default": "StartGlue",',
    ),
    (
        "candidate-physical-size-bound",
        "candidates.py",
        'sum(row["size_bytes"] for row in rows) > MAX_CANDIDATE_BYTES',
        "False",
    ),
    (
        "candidate-attempt-binding",
        "candidate_validation.py",
        'any(value.get(name) != item for name, item in expected.items())',
        "False",
    ),
    (
        "candidate-state-readmission",
        "candidate_validation.py",
        'any(control.get(name) != item for name, item in initial.items())',
        "False",
    ),
    (
        "candidate-managed-glue-result",
        "candidate_validation.py",
        'set(glue) != {"JobRunId"}',
        "False",
    ),
    (
        "candidate-materialized-digest",
        "candidate_validation.py",
        'digest.hexdigest() != reference["sha256"]',
        "False",
    ),
    (
        "candidate-post-comparison-stability",
        "candidate_validation.py",
        "assert_unchanged(objects, arguments.candidate_output_prefix, candidate.versions)",
        "None",
    ),
    (
        "candidate-receipt-retention-prefix",
        "candidate_validation.py",
        'f"s3://{bucket}/publications/validation-receipts/{suffix}/{digest}.json"',
        'f"s3://{bucket}/runs/validation-receipts/{suffix}/{digest}.json"',
    ),
    (
        "query-state-readmission",
        "query_validation.py",
        "if set(control) != allowed or any(\n"
        "        control.get(name) != value for name, value in initial.items()\n"
        "    ):",
        "if False:",
    ),
    (
        "query-validation-receipt-binding",
        "query_validation.py",
        "any(receipt.get(name) != value for name, value in expected_receipt.items())",
        "False",
    ),
    (
        "query-managed-order",
        "query_validation.py",
        "set(athena) != set(completed)",
        "False",
    ),
    (
        "query-candidate-version-binding",
        "query_validation.py",
        'inventory_digest != receipt["version_inventory_sha256"]',
        "False",
    ),
    (
        "query-result-object-address",
        "query_validation.py",
        "output_location != expected_uri",
        "False",
    ),
    (
        "query-post-observation-stability",
        "query_validation.py",
        "after_digest != inventory_digest",
        "False",
    ),
    (
        "validator-query-action-dispatch",
        "validator.py",
        'query_actions = {f"validate-{family}-query" for family in FAMILIES}',
        "query_actions = set()",
    ),
    (
        "failure-state-readmission",
        "failure.py",
        "control.get(name) != value for name, value in initial.items()",
        "False for name, value in initial.items()",
    ),
    (
        "failure-retention-prefix",
        "failure.py",
        'f"s3://{config.bucket}/publications/failure-records/{attempt.run_id}/"',
        'f"s3://{config.bucket}/runs/failure-records/{attempt.run_id}/"',
    ),
    (
        "failure-managed-athena-order",
        "failure.py",
        "set(athena) != set(expected)",
        "False",
    ),
    (
        "controller-failure-action-dispatch",
        "controller.py",
        '"record-failure",',
        '"wrong-failure",',
    ),
)

MUTATION_TEST_PRIORITY = {
    "admission.py": "tests/test_part3_stage5_admission.py",
    "athena.py": "tests/test_part3_stage5_athena.py",
    "athena_aws.py": "tests/test_part3_stage5_athena_aws.py",
    "authority.py": "tests/test_part3_stage5_authority.py",
    "aws_authority.py": "tests/test_part3_stage5_aws_authority.py",
    "aws_objects.py": "tests/test_part3_stage5_aws_objects.py",
    "candidate_validation.py": "tests/test_part3_stage5_candidate_validation.py",
    "candidates.py": "tests/test_part3_stage5_candidates.py",
    "contracts.py": "tests/test_part3_stage5_admission.py",
    "controller.py": "tests/test_part3_stage5_handlers.py",
    "execution.py": "tests/test_part3_stage5_execution.py",
    "financial_rows.py": "tests/test_part3_stage5_financial_rows.py",
    "failure.py": "tests/test_part3_stage5_failure.py",
    "glue_arguments.py": "tests/test_part3_stage5_admission.py",
    "glue_run.py": "tests/test_part3_stage5_glue_run.py",
    "objects.py": "tests/test_part3_stage5_candidates.py",
    "publication.py": "tests/test_part3_stage5_publication.py",
    "query_validation.py": "tests/test_part3_stage5_query_validation.py",
    "runtime.py": "tests/test_part3_stage5_handlers.py",
    "successor_job.py": "tests/test_part3_stage5_successor.py",
    "successor_writer.py": "tests/test_part3_stage5_successor.py",
    "validator.py": "tests/test_part3_stage5_handlers.py",
    "workflow.py": "tests/test_part3_stage5_workflow.py",
}


def mutation_test_order(filename: str, tests: list[str]) -> list[str]:
    """Run the detecting file first while retaining the complete test inventory."""
    preferred = MUTATION_TEST_PRIORITY.get(filename)
    if preferred is None or preferred not in tests:
        raise ValueError(f"mutation test priority is missing for {filename}")
    ordered = [preferred, *(test for test in tests if test != preferred)]
    if len(ordered) != len(tests) or set(ordered) != set(tests):
        raise ValueError("mutation test ordering changed the test inventory")
    return ordered


def command(argv: list[str], root: Path, output: Path, name: str) -> int:
    env = dict(
        os.environ,
        PYTHONPATH=str(root / "src") + os.pathsep + str(root),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONHASHSEED="0",
        PYTHONNOUSERSITE="1",
    )
    completed = subprocess.run(
        argv,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    (output / f"{name}.stdout.log").write_text(completed.stdout)
    (output / f"{name}.stderr.log").write_text(completed.stderr)
    return completed.returncode


def populate_workspace(workspace: Path, snapshot: dict[Path, bytes]) -> None:
    workspace.mkdir()
    for relative, raw in snapshot.items():
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)


def _source_metadata(
    root: Path, base_commit: str | None, base_tree: str | None
) -> tuple[str, str, bool]:
    if (base_commit is None) != (base_tree is None):
        raise ValueError("base commit and tree must be supplied together")
    if base_commit is not None and base_tree is not None:
        if any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in (base_commit, base_tree)):
            raise ValueError("base commit and tree must be lowercase full object IDs")
        return base_commit, base_tree, True
    return (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True
        ).strip(),
        bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root)),
    )


def run(
    root: Path,
    output: Path,
    base_commit: str | None = None,
    base_tree: str | None = None,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    tests = sorted(
        str(p.relative_to(root)) for p in (root / "tests").glob("test_part3_stage5_*.py")
    )
    if not tests:
        raise ValueError("Stage 5 tests missing")
    snapshot: dict[Path, bytes] = {}
    for directory in ("src", "tests", "spec", "contracts", "glue", "tools"):
        for path in sorted((root / directory).rglob("*")):
            relative = path.relative_to(root)
            if path.is_symlink():
                raise ValueError("qualification input contains a symbolic link")
            if path.is_file() and not {"__pycache__", ".pytest_cache"} & set(relative.parts):
                snapshot[relative] = path.read_bytes()
    snapshot[Path("pyproject.toml")] = (root / "pyproject.toml").read_bytes()
    source = {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src/ledgerguard_control").glob("*.py"))
    }
    captured_source = {
        str(path): sha256(raw).hexdigest()
        for path, raw in snapshot.items()
        if path.parent == Path("src/ledgerguard_control") and path.suffix == ".py"
    }
    if captured_source != source:
        raise ValueError("captured control source inventory differs")
    counts_by_run = []
    coverage_by_run = []
    mutations_by_run = []
    for number in (1, 2):
        trial = output / f"run-{number}"
        trial.mkdir()
        workspace = trial / "workspace"
        populate_workspace(workspace, snapshot)
        code = command(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--rcfile=spec/part3-stage5-incremental-coverage.ini",
                "-m",
                "pytest",
                *tests,
                "--junitxml=" + str(trial / "tests.xml"),
            ],
            workspace,
            trial,
            "baseline",
        )
        counts, _ = evaluate_test_result(code, trial / "tests.xml")
        if (
            code != 0
            or counts["tests"] == 0
            or any(counts[k] for k in ("failures", "errors", "skipped"))
        ):
            raise ValueError("baseline tests did not all pass")
        counts_by_run.append(counts)
        code = command(
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                "--rcfile=spec/part3-stage5-incremental-coverage.ini",
                "-o",
                str(trial / "coverage.json"),
            ],
            workspace,
            trial,
            "coverage",
        )
        coverage = json.loads((trial / "coverage.json").read_text())
        if code or set(coverage["files"]) != set(source):
            raise ValueError("coverage gate or complete source inventory failed")
        totals = coverage["totals"]
        if any(totals[k] for k in ("missing_lines", "missing_branches", "excluded_lines")):
            raise ValueError("critical coverage is incomplete or excluded")
        coverage_by_run.append(totals)
        results = []
        shutil.rmtree(workspace)
        for index, (name, filename, before, after) in enumerate(MUTATIONS):
            mutation_workspace = trial / f"mutation-{index:02d}"
            populate_workspace(mutation_workspace, snapshot)
            path = mutation_workspace / "src/ledgerguard_control" / filename
            original = path.read_text()
            mutant = prepare_mutation(original, {"id": name, "before": before, "after": after})
            path.write_text(mutant)
            mutation_tests = mutation_test_order(filename, tests)
            code = command(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    *mutation_tests,
                    "--maxfail=1",
                    "--tb=short",
                    "--junitxml=" + str(trial / f"{name}.xml"),
                ],
                mutation_workspace,
                trial,
                name,
            )
            shutil.rmtree(mutation_workspace)
            counts, killed = evaluate_test_result(code, trial / f"{name}.xml")
            result = {
                "id": name,
                "counts": counts,
                "killed": killed,
                "exit_code": code,
                "source_sha256": sha256(original.encode()).hexdigest(),
                "mutant_sha256": sha256(mutant.encode()).hexdigest(),
            }
            results.append(result)
            (trial / "mutations.json").write_text(json.dumps(results, indent=2) + "\n")
            require_killed(result)
        mutations_by_run.append(results)
    if counts_by_run[0] != counts_by_run[1] or coverage_by_run[0] != coverage_by_run[1]:
        raise ValueError("clean-run qualification differs")
    if mutations_by_run[0] != mutations_by_run[1]:
        raise ValueError("clean-run mutation results differ")
    commit, tree, working_tree_dirty = _source_metadata(root, base_commit, base_tree)
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "claim": "STAGE5_INCREMENT_LOCAL_VERIFIED",
        "stage5_complete": False,
        "aws_calls": 0,
        "source_files": source,
        "tests": counts_by_run[0],
        "coverage": coverage_by_run[0],
        "mutations_killed": len(MUTATIONS),
        "clean_runs": 2,
        "commit": commit,
        "tree": tree,
        "working_tree_dirty": working_tree_dirty,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-commit")
    parser.add_argument("--base-tree")
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve(), args.base_commit, args.base_tree)
