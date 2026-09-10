from __future__ import annotations

import json
import runpy
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ledgerguard.stage3.profiles import get_profile
from tools import build_part3_stage3_ci_evidence as ci_builder
from tools import build_part3_stage3_runtime as builder
from tools import inspect_part3_stage3_artifact as inspector
from tools import inspect_part3_stage3_ci_artifact as ci_inspector
from tools import run_part3_stage3 as runner
from tools import run_part3_stage3_mutations as mutations
from tools import validate_part3_stage3 as validator

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "d0fb01392f7f975909229f418c13a9c73ba8395e"
SOURCE_TREE = "6be2444b583fde20d6fd84d47a87cde9432e2952"
SOURCE_DATE_EPOCH = 1788948092


def _write_zip(path: Path, members: dict[str, bytes], mode: int = 0o100644) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, raw in members.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, raw)


@pytest.mark.parametrize("name", ["/absolute", "a/../b", "directory/"])
def test_builder_rejects_unsafe_members(tmp_path: Path, name: str) -> None:
    with pytest.raises(SystemExit, match="unsafe archive member"):
        builder._zip(tmp_path / "unsafe.zip", {name: b"x"}, SOURCE_DATE_EPOCH)


def test_builder_private_distribution_guards(tmp_path: Path) -> None:
    assert builder._timestamp(0) == (1980, 1, 1, 0, 0, 0)
    with pytest.raises(SystemExit, match="site-packages unavailable"):
        builder._site_packages(tmp_path)
    site = tmp_path / "site"
    dist = site / "sample-1.0.dist-info"
    dist.mkdir(parents=True)
    (site / "kept.py").write_text("x = 1\n")
    (site / "__pycache__").mkdir()
    (site / "__pycache__/ignored.pyc").write_bytes(b"x")
    (site / "link.py").symlink_to(site / "kept.py")
    (dist / "RECORD").write_text(
        "\n/absolute,,\n../escape,,\nmissing.py,,\n__pycache__/ignored.pyc,,\n"
        "link.py,,\nkept.py,,\nsample-1.0.dist-info/RECORD,,\n"
    )
    assert builder._distribution_members(site, dist) == {"kept.py": b"x = 1\n"}


def _distribution(
    root: Path,
    distribution: str = "sample",
    version: str = "1.0",
    metadata_version: str | None = None,
    tag: str | None = "py3-none-any",
    member: str = "sample.py",
) -> tuple[Path, Path]:
    site = root / "site"
    info = site / f"{distribution}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {distribution}\n"
        f"Version: {metadata_version or version}\n\n"
    )
    (info / "WHEEL").write_text("Wheel-Version: 1.0\n" + (f"Tag: {tag}\n" if tag else ""))
    (site / member).parent.mkdir(parents=True, exist_ok=True)
    (site / member).write_bytes(b"payload")
    (info / "RECORD").write_text(f"{member},,\n{info.name}/RECORD,,\n")
    output = root / "out"
    output.mkdir()
    return site, output


