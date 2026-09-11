"""Reproducible incremental qualification, explicitly not Stage 5 acceptance.

Two fresh workspaces run the actual control modules. Source mutations must fail
assertions rather than imports/collection. Reuse the accepted JUnit verifier.
"""

from __future__ import annotations

import argparse
import json
import os
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
        "digest.hexdigest() != trusted_sha256",
        "False",
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
)


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


def run(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    tests = sorted(
        str(p.relative_to(root)) for p in (root / "tests").glob("test_part3_stage5_*.py")
    )
    if not tests:
        raise ValueError("Stage 5 tests missing")
    snapshot: dict[Path, bytes] = {}
    for directory in ("src", "tests", "spec", "contracts", "glue"):
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
            code = command(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    *tests,
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
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "tree": subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=root)
        ),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve())
