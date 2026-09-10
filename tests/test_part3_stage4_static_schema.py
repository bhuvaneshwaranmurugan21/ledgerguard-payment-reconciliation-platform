from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from tools.run_part3_stage4_static import build_commands, prepare_schema_context

ROOT = Path(__file__).resolve().parents[1]


def test_native_command_graph_retains_every_gate_and_has_no_aws_mutation(tmp_path: Path) -> None:
    commands = build_commands(ROOT, tmp_path / "evidence", tmp_path / "schema")
    assert set(commands) == {
        "terraform-version",
        "terraform-format",
        "terraform-initialize",
        "terraform-validate",
        "terraform-schema-initialize",
        "terraform-schema",
        "tflint-version",
        "tflint",
        "handoff",
        "tests",
        "python-lint",
        "python-types",
        "controls-tests",
        "controls-coverage-combine",
        "controls-coverage",
        "controls-coverage-json",
        "controls-lint",
        "controls-types",
        "controls-mutations",
        "inspector-rehearsal",
        "security-raw-scan",
        "security-applicability",
    }
    for name in ("terraform-initialize", "terraform-schema-initialize"):
        assert "-backend=false" in commands[name]
        assert "-lockfile=readonly" in commands[name]
    assert "--fail-under=100" in commands["controls-coverage"]
    assert "--rcfile=spec/part3-stage4-coverage.ini" in commands["controls-tests"]
    assert commands["terraform-schema"][1] == "-chdir=" + str(tmp_path / "schema")
    assert not {"apply", "plan", "destroy", "aws"}.intersection(
        token for c in commands.values() for token in c
    )


def test_schema_context_preserves_exact_lock_and_workload_backend(tmp_path: Path) -> None:
    lock = ROOT / "infra/part3/.terraform.lock.hcl"
    raw = lock.read_bytes()
    workload = (ROOT / "infra/part3/versions.tf").read_bytes()
    target = tmp_path / "schema"
    binding = prepare_schema_context(lock, target)
    assert (target / ".terraform.lock.hcl").read_bytes() == raw
    assert (
        binding["workload_lock_sha256"] == binding["schema_lock_sha256"] == sha256(raw).hexdigest()
    )
    configuration = json.loads((target / "main.tf.json").read_text())
    assert set(configuration) == {"terraform"}
    assert set(configuration["terraform"]) == {"required_version", "required_providers"}
    assert configuration["terraform"]["required_providers"]["aws"] == {
        "source": "hashicorp/aws",
        "version": "= 6.11.0",
    }
    assert (ROOT / "infra/part3/versions.tf").read_bytes() == workload
    assert b'backend "s3" {}' in workload
    assert lock.read_bytes() == raw


@pytest.mark.parametrize("old,new", [("6.11.0", "6.12.0"), ("hashicorp/aws", "other/aws")])
def test_schema_context_rejects_provider_substitution(tmp_path: Path, old: str, new: str) -> None:
    lock = tmp_path / "changed.lock"
    lock.write_text((ROOT / "infra/part3/.terraform.lock.hcl").read_text().replace(old, new))
    target = tmp_path / "schema"
    with pytest.raises(ValueError, match="lock identity"):
        prepare_schema_context(lock, target)
    assert not target.exists()


def test_schema_context_refuses_reusing_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        prepare_schema_context(ROOT / "infra/part3/.terraform.lock.hcl", tmp_path)