def test_dependency_wheel_guard_matrix(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    output = tmp_path / "empty-out"
    output.mkdir()
    with pytest.raises(SystemExit, match="locked distribution unavailable"):
        builder.build_dependency_wheel(empty, "sample", "1.0", output, SOURCE_DATE_EPOCH)

    site, output = _distribution(tmp_path / "version", metadata_version="2.0")
    with pytest.raises(SystemExit, match="version mismatch"):
        builder.build_dependency_wheel(site, "sample", "1.0", output, SOURCE_DATE_EPOCH)

    site, output = _distribution(tmp_path / "tag", tag=None)
    with pytest.raises(SystemExit, match="wheel tag unavailable"):
        builder.build_dependency_wheel(site, "sample", "1.0", output, SOURCE_DATE_EPOCH)

    site, output = _distribution(tmp_path / "native", member="native.so")
    with pytest.raises(SystemExit, match="native member in pure wheel"):
        builder.build_dependency_wheel(site, "sample", "1.0", output, SOURCE_DATE_EPOCH)

    site, output = _distribution(tmp_path / "rpds", distribution="rpds_py")
    with pytest.raises(SystemExit, match=r"not CPython 3\.11"):
        builder.build_dependency_wheel(site, "rpds_py", "1.0", output, SOURCE_DATE_EPOCH)


def test_runtime_member_contract_digest_guard(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "src/ledgerguard/reconciliation").mkdir(parents=True)
    (repository / "src/ledgerguard/contract_data").mkdir(parents=True)
    (repository / "contracts").mkdir()
    (repository / "src/ledgerguard/contract_data/__init__.py").write_text("")
    (repository / "contracts/example.json").write_text("{}\n")
    (repository / "contracts/active-contract-set-v1.json").write_text(
        json.dumps({"contracts": [{"path": "contracts/example.json", "sha256": "0" * 64}]})
    )
    original = builder.RUNTIME_STAGE3
    builder.RUNTIME_STAGE3 = ()
    try:
        with pytest.raises(SystemExit, match="contract digest mismatch"):
            builder._runtime_members(repository)
    finally:
        builder.RUNTIME_STAGE3 = original


def test_builder_main_argument_and_execution_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = [
        "build",
        "--environment",
        str(tmp_path),
        "--output",
        str(tmp_path / "output"),
        "--source-commit",
        SOURCE_COMMIT,
        "--source-tree",
        SOURCE_TREE,
        "--source-date-epoch",
        str(SOURCE_DATE_EPOCH),
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(builder.sys, "version_info", (3, 10, 0))
    with pytest.raises(SystemExit, match="exact CPython"):
        builder.main()
    monkeypatch.setattr(builder.sys, "version_info", (3, 11, 13))
    source_index = arguments.index(SOURCE_COMMIT)
    arguments[source_index] = "bad"
    with pytest.raises(SystemExit, match="invalid source identity"):
        builder.main()
    arguments[source_index] = SOURCE_COMMIT
    monkeypatch.setattr(builder, "build_bundle", lambda *args: {"verdict": "PASS"})
    builder.main()
    assert '"verdict": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["build", "--help"])
    monkeypatch.delitem(sys.modules, "tools.build_part3_stage3_runtime")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("tools.build_part3_stage3_runtime", run_name="__main__")


def _valid_bundle(tmp_path: Path) -> Path:
    result = builder.build_bundle(
        ROOT, Path(sys.prefix), tmp_path / "bundle", SOURCE_COMMIT, SOURCE_TREE, SOURCE_DATE_EPOCH
    )
    assert result["bundle"]["sha256"]
    return tmp_path / "bundle/ledgerguard-stage3-glue-runtime.zip"


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_inspector_low_level_guard_matrix(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("same", b"a")
            archive.writestr("same", b"b")
    with zipfile.ZipFile(duplicate) as archive, pytest.raises(ValueError, match="duplicate"):
        inspector._safe_members(archive)

    for index, (name, mode, message) in enumerate(
        [("../unsafe", 0o100644, "unsafe"), ("mode", 0o100755, "mode")]
    ):
        path = tmp_path / f"unsafe-{index}.zip"
        _write_zip(path, {name: b"x"}, mode)
        with zipfile.ZipFile(path) as archive, pytest.raises(ValueError, match=message):
            inspector._safe_members(archive)

    with pytest.raises(ValueError, match="invalid required JSON"):
        inspector._json({}, "missing")
    with pytest.raises(ValueError, match="not an object"):
        inspector._json({"value": b"[]"}, "value")


def _wheel(tmp_path: Path, members: dict[str, bytes]) -> bytes:
    path = tmp_path / f"wheel-{len(list(tmp_path.glob('wheel-*')))}.zip"
    _write_zip(path, members)
    return path.read_bytes()


def test_wheel_record_guard_matrix(tmp_path: Path) -> None:
    record = "sample.dist-info/RECORD"
    with pytest.raises(ValueError, match="exactly one RECORD"):
        inspector._inspect_record(_wheel(tmp_path, {"a.py": b"x"}))
    bad_rows = [
        (b"broken\n", "invalid or duplicate"),
        (f"{record},sha256=x,1\n".encode(), "self-row"),
        (f"missing.py,sha256=x,1\n{record},,\n".encode(), "member or size"),
        (f"a.py,sha256=x,1\n{record},,\n".encode(), "digest mismatch"),
        (f"{record},,\n".encode(), "coverage differs"),
    ]
    for content, message in bad_rows:
        with pytest.raises(ValueError, match=message):
            inspector._inspect_record(_wheel(tmp_path, {"a.py": b"x", record: content}))


def _rewrite_bundle(tmp_path: Path, base: Path, mutate: object) -> Path:
    members = _members(base)
    if callable(mutate):
        mutate(members)
    target = tmp_path / f"mutated-{len(list(tmp_path.glob('mutated-*')))}.zip"
    _write_zip(target, members)
    return target


def test_runtime_inspector_bundle_guard_matrix(tmp_path: Path) -> None:
    base = _valid_bundle(tmp_path)

    def remove_required(rows: dict[str, bytes]) -> None:
        rows.pop("LICENSES.json")

    def list_manifest(rows: dict[str, bytes]) -> None:
        rows["package-manifest.json"] = b"[]"

    def no_inventory(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["package-manifest.json"])
        value["members"] = None
        rows["package-manifest.json"] = json.dumps(value).encode()

    def invalid_row(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["package-manifest.json"])
        value["members"][0] = []
        rows["package-manifest.json"] = json.dumps(value).encode()

    def duplicate_path(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["package-manifest.json"])
        value["members"].append(value["members"][0])
        rows["package-manifest.json"] = json.dumps(value).encode()

    def identity(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["package-manifest.json"])
        value["members"][0]["sha256"] = "0" * 64
        rows["package-manifest.json"] = json.dumps(value).encode()

    def set_differs(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["package-manifest.json"])
        value["members"].pop()
        rows["package-manifest.json"] = json.dumps(value).encode()

    def sbom_standard(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["SBOM.spdx.json"])
        value["spdxVersion"] = "wrong"
        rows["SBOM.spdx.json"] = json.dumps(value).encode()
        manifest = json.loads(rows["package-manifest.json"])
        for item in manifest["members"]:
            if item["path"] == "SBOM.spdx.json":
                item["size_bytes"] = len(rows["SBOM.spdx.json"])
                from hashlib import sha256

                item["sha256"] = sha256(rows["SBOM.spdx.json"]).hexdigest()
        rows["package-manifest.json"] = json.dumps(manifest).encode()

    cases = [
        (remove_required, "required runtime"),
        (list_manifest, "not an object"),
        (no_inventory, "inventory unavailable"),
        (invalid_row, "invalid package inventory"),
        (duplicate_path, "duplicate or unexpected"),
        (identity, "identity mismatch"),
        (set_differs, "inventory set differs"),
        (sbom_standard, "SBOM standard"),
    ]
    for mutate, message in cases:
        with pytest.raises(ValueError, match=message):
            inspector.inspect_runtime_bundle(_rewrite_bundle(tmp_path, base, mutate))


def test_inspector_main_and_remaining_bundle_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _valid_bundle(tmp_path)
    monkeypatch.setattr(sys, "argv", ["inspect", str(base)])
    inspector.main()
    assert '"sbom_valid": true' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["inspect", "--help"])
    monkeypatch.delitem(sys.modules, "tools.inspect_part3_stage3_artifact")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("tools.inspect_part3_stage3_artifact", run_name="__main__")

    def mutate_and_sync(rows: dict[str, bytes], action: object) -> None:
        action(rows)
        from hashlib import sha256

        manifest = json.loads(rows["package-manifest.json"])
        manifest["members"] = [
            {
                "path": name,
                "size_bytes": len(raw),
                "sha256": sha256(raw).hexdigest(),
            }
            for name, raw in sorted(rows.items())
            if name != "package-manifest.json"
        ]
        rows["package-manifest.json"] = json.dumps(manifest).encode()

    def sbom_digest(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["package-manifest.json"])
        value["sbom_sha256"] = "0" * 64
        rows["package-manifest.json"] = json.dumps(value).encode()

    def wheel_count(rows: dict[str, bytes]) -> None:
        rows.pop(next(name for name in rows if name.startswith("wheelhouse/attrs-")))

    def runtime_identity(rows: dict[str, bytes]) -> None:
        name = next(name for name in rows if "/ledgerguard_runtime-" in name)
        rows["wheelhouse/not-runtime.whl"] = rows.pop(name)

    def runtime_digest(rows: dict[str, bytes]) -> None:
        value = json.loads(rows["package-manifest.json"])
        value["runtime_wheel_sha256"] = "0" * 64
        rows["package-manifest.json"] = json.dumps(value).encode()

    def forbidden(rows: dict[str, bytes]) -> None:
        from hashlib import sha256

        name = next(name for name in rows if "/ledgerguard_runtime-" in name)
        wheel_rows = _members_from_bytes(rows[name])
        wheel_rows["ledgerguard/stage3/generator.py"] = b""
        record_name = next(item for item in wheel_rows if item.endswith(".dist-info/RECORD"))
        record_rows = [
            builder._record_line(item, raw)
            for item, raw in sorted(wheel_rows.items())
            if item != record_name
        ]
        record_rows.append(f"{record_name},,")
        wheel_rows[record_name] = ("\n".join(record_rows) + "\n").encode()
        wheel_path = tmp_path / "forbidden-wheel.zip"
        _write_zip(wheel_path, wheel_rows)
        rows[name] = wheel_path.read_bytes()
        value = json.loads(rows["package-manifest.json"])
        value["runtime_wheel_sha256"] = sha256(rows[name]).hexdigest()
        rows["package-manifest.json"] = json.dumps(value).encode()

    cases = [
        (sbom_digest, "SBOM digest"),
        (wheel_count, "wheel closure count"),
        (runtime_identity, "runtime wheel identity"),
        (runtime_digest, "runtime wheel digest"),
        (forbidden, "excluded oracle"),
    ]
    for action, message in cases:
        path = _rewrite_bundle(
            tmp_path, base, lambda rows, action=action: mutate_and_sync(rows, action)
        )
        with pytest.raises(ValueError, match=message):
            inspector.inspect_runtime_bundle(path)


def _members_from_bytes(raw: bytes) -> dict[str, bytes]:
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_single_validation_orchestrates_real_small_asset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        validator,
        "PROFILES",
        {
            "correctness-small": get_profile("correctness-small"),
            "secondary-copy": get_profile("correctness-small"),
        },
    )

    def fake_spark(repository: Path, asset: Path, candidate: Path) -> dict[str, object]:
        del repository, asset
        candidate.mkdir()
        (candidate / "candidate-manifest.json").write_text("{}\n")
        (candidate / "COMPLETED.json").write_text("{}\n")
        return {
            "transaction_count": 16,
            "settlement_count": 4,
            "allocation_count": 5,
            "logical_sha256": "1" * 64,
            "candidate_manifest_sha256": "9" * 64,
            "authoritative_proof": False,
        }

    monkeypatch.setattr(validator, "run_local", fake_spark)
    monkeypatch.setattr(
        validator,
        "build_bundle",
        lambda *args: {"bundle": {"sha256": "2" * 64}},
    )
    monkeypatch.setattr(validator, "inspect_runtime_bundle", lambda path: {"valid": True})
    result = validator.execute_one(ROOT, tmp_path / "evidence", SOURCE_COMMIT, SOURCE_TREE)
    assert result["verdict"] == "PASS"
    assert result["deterministic_payload"]["aws_execution"] is False
    assert "candidate_manifest_file_sha256" not in result["deterministic_payload"]["spark"]
    assert result["spark_physical_evidence"]["candidate_manifest_file_sha256"]


def test_validation_guards_and_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(validator.sys, "version_info", (3, 10, 0))
    with pytest.raises(SystemExit, match="exact CPython"):
        validator.execute_one(ROOT, tmp_path / "bad-version", SOURCE_COMMIT, SOURCE_TREE)
    monkeypatch.setattr(validator.sys, "version_info", (3, 11, 13))
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "x").write_text("x")
    with pytest.raises(SystemExit, match="must be empty"):
        validator.execute_one(ROOT, occupied, SOURCE_COMMIT, SOURCE_TREE)
    monkeypatch.setattr(validator, "PROFILES", {})
    with pytest.raises(SystemExit, match="correctness qualification"):
        validator.execute_one(ROOT, tmp_path / "no-small", SOURCE_COMMIT, SOURCE_TREE)

    called: list[object] = []
    monkeypatch.setattr(validator, "execute_one", lambda *args: called.extend(args) or {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate",
            "--repository",
            str(ROOT),
            "--output",
            str(tmp_path / "main"),
            "--source-commit",
            SOURCE_COMMIT,
            "--source-tree",
            SOURCE_TREE,
        ],
    )
    validator.main()
    assert called
    monkeypatch.setattr(sys, "argv", ["validate", "--help"])
    monkeypatch.delitem(sys.modules, "tools.validate_part3_stage3")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("tools.validate_part3_stage3", run_name="__main__")


