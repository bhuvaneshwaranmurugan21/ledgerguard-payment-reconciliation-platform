"""Qualification receipt metadata remains explicit and fail closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.run_part3_stage5_incremental import _source_metadata


def test_explicit_verified_base_is_recorded_as_dirty_successor(tmp_path: Path):
    commit = "a" * 40
    tree = "b" * 40
    assert _source_metadata(tmp_path, commit, tree) == (commit, tree, True)


@pytest.mark.parametrize(
    "commit,tree",
    [
        ("a" * 40, None),
        (None, "b" * 40),
        ("A" * 40, "b" * 40),
        ("a" * 39, "b" * 40),
    ],
)
def test_explicit_base_requires_complete_full_lowercase_object_ids(
    tmp_path: Path, commit: str | None, tree: str | None
):
    with pytest.raises(ValueError):
        _source_metadata(tmp_path, commit, tree)
