from __future__ import annotations

from pathlib import Path

import pytest

from ledgerguard.part1 import (
    Part1CompletionError,
    _load_preserved_json,
)
from ledgerguard.part1 import (
    _list as part1_list,
)
from ledgerguard.part1 import (
    _load as part1_load,
)
from ledgerguard.part1 import (
    _mapping as part1_mapping,
)
from ledgerguard.stage0 import (
    Stage0Error,
)
from ledgerguard.stage0 import (
    _load as stage0_load,
)
from ledgerguard.stage0 import (
    _mapping as stage0_mapping,
)
from ledgerguard.stage1 import (
    Stage1Error,
)
from ledgerguard.stage1 import (
    _list as stage1_list,
)
from ledgerguard.stage1 import (
    _load as stage1_load,
)
from ledgerguard.stage1 import (
    _mapping as stage1_mapping,
)


@pytest.mark.parametrize(
    "loader,error",
    [(stage0_load, Stage0Error), (stage1_load, Stage1Error), (part1_load, Part1CompletionError)],
)
def test_invalid_json_fails_closed(tmp_path: Path, loader: object, error: type[Exception]) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(error, match="cannot load"):
        loader(path)  # type: ignore[operator]


@pytest.mark.parametrize(
    "loader,error",
    [(stage0_load, Stage0Error), (stage1_load, Stage1Error), (part1_load, Part1CompletionError)],
)
def test_non_object_json_fails_closed(
    tmp_path: Path, loader: object, error: type[Exception]
) -> None:
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(error, match="JSON object required"):
        loader(path)  # type: ignore[operator]


def test_mapping_and_list_guards_fail_closed() -> None:
    with pytest.raises(Stage0Error, match="stage0 mapping"):
        stage0_mapping([], "stage0 mapping")
    with pytest.raises(Stage1Error, match="stage1 mapping"):
        stage1_mapping([], "stage1 mapping")
    with pytest.raises(Stage1Error, match="stage1 list"):
        stage1_list({}, "stage1 list")
    with pytest.raises(Part1CompletionError, match="part1 mapping"):
        part1_mapping([], "part1 mapping")
    with pytest.raises(Part1CompletionError, match="part1 list"):
        part1_list({}, "part1 list")


def test_preserved_json_loader_fails_closed(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(Part1CompletionError, match="cannot load preserved authority"):
        _load_preserved_json(invalid)
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(Part1CompletionError, match="preserved JSON object required"):
        _load_preserved_json(array)