def _runner_git(arguments: tuple[str, ...], dirty: bool = False) -> str:
    if arguments == ("status", "--porcelain"):
        return "dirty" if dirty else ""
    if arguments == ("rev-parse", "HEAD"):
        return "f" * 40
    if arguments == ("rev-parse", "HEAD^{tree}"):
        return "e" * 40
    if arguments == ("show", "-s", "--format=%T", runner.BASE_COMMIT):
        return runner.BASE_TREE
    if arguments == ("show", "-s", "--format=%P", runner.BASE_COMMIT):
        return runner.BASE_PARENT
    if arguments == ("show", "-s", "--format=%ct", "f" * 40):
        return str(SOURCE_DATE_EPOCH)
    raise AssertionError(arguments)


def test_runner_positive_and_determinism_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    monkeypatch.setattr(runner, "_git", lambda root, *args: _runner_git(args))
    monkeypatch.setattr(runner, "_qualification", lambda *args: {"verdict": "PASS"})
    calls = 0

    def fake_subprocess(command: list[str], **kwargs: object) -> SimpleNamespace:
        nonlocal calls
        if command[:3] == ["git", "merge-base", "--is-ancestor"]:
            return SimpleNamespace(returncode=0)
        calls += 1
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True)
        payload = {"stable": True}
        result = {
            "deterministic_payload": payload,
            "deterministic_payload_sha256": __import__("hashlib").sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "spark_physical_evidence": {"run": calls},
            "telemetry": {"run": calls},
        }
        (output / "validation-result.json").write_text(json.dumps(result))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_subprocess)
    evidence = runner.run(repository, tmp_path / "output", 2)
    assert evidence["verdict"] == "PASS"
    assert evidence["clean_run_count"] == 2
    assert evidence["spark_physical_evidence"] == [{"run": 1}, {"run": 2}]
    assert (tmp_path / "output/artifact-manifest.json").is_file()

    def differing(command: list[str], **kwargs: object) -> SimpleNamespace:
        result = fake_subprocess(command, **kwargs)
        if "--output" in command and command[command.index("--output") + 1].endswith("run-2"):
            path = Path(command[command.index("--output") + 1]) / "validation-result.json"
            value = json.loads(path.read_text())
            value["deterministic_payload"] = {"stable": False}
            path.write_text(json.dumps(value))
        return result

    monkeypatch.setattr(runner.subprocess, "run", differing)
    with pytest.raises(SystemExit, match="payloads differ"):
        runner.run(repository, tmp_path / "different", 2)

    def bad_digest(command: list[str], **kwargs: object) -> SimpleNamespace:
        result = fake_subprocess(command, **kwargs)
        if "--output" in command:
            path = Path(command[command.index("--output") + 1]) / "validation-result.json"
            value = json.loads(path.read_text())
            value["deterministic_payload_sha256"] = "0" * 64
            path.write_text(json.dumps(value))
        return result

    monkeypatch.setattr(runner.subprocess, "run", bad_digest)
    with pytest.raises(SystemExit, match="payload digest differs"):
        runner.run(repository, tmp_path / "digest", 2)


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ("runs", "exactly two"),
        ("inside", "outside the repository"),
        ("nonempty", "must be empty"),
        ("dirty", "clean worktree"),
        ("tree", "base tree differs"),
        ("parent", "base parent differs"),
        ("timestamp", "head timestamp is invalid"),
        ("ancestor", "does not descend"),
    ],
)
def test_runner_entry_guard_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, condition: str, message: str
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    output = tmp_path / "out"
    runs = 1 if condition == "runs" else 2
    if condition == "inside":
        output = repository / "out"
    if condition == "nonempty":
        output.mkdir()
        (output / "x").write_text("x")

    def git(root: Path, *args: str) -> str:
        value = _runner_git(args, dirty=condition == "dirty")
        if condition == "tree" and args[:3] == ("show", "-s", "--format=%T"):
            return "wrong"
        if condition == "parent" and args[:3] == ("show", "-s", "--format=%P"):
            return "wrong"
        if condition == "timestamp" and args[:3] == ("show", "-s", "--format=%ct"):
            return "invalid"
        return value

    monkeypatch.setattr(runner, "_git", git)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1 if condition == "ancestor" else 0),
    )
    with pytest.raises(SystemExit, match=message):
        runner.run(repository, output, runs)


