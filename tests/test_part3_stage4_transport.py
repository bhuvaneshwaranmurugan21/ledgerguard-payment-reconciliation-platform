from __future__ import annotations

import os
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from tools.part3_stage4.transport import ACCEPTED, materialize, verify_identity, verify_wheels


@pytest.fixture
def accepted_bundle() -> Path:
    # Qualification must supply the real accepted archive. Missing evidence fails.
    path = Path(os.environ["STAGE4_ACCEPTED_RUNTIME"])
    assert sha256(path.read_bytes()).hexdigest() == ACCEPTED["runtime_bundle_sha256"]
    return path


def test_real_transport_is_deterministic_and_preserves_admitted_bytes(
    accepted_bundle: Path, tmp_path: Path
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    assert materialize(accepted_bundle, first) == materialize(accepted_bundle, second)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }
    with (
        zipfile.ZipFile(accepted_bundle) as source,
        zipfile.ZipFile(first / "ledgerguard.gluewheels.zip") as transport,
    ):
        expected = {Path(n).name: source.read(n) for n in source.namelist() if n.endswith(".whl")}
        assert len(expected) == 7
        assert set(transport.namelist()) == set(expected)
        for name, raw in expected.items():
            assert transport.read(name) == raw
        assert (first / "ledgerguard_stage3_job.py").read_bytes() == source.read(
            "glue/ledgerguard_stage3_job.py"
        )
        for name in ("SBOM.spdx.json", "LICENSES.json", "PROVENANCE.json"):
            assert (first / name).read_bytes() == source.read(name)
    with pytest.raises(FileExistsError):
        materialize(accepted_bundle, first)


def test_unaccepted_archive_rejected_before_materialization(
    accepted_bundle: Path, tmp_path: Path
) -> None:
    altered = tmp_path / "changed.zip"
    altered.write_bytes(accepted_bundle.read_bytes() + b"unapproved appendix")
    with pytest.raises(ValueError, match="unaccepted"):
        materialize(altered, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "field", ["source_commit", "source_tree", "runtime_wheel_sha256", "sbom_sha256"]
)
def test_runtime_identity_substitution_rejected(field: str) -> None:
    verify_identity(dict(ACCEPTED))
    changed = dict(ACCEPTED)
    changed[field] = "0" * len(changed[field])
    with pytest.raises(ValueError, match=field):
        verify_identity(changed)
    del changed[field]
    with pytest.raises(ValueError, match=field):
        verify_identity(changed)


@pytest.mark.parametrize("change", ["extra", "missing", "changed", "duplicate"])
def test_transport_rejects_real_archive_tampering(
    accepted_bundle: Path, tmp_path: Path, change: str
) -> None:
    with zipfile.ZipFile(accepted_bundle) as source:
        expected = {Path(n).name: source.read(n) for n in source.namelist() if n.endswith(".whl")}
    names = sorted(expected)
    path = tmp_path / "tampered.zip"
    with zipfile.ZipFile(path, "w") as out:
        for name in names:
            if change == "missing" and name == names[0]:
                continue
            out.writestr(
                name, b"altered" if change == "changed" and name == names[0] else expected[name]
            )
        if change == "extra":
            out.writestr("unauthorized.whl", b"extra")
        if change == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                out.writestr(names[0], expected[names[0]])
    with pytest.raises(ValueError, match="round-trip"):
        verify_wheels(path, expected)
