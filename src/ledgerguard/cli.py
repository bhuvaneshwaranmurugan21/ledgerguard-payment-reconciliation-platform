from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .simulator import simulate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledgerguard")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("simulate")
    cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = simulate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