def test_runner_identity_git_and_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "value"
    path.write_bytes(b"abc")
    assert runner._identity(path)["size_bytes"] == 3
    assert runner._git(ROOT, "rev-parse", "HEAD")
    monkeypatch.setattr(runner, "run", lambda *args: {"verdict": "PASS"})
    monkeypatch.setattr(sys, "argv", ["run", "--output", str(tmp_path / "out")])
    runner.main()
    assert '"verdict": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["run", "--help"])
    monkeypatch.delitem(sys.modules, "tools.run_part3_stage3")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("tools.run_part3_stage3", run_name="__main__")


def _qualification_execute(
    command: list[str], output: Path, coverage: float = 100.0, mutations_killed: bool = True
) -> None:
    if "--junitxml" in command:
        path = Path(command[command.index("--junitxml") + 1])
        path.write_text(
            '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/>'
            "</testsuites>"
        )
    if "json" in command and "coverage" in command:
        path = Path(command[command.index("-o") + 1])
        path.write_text(json.dumps({"totals": {"percent_covered": coverage}}))
    if len(command) > 1 and command[1].endswith("tools/run_part3_stage3_mutations.py"):
        path = Path(command[command.index("--output") + 1])
        path.mkdir()
        rows = [{"killed": mutations_killed} for _ in range(24)]
        (path / "results.json").write_text(json.dumps(rows))


