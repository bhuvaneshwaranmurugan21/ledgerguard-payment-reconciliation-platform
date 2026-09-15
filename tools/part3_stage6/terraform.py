"""Exact Terraform command construction for the Stage 6 plan-only controller."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TERRAFORM_VERSION = "1.13.1"
FORBIDDEN = {"apply", "force-unlock", "import", "-target", "-refresh=false", "-lock=false"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def terraform_variables(
    release: dict[str, Any], release_dir: Path, *, operation_id: str, expires_at: str
) -> dict[str, Any]:
    if operation_id != "release-qual1":
        raise ValueError("Stage 6 operation identity differs")
    if (
        re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", expires_at)
        is None
    ):
        raise ValueError("Stage 6 expiry must be canonical UTC")
    value = dict(release)
    if value.get("schema_version") != "ledgerguard.stage5-terraform-release.v1":
        raise ValueError("Stage 5 Terraform release schema differs")
    value.pop("schema_version")
    for archive_field in ("validator_zip", "controller_zip"):
        raw = value.get(archive_field)
        if not isinstance(raw, str) or Path(raw).name != raw:
            raise ValueError(f"unsafe release archive path: {archive_field}")
        path = (release_dir / raw).resolve()
        if release_dir.resolve() not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"release archive missing or unsafe: {archive_field}")
        value[archive_field] = str(path)
    return {
        "operation_id": operation_id,
        "expires_at": expires_at,
        "permissions_boundary_arns": {
            role: f"arn:aws:iam::857229544428:policy/LedgerGuardPart3-{role}-Boundary-v1"
            for role in ("glue", "workflow", "validator", "controller")
        },
        "stage5_release": value,
    }


def backend_arguments(*, kms_key_arn: str, operation_id: str) -> list[str]:
    if operation_id != "release-qual1":
        raise ValueError("Stage 6 backend operation identity differs")
    if (
        re.fullmatch(
            r"arn:aws:kms:ap-southeast-2:857229544428:key/(?:[0-9a-f-]{36}|mrk-[0-9a-f]{32})",
            kms_key_arn,
        )
        is None
    ):
        raise ValueError("exact backend KMS key ARN required")
    return [
        "-backend-config=bucket=ledgerguard-tfstate-857229544428-ap-southeast-2",
        "-backend-config=key=ledgerguard/terraform/part3/platform/release-qual1/terraform.tfstate",
        "-backend-config=region=ap-southeast-2",
        "-backend-config=encrypt=true",
        f"-backend-config=kms_key_id={kms_key_arn}",
        "-backend-config=use_lockfile=true",
    ]


def validate_command(command: list[str], *, plan_path: Path | None = None) -> str:
    if not command or command[0] != "terraform":
        raise ValueError("only Terraform commands are accepted")
    lowered = [token.lower() for token in command]
    joined = " ".join(lowered)
    if any(term in joined for term in FORBIDDEN):
        raise ValueError("prohibited Terraform argument")
    if len(command) < 2 or command[1] not in {"version", "init", "validate", "plan", "show"}:
        raise ValueError("Terraform subcommand is not Stage 6 allowlisted")
    if command[1] == "init":
        required_init = {"-input=false", "-reconfigure", "-lockfile=readonly"}
        if not required_init.issubset(command):
            raise ValueError("Terraform init safety arguments are incomplete")
    if command[1] == "plan":
        required = {"-input=false", "-lock=true", "-refresh=true", "-detailed-exitcode"}
        if not required.issubset(command):
            raise ValueError("Terraform plan safety arguments are incomplete")
        outputs = [token for token in command if token.startswith("-out=")]
        if plan_path is None or outputs != [f"-out={plan_path}"]:
            raise ValueError("Terraform saved binary plan binding differs")
    if command[1] == "show":
        if plan_path is None or command != ["terraform", "show", "-json", str(plan_path)]:
            raise ValueError("Terraform JSON must come from the saved binary plan")
    return command[1]


Run = Callable[[list[str], Path], subprocess.CompletedProcess[bytes]]


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=cwd, capture_output=True, check=False)


@dataclass
class PlanSession:
    infra_dir: Path
    work_dir: Path
    run: Run = _run
    journal: list[dict[str, Any]] = field(default_factory=list)

    def _invoke(
        self,
        command: list[str],
        *,
        plan_path: Path | None = None,
        allowed_codes: frozenset[int] = frozenset({0}),
    ) -> bytes:
        operation = validate_command(command, plan_path=plan_path)
        result = self.run(command, self.infra_dir)
        self.journal.append(
            {
                "sequence": len(self.journal) + 1,
                "operation": f"terraform-{operation}",
                "command": ["terraform", operation],
                "exit_code": result.returncode,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            }
        )
        if result.returncode not in allowed_codes:
            raise RuntimeError(f"Terraform {operation} failed with exit code {result.returncode}")
        return result.stdout

    def execute(
        self,
        *,
        variables: dict[str, Any],
        backend: list[str],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if self.infra_dir.is_symlink() or not self.infra_dir.is_dir():
            raise ValueError("regular Terraform source directory required")
        if self.work_dir.exists() or self.work_dir.is_symlink():
            raise ValueError("new private Terraform work directory required")
        self.work_dir.mkdir(parents=True, mode=0o700)
        plan_path = self.work_dir / "stage6.tfplan"
        json_path = self.work_dir / "plan.json"
        variables_path = self.work_dir / "stage6.auto.tfvars.json"
        variables_path.write_bytes(_canonical(variables))
        version_raw = self._invoke(["terraform", "version", "-json"])
        version = json.loads(version_raw)
        if version.get("terraform_version") != TERRAFORM_VERSION:
            raise ValueError("Terraform version differs")
        self._invoke(
            [
                "terraform",
                "init",
                "-input=false",
                "-reconfigure",
                "-lockfile=readonly",
                *backend,
            ]
        )
        validation = json.loads(self._invoke(["terraform", "validate", "-json"]))
        if validation.get("valid") is not True or validation.get("error_count") != 0:
            raise ValueError("Terraform validation failed")
        self._invoke(
            [
                "terraform",
                "plan",
                "-input=false",
                "-lock=true",
                "-lock-timeout=60s",
                "-refresh=true",
                "-detailed-exitcode",
                f"-out={plan_path}",
                f"-var-file={variables_path}",
            ],
            plan_path=plan_path,
            allowed_codes=frozenset({2}),
        )
        if not plan_path.is_file() or plan_path.is_symlink():
            raise ValueError("Terraform did not create a regular saved plan")
        plan_bytes = plan_path.read_bytes()
        plan_json_bytes = self._invoke(
            ["terraform", "show", "-json", str(plan_path)], plan_path=plan_path
        )
        json_path.write_bytes(plan_json_bytes)
        plan = json.loads(plan_json_bytes)
        if not isinstance(plan, dict):
            raise ValueError("Terraform saved plan JSON must be an object")
        digests = {
            "binary_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "json_sha256": hashlib.sha256(plan_json_bytes).hexdigest(),
            "variable_sha256": hashlib.sha256(variables_path.read_bytes()).hexdigest(),
        }
        return plan, digests
