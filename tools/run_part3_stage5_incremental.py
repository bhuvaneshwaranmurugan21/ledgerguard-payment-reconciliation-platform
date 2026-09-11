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
)


def command(argv: list[str], root: Path, output: Path, name: str) -> int:
    env = dict(
        os.environ,
        PYTHONPATH=str(root / "src") + os.pathsep + str(root),
        PYTHONDONTWRITEBYTECODE="1",
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


def run(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    tests = sorted(
        str(p.relative_to(root)) for p in (root / "tests").glob("test_part3_stage5_*.py")
    )
    if not tests:
        raise ValueError("Stage 5 tests missing")
    source = {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src/ledgerguard_control").glob("*.py"))
    }
    counts_by_run = []
    coverage_by_run = []
    mutations_by_run = []
    for number in (1, 2):
        trial = output / f"run-{number}"
        trial.mkdir()
        workspace = trial / "workspace"
        workspace.mkdir()
        for name in ("src", "tests", "spec", "contracts"):
            shutil.copytree(
                root / name,
                workspace / name,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
            )
        shutil.copy(root / "pyproject.toml", workspace / "pyproject.toml")
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
        for name, filename, before, after in MUTATIONS:
            path = workspace / "src/ledgerguard_control" / filename
            original = path.read_text()
            mutant = prepare_mutation(original, {"id": name, "before": before, "after": after})
            path.write_text(mutant)
            try:
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
                    workspace,
                    trial,
                    name,
                )
            finally:
                path.write_text(original)
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
        shutil.rmtree(workspace)
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
