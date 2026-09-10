from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.run_part3_stage4_mutations import (
    REQUIRED_MUTATIONS,
    evaluate_test_result,
    load_registry,
    prepare_mutation,
    require_killed,
)

ROOT = Path(__file__).resolve().parents[1]


def test_registered_fault_identity_is_exact() -> None:
    assert tuple(row["id"] for row in load_registry(ROOT)) == REQUIRED_MUTATIONS


@pytest.mark.parametrize("change", ["rename", "reorder", "remove", "duplicate"])
def test_mutation_inventory_cannot_be_redefined(change: str, tmp_path: Path) -> None:
    data = json.loads((ROOT / "spec/part3-stage4-mutations-v1.json").read_text())
    rows = data["mutations"]
    if change == "rename":
        rows[0]["id"] = "unregistered-substitute"
    elif change == "reorder":
        rows[0], rows[1] = rows[1], rows[0]
    elif change == "remove":
        rows.pop()
    else:
        rows[-1] = rows[0]
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/part3-stage4-mutations-v1.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="inventory differs"):
        load_registry(tmp_path)


def test_mutations_must_change_one_actual_source_target() -> None:
    row = load_registry(ROOT)[0]
    original = (ROOT / row["path"]).read_text()
    assert prepare_mutation(original, row) != original
    with pytest.raises(ValueError, match="not unique"):
        prepare_mutation(original, dict(row, before="absent mutation target"))
    with pytest.raises(ValueError, match="not unique"):
        prepare_mutation(original + original, row)
    with pytest.raises(ValueError, match="does not alter"):
        prepare_mutation(original, dict(row, after=row["before"]))
    with pytest.raises(SyntaxError):
        prepare_mutation(original, dict(row, after="invalid @@@ syntax"))


@pytest.mark.parametrize(
    "code,name,expected",
    [
        (1, "killed-mutation.xml", True),
        (2, "killed-mutation.xml", False),
        (0, "passed-tests.xml", False),
        (1, "passed-tests.xml", False),
    ],
)
def test_kills_require_real_test_failures(code: int, name: str, expected: bool) -> None:
    path = ROOT / "tests/fixtures/part3-stage4-native-f23d77d" / name
    counts, killed = evaluate_test_result(code, path)
    assert killed is expected
    assert counts["tests"] > 0
    result = {"id": "observed-historical-result", "killed": killed}
    if expected:
        require_killed(result)
    else:
        with pytest.raises(ValueError, match="wrong reason"):
            require_killed(result)


@pytest.mark.parametrize("change", ["header", "error", "skip"])
def test_tampered_junit_or_wrong_failure_category_cannot_count_as_killed(
    change: str, tmp_path: Path
) -> None:
    source = ROOT / "tests/fixtures/part3-stage4-native-f23d77d/killed-mutation.xml"
    tree = ET.parse(source)
    suite = next(tree.getroot().iter("testsuite"))
    if change == "header":
        suite.set("failures", "100")
    else:
        category = "error" if change == "error" else "skipped"
        suite.set("errors" if change == "error" else "skipped", "1")
        ET.SubElement(next(tree.getroot().iter("testcase")), category)
    path = tmp_path / "adversarial.xml"
    tree.write(path)
    if change == "header":
        with pytest.raises(ValueError, match="actual cases"):
            evaluate_test_result(1, path)
    else:
        assert evaluate_test_result(1, path)[1] is False