def test_qualification_orchestration_and_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "_execute",
        lambda repository, command, environment: _qualification_execute(
            command, tmp_path / "unused"
        ),
    )
    result = runner._qualification(ROOT, tmp_path / "qualified", {})
    assert result["coverage"]["percent_covered"] == 100.0
    assert result["mutations"] == {"total": 24, "killed": 24}

    monkeypatch.setattr(runner.sys, "version_info", (3, 10, 0))
    with pytest.raises(SystemExit, match="exact CPython"):
        runner._qualification(ROOT, tmp_path / "version", {})
    monkeypatch.setattr(runner.sys, "version_info", (3, 11, 13))
    with pytest.raises(SystemExit, match="forbids AWS credential"):
        runner._qualification(ROOT, tmp_path / "aws", {"AWS_ACCESS_KEY_ID": "present"})


def test_qualification_result_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "_execute",
        lambda repository, command, environment: _qualification_execute(
            command, tmp_path / "unused", coverage=99.9
        ),
    )
    with pytest.raises(SystemExit, match="coverage differs"):
        runner._qualification(ROOT, tmp_path / "coverage", {})
    monkeypatch.setattr(
        runner,
        "_execute",
        lambda repository, command, environment: _qualification_execute(
            command, tmp_path / "unused", mutations_killed=False
        ),
    )
    with pytest.raises(SystemExit, match="mutation qualification"):
        runner._qualification(ROOT, tmp_path / "mutation", {})


