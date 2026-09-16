#!/usr/bin/env python3
"""Adjudicate a private Organizations observation against a private IAM packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.part3_stage6.organization_scp import (
    adjudicate_service_control_policies,
    successor_required_requests,
    validate_observation_archive,
)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--observation-sha256", required=True)
    parser.add_argument("--observation-source-commit", required=True)
    parser.add_argument("--observation-source-tree", required=True)
    parser.add_argument("--preflight-anchor-sha256", required=True)
    parser.add_argument("--successor-packet", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    observation = validate_observation_archive(
        arguments.observation,
        archive_sha256=arguments.observation_sha256,
        source_commit=arguments.observation_source_commit,
        source_tree=arguments.observation_source_tree,
        anchor_preflight_failure_sha256=arguments.preflight_anchor_sha256,
    )
    packet = _load_object(arguments.successor_packet, "successor packet")
    if packet.get("classification") != "PRIVATE_DESIRED_NOT_INSTALLED_NOT_EFFECTIVELY_VERIFIED":
        raise ValueError("successor packet classification differs")
    if packet.get("stage6_source") != {
        "commit": arguments.source_commit,
        "tree": arguments.source_tree,
    } or any(
        re.fullmatch(r"[0-9a-f]{40}", value) is None
        for value in (arguments.source_commit, arguments.source_tree)
    ):
        raise ValueError("successor packet source binding differs")
    adjudication = adjudicate_service_control_policies(
        observation, successor_required_requests(packet)
    )
    if arguments.output.exists():
        raise ValueError("SCP adjudication output already exists")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": "ledgerguard.part3-stage6-organization-scp-adjudication.v1",
        "classification": "PRIVATE_ORGANIZATION_SCP_ADJUDICATION",
        "source": {"commit": arguments.source_commit, "tree": arguments.source_tree},
        "observation_source": {
            "commit": arguments.observation_source_commit,
            "tree": arguments.observation_source_tree,
        },
        "bindings": {
            "observation_sha256": arguments.observation_sha256,
            "preflight_anchor_sha256": arguments.preflight_anchor_sha256,
            "successor_packet_sha256": hashlib.sha256(
                arguments.successor_packet.read_bytes()
            ).hexdigest(),
        },
        "adjudication": adjudication,
        "stage6_complete": False,
    }
    arguments.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
