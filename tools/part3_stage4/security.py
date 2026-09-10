"""Bind a complete raw scan to a narrow, source-specific applicability review."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from tools.part3_stage4.resources import evaluate, parse_module


def assess(root: Path, raw_scan: bytes) -> dict[str, Any]:
    review = json.loads((root / "spec/part3-stage4-security-review-v1.json").read_text())
    if review["scope"] != "PART3_SYNTHETIC_ZERO_WORKLOAD_CONTROL_PLANE_ONLY":
        raise ValueError("security applicability scope changed")
    bindings = dict(review["source_hashes"])
    bindings["spec/part3-requirements-v1.json"] = review["master_requirements_sha256"]
    bindings["spec/part3-stage4-resource-controls-v1.json"] = review["resource_controls_sha256"]
    for name, digest in bindings.items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or (root / path).is_symlink():
            raise ValueError("unsafe security source binding")
        if sha256((root / path).read_bytes()).hexdigest() != digest:
            raise ValueError("security review source changed: " + name)
    evaluate(
        parse_module(root / "infra/part3"),
        json.loads((root / "spec/part3-stage4-resource-controls-v1.json").read_text()),
    )
    scan = json.loads(raw_scan)
    successes = 0
    failures = []
    for result in scan["Results"]:
        observed = {"PASS": 0, "FAIL": 0}
        for finding in result.get("Misconfigurations", []):
            status = finding["Status"]
            if status not in observed:
                raise ValueError("unknown or unexecuted security finding status")
            observed[status] += 1
            if status == "FAIL":
                failures.append(
                    (finding["ID"], result["Target"], finding["CauseMetadata"]["Resource"])
                )
        summary = result["MisconfSummary"]
        if observed != {"PASS": summary["Successes"], "FAIL": summary["Failures"]}:
            raise ValueError("security scan summary does not match retained findings")
        successes += observed["PASS"]
    decisions = [(row["id"], row["target"], row["resource"]) for row in review["decisions"]]
    if (
        not successes
        or len(decisions) != len(set(decisions))
        or sorted(failures) != sorted(decisions)
    ):
        raise ValueError("raw scanner findings differ from the exact reviewed set")
    return {
        "classification": "SOURCE_BOUND_APPLICABILITY_REVIEW",
        "raw_scanner_successes": successes,
        "raw_scanner_failures": len(failures),
        "reviewed_inapplicable": review["decisions"],
        "unreviewed_failures": 0,
        "raw_scan_sha256": sha256(raw_scan).hexdigest(),
        "review_sha256": sha256(
            (root / "spec/part3-stage4-security-review-v1.json").read_bytes()
        ).hexdigest(),
        "scope": review["scope"],
        "scanner_itself_all_green": False,
        "aws_controls_verified": False,
        "production_security_claim": False,
    }