def test_runner_execute_and_junit_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: list[object] = []
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *args, **kwargs: called.append(args) or None
    )
    runner._execute(ROOT, ["command"], {})
    assert called
    single = tmp_path / "single.xml"
    single.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>')
    assert runner._junit_counts(single)["tests"] == 1
    for index, attributes in enumerate(
        [
            'tests="0" failures="0" errors="0" skipped="0"',
            'tests="1" failures="1" errors="0" skipped="0"',
            'tests="1" failures="0" errors="1" skipped="0"',
            'tests="1" failures="0" errors="0" skipped="1"',
        ]
    ):
        path = tmp_path / f"bad-{index}.xml"
        path.write_text(f"<testsuite {attributes}/>")
        with pytest.raises(SystemExit, match="not complete and green"):
            runner._junit_counts(path)


def test_mutation_runner_executes_complete_reviewed_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        junit = Path(command[command.index("--junitxml") + 1])
        junit.write_text(
            '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0"/>'
            "</testsuites>"
        )
        return SimpleNamespace(returncode=1, stdout="failure", stderr="")

    monkeypatch.setattr(mutations.subprocess, "run", fake_run)
    output = tmp_path / "mutations"
    results = mutations.run_mutations(ROOT, output)
    assert len(results) == 24
    assert all(row["killed"] for row in results)
    assert json.loads((output / "results.json").read_text()) == results


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value["mutations"].pop(), "inventory differs"),
        (
            lambda value: value["mutations"][0].update(family="wrong"),
            "families differ",
        ),
        (lambda value: value.update(equivalent_mutations=["x"]), "adjudication differs"),
    ],
)
def test_mutation_registry_guards(
    tmp_path: Path, change: object, message: str
) -> None:
    root = tmp_path / "root"
    (root / "spec").mkdir(parents=True)
    value = json.loads((ROOT / "spec/part3-stage3-code-mutations-v1.json").read_text())
    change(value)
    (root / "spec/part3-stage3-code-mutations-v1.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match=message):
        mutations.run_mutations(root, tmp_path / "output")


def test_mutation_execution_failure_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def no_junit(command: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(mutations.subprocess, "run", no_junit)
    with pytest.raises(ValueError, match="no test evidence"):
        mutations.run_mutations(ROOT, tmp_path / "no-junit")

    def survivor(command: list[str], **kwargs: object) -> SimpleNamespace:
        junit = Path(command[command.index("--junitxml") + 1])
        junit.write_text(
            '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"/>'
            "</testsuites>"
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mutations.subprocess, "run", survivor)
    with pytest.raises(ValueError, match="survived or failed"):
        mutations.run_mutations(ROOT, tmp_path / "survivor")

    value = json.loads((ROOT / "spec/part3-stage3-code-mutations-v1.json").read_text())
    value["mutations"][0]["before"] = "not present"
    altered = tmp_path / "altered"
    mutations._copy_repository(ROOT, altered)
    (altered / "spec/part3-stage3-code-mutations-v1.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="target is not unique"):
        mutations.run_mutations(altered, tmp_path / "bad-target")


def test_mutation_runner_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: list[object] = []
    monkeypatch.setattr(mutations, "run_mutations", lambda *args: called.extend(args) or [])
    monkeypatch.setattr(
        sys,
        "argv",
        ["mutations", "--root", str(ROOT), "--output", str(tmp_path / "output")],
    )
    mutations.main()
    assert called
    monkeypatch.setattr(sys, "argv", ["mutations", "--help"])
    monkeypatch.delitem(sys.modules, "tools.run_part3_stage3_mutations")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("tools.run_part3_stage3_mutations", run_name="__main__")


def _ci_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, str, Path]:
    head = "a" * 40
    tree = "b" * 40
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": head}}}))
    values = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event),
        "EXPECTED_SHA": head,
        "GITHUB_REPOSITORY": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_REF": "refs/pull/26/merge",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    def git(command: list[str], **kwargs: object) -> str:
        return head if "rev-parse" in command else tree

    monkeypatch.setattr(ci_builder.subprocess, "check_output", git)
    return head, tree, event


def _local_evidence(artifact: Path, head: str, tree: str) -> None:
    artifact.mkdir()
    (artifact / "part3-stage3-local-evidence.json").write_text(
        json.dumps(
            {
                "head_sha": head,
                "head_tree": tree,
                "deterministic_payload_sha256": "c" * 64,
                "verdict": "PASS",
                "aws_execution": False,
            }
        )
    )


def test_ci_evidence_build_and_independent_inspection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head, tree, _ = _ci_environment(monkeypatch, tmp_path)
    artifact = tmp_path / "artifact"
    _local_evidence(artifact, head, tree)
    envelope = ci_builder.build(artifact)
    assert envelope["workflow_run_id"] == 123
    result = ci_inspector.inspect(artifact, head, 123, 2)
    assert result["independently_accepted"] is True
    assert result["head_tree"] == tree


def test_ci_builder_guards_and_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in list(ci_builder.os.environ):
        if name.startswith("GITHUB_") or name == "EXPECTED_SHA":
            monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="environment variable is missing"):
        ci_builder._required("GITHUB_EVENT_NAME")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "manual")
    artifact = tmp_path / "invalid-event"
    artifact.mkdir()
    (artifact / "part3-stage3-local-evidence.json").write_text("{}")
    with pytest.raises(SystemExit, match="requires pull_request or push"):
        ci_builder.build(artifact)

    head, tree, event = _ci_environment(monkeypatch, tmp_path)
    push_event = tmp_path / "push.json"
    push_event.write_text("{}")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(push_event))
    monkeypatch.setenv("GITHUB_SHA", head)
    push_artifact = tmp_path / "push-artifact"
    _local_evidence(push_artifact, head, tree)
    assert ci_builder.build(push_artifact)["event"] == "push"

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("EXPECTED_SHA", "d" * 40)
    mismatch = tmp_path / "mismatch"
    _local_evidence(mismatch, head, tree)
    with pytest.raises(SystemExit, match="checkout differs"):
        ci_builder.build(mismatch)
    monkeypatch.setenv("EXPECTED_SHA", head)
    local_mismatch = tmp_path / "local-mismatch"
    _local_evidence(local_mismatch, head, "d" * 40)
    with pytest.raises(SystemExit, match="local evidence source"):
        ci_builder.build(local_mismatch)

    monkeypatch.setenv("GITHUB_REPOSITORY", "wrong/repository")
    invalid_schema = tmp_path / "invalid-schema"
    _local_evidence(invalid_schema, head, tree)
    with pytest.raises(SystemExit, match="CI evidence is invalid"):
        ci_builder.build(invalid_schema)
    monkeypatch.setenv(
        "GITHUB_REPOSITORY",
        "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
    )

    success = tmp_path / "main-success"
    _local_evidence(success, head, tree)
    monkeypatch.setattr(sys, "argv", ["ci-build", "--artifact-directory", str(success)])
    ci_builder.main()
    assert '"workflow_run_id": 123' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["ci-build", "--help"])
    monkeypatch.delitem(sys.modules, "tools.build_part3_stage3_ci_evidence")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("tools.build_part3_stage3_ci_evidence", run_name="__main__")


