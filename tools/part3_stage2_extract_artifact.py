#!/usr/bin/env python3
"""Validate GitHub artifact metadata and safely extract one immutable ZIP."""

from __future__ import annotations

import argparse
import json
import stat
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-artifact-id", required=True)
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text())
    if str(metadata.get("id")) != args.expected_artifact_id:
        raise ValueError("artifact ID differs")
    if metadata.get("expired") is not False:
        raise ValueError("artifact is expired or expiry is unknown")
    if metadata.get("name") != args.expected_name:
        raise ValueError("artifact name differs")
    if str(metadata.get("workflow_run", {}).get("id")) != args.expected_run_id:
        raise ValueError("artifact workflow run differs")
    archive_digest = sha256(args.archive.read_bytes()).hexdigest()
    if archive_digest != args.expected_archive_sha256:
        raise ValueError("artifact archive digest differs")
    if args.output.exists():
        raise ValueError("artifact extraction output already exists")
    args.output.mkdir(parents=True)
    with zipfile.ZipFile(args.archive) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)) or len(names) > 1000:
            raise ValueError("artifact ZIP member inventory is unsafe")
        if sum(member.file_size for member in members) > 50_000_000:
            raise ValueError("artifact ZIP is too large")
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.filename
                or stat.S_ISLNK(mode)
            ):
                raise ValueError("artifact ZIP path is unsafe")
            destination = args.output.joinpath(*path.parts)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))


if __name__ == "__main__":
    main()
