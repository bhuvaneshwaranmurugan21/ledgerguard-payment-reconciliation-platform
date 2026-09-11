from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import pytest

from tools.rehearse_part3_stage4_inspector import (
    execute,
    main,
    require_equal_acceptance,
    require_inventory_rejection,
)


def test_genuine_frozen_artifact_rehearsal_and_cli(tmp_path: Path) -> None:
    source = Path(os.environ["STAGE4_ACCEPTED_CI_ARTIFACT"])
    first = execute(source, tmp_path / "first")
    second = execute(source, tmp_path / "second")
    assert first == second
    assert first["genuine_artifact"]["member_count"] == 167
    assert len(first["negative_cases"]) == 2
    assert first["aws_execution"] is False
    with pytest.raises(ValueError, match="fresh output"):
        execute(source, tmp_path / "first")
    changed = deepcopy(first["genuine_artifact"])
    changed["head_sha"] = "0" * 40
    with pytest.raises(AssertionError, match="acceptance changed"):
        require_equal_acceptance(changed, first["genuine_artifact"])
    main(["--source", str(source), "--destination", str(tmp_path / "cli")])


def test_rehearsal_must_fail_if_rejection_disappears_or_has_wrong_cause() -> None:
    require_inventory_rejection("artifact member set differs")
    with pytest.raises(AssertionError, match="nested manifest accepted"):
        require_inventory_rejection(None)
    with pytest.raises(ValueError, match="unexpected inspection"):
        require_inventory_rejection("artifact head identity differs")
