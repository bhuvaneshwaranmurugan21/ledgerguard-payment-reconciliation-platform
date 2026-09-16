from __future__ import annotations

import subprocess
from pathlib import Path

from tools import run_part3_stage6_mutations as runner


def test_each_mutation_starts_from_frozen_original(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "root"
    for name in (".github", "tools", "src", "tests", "spec", "contracts", "infra"):
        (root / name).mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='mutation-test'\n")
    source = root / "src" / "target.py"
    original = 'FIRST = "base"\nSECOND = "base"\n'
    source.write_text(original)
    rows = [
        {
            "id": "S6-M01-first",
            "path": "src/target.py",
            "before": 'FIRST = "base"',
            "after": 'FIRST = "mutant"',
            "test": "tests/test_target.py",
        },
        {
            "id": "S6-M02-second",
            "path": "src/target.py",
            "before": 'SECOND = "base"',
            "after": 'SECOND = "mutant"',
            "test": "tests/test_target.py",
        },
    ]
    monkeypatch.setattr(runner, "load_registry", lambda _: rows)
    observed: list[str] = []

    def execute(command, *, cwd, env, capture_output, text, timeout):
        del command, env, capture_output, text, timeout
        observed.append((cwd / "src" / "target.py").read_text())
        trial = tmp_path / "evidence" / rows[len(observed) - 1]["id"]
        (trial / "tests.xml").write_text(
            "<testsuites><testsuite><testcase><failure/></testcase></testsuite></testsuites>"
        )
        return subprocess.CompletedProcess([], 1, stdout="killed", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", execute)
    results = runner.run(root, tmp_path / "evidence")

    assert observed == [
        'FIRST = "mutant"\nSECOND = "base"\n',
        'FIRST = "base"\nSECOND = "mutant"\n',
    ]
    assert results[0]["source_sha256"] == results[1]["source_sha256"]
    assert all(row["killed"] is True for row in results)
