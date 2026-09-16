#!/usr/bin/env python3
"""Independently inspect a sanitized Part 3 Stage 6 artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.part3_stage6.artifact import inspect_artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_artifact(args.artifact), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
