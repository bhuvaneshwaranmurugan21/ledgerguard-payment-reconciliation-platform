#!/usr/bin/env python3
"""Bundle complete local evidence from the actual GitHub event checkout."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard_part3_stage1_evidence import build_manifest, envelope, verify_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    out = args.output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    local = cast(dict[str, Any], json.loads(args.local_evidence.read_text()))
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "show", "-s", "--format=%T", "HEAD"], text=True).strip()
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", "cb81704adcfdfac5d93879cd6c189fc2213bbe79", "HEAD"],
        check=True,
    )
    result = envelope(dict(os.environ), event, local, commit, tree)
    schema = json.loads((root / "contracts/part3/ci-evidence-v1.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    (out / "ci-evidence.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    shutil.copyfile(args.local_evidence, out / "local-evidence.json")
    for i in (1, 2):
        run = args.local_evidence.parent / f"run-{i}"
        destination = out / f"run-{i}"
        destination.mkdir()
        for name in (
            "result.json",
            "collection.json",
            "execution-selection.json",
            "pytest.xml",
            "coverage.json",
            "mutations.json",
        ):
            shutil.copyfile(run / name, destination / name)
        for path in sorted((run / "mutations").glob("*/pytest.xml")):
            target = destination / "mutations" / path.parent.name
            target.mkdir(parents=True)
            for name in ("pytest.xml", "stdout.log", "stderr.log"):
                shutil.copyfile(path.parent / name, target / name)
    sources = [
        "contracts/part2-part3-handoff-v1.json",
        "spec/part2-stage8-external-closure-freeze-v1.json",
        "spec/part2-master-conformance-addendum-v1.json",
        "spec/part3-requirements-v1.json",
        "spec/part3-source-index-v1.json",
        "spec/part3-master-gates-v1.json",
        "spec/part3-traceability-v1.json",
        "spec/part3-stage1-test-execution-v1.json",
        "spec/part3-stage1-code-mutations-v1.json",
        "spec/part3-stage1-coverage.ini",
        "spec/part3-stage1-gate-registry-v1.json",
        "spec/part3-stage1-scenario-traceability-v1.json",
        "docs/adr/0026-append-only-source-correction.md",
    ]
    for name in sources:
        target = out / "authority" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    manifest = build_manifest(out)
    verify_manifest(out, manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
