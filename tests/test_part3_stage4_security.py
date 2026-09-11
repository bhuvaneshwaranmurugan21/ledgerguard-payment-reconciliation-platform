from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools.part3_stage4.security import assess

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / "evidence/part3-stage4/local/trivy-after-tracing.json").read_bytes()


def test_actual_scan_has_exact_scoped_review_without_hiding_failures() -> None:
    result = assess(ROOT, RAW)
    assert result["raw_scanner_successes"] == 65
    assert result["raw_scanner_failures"] == 4
    assert result["unreviewed_failures"] == 0
    assert result["scanner_itself_all_green"] is False
    assert result["aws_controls_verified"] is False
    assert result["production_security_claim"] is False


@pytest.fixture
def copied(tmp_path: Path) -> Path:
    shutil.copytree(
        ROOT / "infra/part3", tmp_path / "infra/part3", ignore=shutil.ignore_patterns(".terraform")
    )
    (tmp_path / "spec").mkdir()
    for name in ("security-review", "resource-controls"):
        shutil.copy(ROOT / f"spec/part3-stage4-{name}-v1.json", tmp_path / "spec")
    shutil.copy(ROOT / "spec/part3-requirements-v1.json", tmp_path / "spec")
    return tmp_path


def test_source_change_invalidates_review(copied: Path) -> None:
    path = copied / "infra/part3/compute.tf"
    path.write_text(path.read_text() + "\n# changed source\n")
    with pytest.raises(ValueError, match="source changed"):
        assess(copied, RAW)


@pytest.mark.parametrize("fault", ["scope", "absolute", "traversal", "symlink", "duplicate"])
def test_review_scope_paths_and_duplicates_fail(copied: Path, fault: str) -> None:
    path = copied / "spec/part3-stage4-security-review-v1.json"
    review = json.loads(path.read_text())
    if fault == "scope":
        review["scope"] = "PRODUCTION"
    if fault == "absolute":
        review["source_hashes"]["/etc/passwd"] = "0" * 64
    if fault == "traversal":
        review["source_hashes"]["../escape"] = "0" * 64
    if fault == "duplicate":
        review["decisions"].append(review["decisions"][0])
    if fault == "symlink":
        source = copied / "infra/part3/compute.tf"
        source.unlink()
        source.symlink_to(ROOT / "infra/part3/compute.tf")
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError):
        assess(copied, RAW)


@pytest.mark.parametrize("fault", ["unreviewed", "missing", "status", "summary", "no-success"])
def test_incomplete_or_new_findings_do_not_inherit_an_exception(fault: str) -> None:
    scan: dict[str, Any] = json.loads(RAW)
    if fault == "unreviewed":
        scan["Results"][-1]["Misconfigurations"][0]["ID"] = "NEW-UNREVIEWED"
    if fault == "missing":
        scan["Results"].pop()
    if fault == "status":
        scan["Results"][0]["Misconfigurations"][0]["Status"] = "SKIPPED"
    if fault == "summary":
        scan["Results"][0]["MisconfSummary"]["Successes"] += 1
    if fault == "no-success":
        scan["Results"].pop(0)
    with pytest.raises(ValueError):
        assess(ROOT, json.dumps(scan).encode())
