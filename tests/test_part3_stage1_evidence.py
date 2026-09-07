from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ledgerguard_part3_stage1_evidence import (
    REPOSITORY,
    build_manifest,
    digest,
    envelope,
    verify_manifest,
)
from ledgerguard_part3_stage1_validation import EntryRejected


def inputs() -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    env = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "EXPECTED_SHA": "a" * 40,
    }
    event = {"number": 19, "pull_request": {"head": {"sha": "a" * 40}}}
    payload = {"wheel_sha256": "b" * 64}
    local = {
        "part": 3,
        "stage": 1,
        "clean_run_count": 2,
        "deterministic_equal": True,
        "deterministic_payload": payload,
        "deterministic_payload_sha256": digest(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ),
        "execution_boundary": {"aws_execution": False},
    }
    return env, event, local


def test_pr_and_main_envelopes_bind_exact_event_head_without_self_attesting_success() -> None:
    env, event, local = inputs()
    first = envelope(env, event, local, "a" * 40, "c" * 40)
    assert first["run_success_independently_required"] is True
    assert first["postmerge_verification_required"] is True
    assert first["aws_execution"] is False and first["project_complete"] is False
    env.update(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main", GITHUB_SHA="a" * 40)
    assert envelope(env, {}, local, "a" * 40, "c" * 40)["pull_request_number"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_REPOSITORY", "other/repository"),
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_RUN_ID", "0"),
        ("GITHUB_RUN_ATTEMPT", "abc"),
        ("EXPECTED_SHA", "d" * 40),
    ],
)
def test_forged_event_metadata_rejects(key: str, value: str) -> None:
    env, event, local = inputs()
    env[key] = value
    with pytest.raises(EntryRejected):
        envelope(env, event, local, "a" * 40, "c" * 40)


@pytest.mark.parametrize("field", ["head", "tree", "pr", "push", "runs", "digest", "wheel", "aws"])
def test_evidence_cannot_upgrade_invalid_local_or_event_facts(field: str) -> None:
    env, event, local = inputs()
    head = "a" * 40
    tree = "c" * 40
    if field == "head":
        event["pull_request"]["head"]["sha"] = "not-a-sha"
    elif field == "tree":
        tree = "not-a-tree"
    elif field == "pr":
        event["number"] = True
    elif field == "push":
        env.update(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/other")
    elif field == "runs":
        local["clean_run_count"] = 1
    elif field == "digest":
        local["deterministic_payload_sha256"] = "0" * 64
    elif field == "wheel":
        local["deterministic_payload"]["wheel_sha256"] = "invalid"
        local["deterministic_payload_sha256"] = digest(
            json.dumps(
                local["deterministic_payload"], sort_keys=True, separators=(",", ":")
            ).encode()
        )
    else:
        local["execution_boundary"]["aws_execution"] = True
    with pytest.raises(EntryRejected):
        envelope(env, event, local, head, tree)


def test_artifact_inventory_is_exact_recursive_and_non_self_referential(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/report.json").write_text("{}")
    (tmp_path / "manifest.json").write_text("self is explicitly excluded")
    m = build_manifest(tmp_path)
    assert verify_manifest(tmp_path, m) == {"members": 1, "integrity_verified": True}
    (tmp_path / "extra").write_text("undeclared")
    with pytest.raises(EntryRejected):
        verify_manifest(tmp_path, m)


@pytest.mark.parametrize(
    "alteration",
    [
        "empty",
        "symlink",
        "envelope",
        "inventory",
        "shape",
        "traversal",
        "absolute",
        "backslash",
        "self",
        "digest",
        "missing",
    ],
)
def test_artifact_adversaries_fail_closed(tmp_path: Path, alteration: str) -> None:
    path = tmp_path / "report.json"
    path.write_text("{}")
    m = build_manifest(tmp_path)
    if alteration == "empty":
        path.unlink()
    elif alteration == "symlink":
        (tmp_path / "link").symlink_to(path)
    elif alteration == "envelope":
        m["schema_version"] = "2.0"
    elif alteration == "inventory":
        m["members"] = []
    elif alteration == "shape":
        m["members"][0]["extra"] = True
    elif alteration in ("traversal", "absolute", "backslash", "self"):
        m["members"][0]["path"] = {
            "traversal": "../report",
            "absolute": "/report",
            "backslash": "a\\report",
            "self": "manifest.json",
        }[alteration]
    elif alteration == "digest":
        path.write_text("changed")
    else:
        path.unlink()
    with pytest.raises(EntryRejected):
        verify_manifest(tmp_path, m)