def _refresh_artifact_manifest(artifact: Path) -> None:
    from hashlib import sha256

    members = []
    for path in sorted(artifact.rglob("*")):
        if path.is_file() and path.name != "artifact-manifest.json":
            raw = path.read_bytes()
            members.append(
                {
                    "path": path.relative_to(artifact).as_posix(),
                    "size_bytes": len(raw),
                    "sha256": sha256(raw).hexdigest(),
                }
            )
    manifest = json.loads((artifact / "artifact-manifest.json").read_text())
    manifest["members"] = members
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (artifact / "artifact-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )


def test_ci_artifact_inspector_guard_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head, tree, _ = _ci_environment(monkeypatch, tmp_path)

    def fresh(name: str) -> Path:
        artifact = tmp_path / name
        _local_evidence(artifact, head, tree)
        ci_builder.build(artifact)
        return artifact

    with pytest.raises(ValueError, match="external directory"):
        ci_inspector.inspect(tmp_path / "absent", head, 123, 2)
    symlinked = fresh("symlink")
    (symlinked / "link").symlink_to(symlinked / "ci-evidence.json")
    with pytest.raises(ValueError, match="symlink"):
        ci_inspector.inspect(symlinked, head, 123, 2)

    digest = fresh("digest")
    manifest = json.loads((digest / "artifact-manifest.json").read_text())
    manifest["manifest_sha256"] = "0" * 64
    (digest / "artifact-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest digest"):
        ci_inspector.inspect(digest, head, 123, 2)

    no_rows = fresh("no-rows")
    manifest = json.loads((no_rows / "artifact-manifest.json").read_text())
    manifest["members"] = None
    manifest.pop("manifest_sha256")
    from hashlib import sha256

    manifest["manifest_sha256"] = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (no_rows / "artifact-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inventory is unavailable"):
        ci_inspector.inspect(no_rows, head, 123, 2)

    invalid = fresh("invalid-row")
    manifest = json.loads((invalid / "artifact-manifest.json").read_text())
    manifest["members"][0] = []
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (invalid / "artifact-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="row is invalid"):
        ci_inspector.inspect(invalid, head, 123, 2)

    duplicate = fresh("duplicate-row")
    manifest = json.loads((duplicate / "artifact-manifest.json").read_text())
    manifest["members"].append(manifest["members"][0])
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (duplicate / "artifact-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe or duplicated"):
        ci_inspector.inspect(duplicate, head, 123, 2)

    identity = fresh("identity")
    manifest = json.loads((identity / "artifact-manifest.json").read_text())
    manifest["members"][0]["sha256"] = "0" * 64
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (identity / "artifact-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="member identity differs"):
        ci_inspector.inspect(identity, head, 123, 2)

    extra = fresh("extra")
    (extra / "extra.txt").write_text("extra")
    with pytest.raises(ValueError, match="member set differs"):
        ci_inspector.inspect(extra, head, 123, 2)

    wrong_head = fresh("wrong-head")
    with pytest.raises(ValueError, match="head identity differs"):
        ci_inspector.inspect(wrong_head, "d" * 40, 123, 2)
    wrong_run = fresh("wrong-run")
    with pytest.raises(ValueError, match="workflow run identity differs"):
        ci_inspector.inspect(wrong_run, head, 999, 2)
    wrong_payload = fresh("wrong-payload")
    ci = json.loads((wrong_payload / "ci-evidence.json").read_text())
    ci["deterministic_payload_sha256"] = "d" * 64
    (wrong_payload / "ci-evidence.json").write_text(json.dumps(ci))
    _refresh_artifact_manifest(wrong_payload)
    with pytest.raises(ValueError, match="payload binding differs"):
        ci_inspector.inspect(wrong_payload, head, 123, 2)

    wrong_tree = fresh("wrong-tree")
    ci = json.loads((wrong_tree / "ci-evidence.json").read_text())
    ci["head_tree"] = "d" * 40
    (wrong_tree / "ci-evidence.json").write_text(json.dumps(ci))
    _refresh_artifact_manifest(wrong_tree)
    with pytest.raises(ValueError, match="head identity differs"):
        ci_inspector.inspect(wrong_tree, head, 123, 2)

    wrong_verdict = fresh("wrong-verdict")
    local = json.loads((wrong_verdict / "part3-stage3-local-evidence.json").read_text())
    local["verdict"] = "FAIL"
    (wrong_verdict / "part3-stage3-local-evidence.json").write_text(json.dumps(local))
    _refresh_artifact_manifest(wrong_verdict)
    with pytest.raises(ValueError, match="qualification verdict differs"):
        ci_inspector.inspect(wrong_verdict, head, 123, 2)

    wrong_boundary = fresh("wrong-boundary")
    local = json.loads((wrong_boundary / "part3-stage3-local-evidence.json").read_text())
    local["aws_execution"] = True
    (wrong_boundary / "part3-stage3-local-evidence.json").write_text(json.dumps(local))
    _refresh_artifact_manifest(wrong_boundary)
    with pytest.raises(ValueError, match="AWS execution boundary differs"):
        ci_inspector.inspect(wrong_boundary, head, 123, 2)


def test_ci_artifact_inspector_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(ci_inspector, "inspect", lambda *args: {"accepted": True})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspect-ci",
            "--artifact",
            str(tmp_path),
            "--expected-sha",
            "a" * 40,
            "--expected-run-id",
            "1",
            "--expected-run-attempt",
            "1",
            "--output",
            str(output),
        ],
    )
    ci_inspector.main()
    assert json.loads(output.read_text()) == {"accepted": True}
    monkeypatch.setattr(sys, "argv", ["inspect-ci", "--help"])
    monkeypatch.delitem(sys.modules, "tools.inspect_part3_stage3_ci_artifact")
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("tools.inspect_part3_stage3_ci_artifact", run_name="__main__")


def test_validation_commit_epoch_rejects_invalid_git_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_timestamp(*args: object, **kwargs: object) -> str:
        return "invalid\n"

    monkeypatch.setattr(validator.subprocess, "check_output", invalid_timestamp)
    with pytest.raises(SystemExit, match="source commit timestamp is invalid"):
        validator._commit_epoch(ROOT, "0" * 40)
