from __future__ import annotations

from copy import deepcopy

import pytest

from tools.part3_stage6.relationships import REQUIRED_REFERENCES, validate_relationships


def plan() -> dict[str, object]:
    grouped: dict[str, dict[str, object]] = {}
    for (address, expression), reference in REQUIRED_REFERENCES.items():
        grouped.setdefault(address, {})[expression] = {"references": [reference]}
    return {
        "configuration": {
            "root_module": {
                "resources": [
                    {"address": address, "expressions": expressions}
                    for address, expressions in grouped.items()
                ]
            }
        }
    }


def test_exact_computed_relationships_pass() -> None:
    assert REQUIRED_REFERENCES[("aws_s3_bucket_policy.workload", "bucket")] == (
        "aws_s3_bucket.workload.id"
    )
    assert REQUIRED_REFERENCES[("aws_s3_bucket_policy.workload", "policy")] == (
        "aws_s3_bucket.workload.arn"
    )
    assert REQUIRED_REFERENCES[("aws_iam_role_policy.runtime", "role")] == ("aws_iam_role.runtime")
    result = validate_relationships(plan())
    assert result["relationships_validated"] == len(REQUIRED_REFERENCES)
    assert result["stage6_complete"] is False


def test_missing_resource_and_reference_fail() -> None:
    changed = plan()
    changed["configuration"]["root_module"]["resources"].pop()  # type: ignore[index,union-attr]
    with pytest.raises(ValueError, match="resource missing"):
        validate_relationships(changed)
    changed = deepcopy(plan())
    first = changed["configuration"]["root_module"]["resources"][0]  # type: ignore[index]
    next(iter(first["expressions"].values()))["references"] = []  # type: ignore[union-attr,index]
    with pytest.raises(ValueError, match="required relationship"):
        validate_relationships(changed)


def test_duplicate_resource_and_malformed_references_fail() -> None:
    changed = plan()
    changed["configuration"]["root_module"]["resources"].append(  # type: ignore[index,union-attr]
        deepcopy(changed["configuration"]["root_module"]["resources"][0])  # type: ignore[index]
    )
    with pytest.raises(ValueError, match="identity invalid"):
        validate_relationships(changed)
    changed = plan()
    first = changed["configuration"]["root_module"]["resources"][0]  # type: ignore[index]
    next(iter(first["expressions"].values()))["references"] = "not-an-array"  # type: ignore[union-attr,index]
    with pytest.raises(ValueError, match="references invalid"):
        validate_relationships(changed)


def test_relationship_containers_are_strict() -> None:
    with pytest.raises(ValueError, match="configuration must"):
        validate_relationships({"configuration": []})
    changed = plan()
    changed["configuration"]["root_module"]["resources"] = {}  # type: ignore[index]
    with pytest.raises(ValueError, match="resources missing"):
        validate_relationships(changed)
    changed = plan()
    first = changed["configuration"]["root_module"]["resources"][0]  # type: ignore[index]
    first["expressions"] = []  # type: ignore[index]
    with pytest.raises(ValueError, match="expressions"):
        validate_relationships(changed)
