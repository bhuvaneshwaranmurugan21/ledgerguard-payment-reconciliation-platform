"""Inspect actual HCL against the reviewed Stage 4 resource-property contract.

This is source validation, not a substitute for native Terraform validation or
the later evaluator of real saved plans. Unresolved Stage 5 inputs stay unresolved.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO, cast


def parse_module(root: Path) -> dict[str, Any]:
    parse_hcl = cast(Callable[[TextIO], dict[str, Any]], importlib.import_module("hcl2").load)
    result: dict[str, Any] = {
        "resource": {},
        "locals": {},
        "variable": {},
        "terraform": [],
        "provider": {},
    }
    files = sorted(root.glob("*.tf"))
    if not files or list(root.glob("*.tf.json")):
        raise ValueError("missing HCL module or unadmitted JSON configuration")
    for path in files:
        if path.is_symlink():
            raise ValueError("configuration symlink is not admitted")
        with path.open() as stream:
            document = parse_hcl(stream)
        for kind, entries in document.items():
            if kind not in result:
                raise ValueError("unadmitted configuration block: " + kind)
            if kind == "terraform":
                result[kind].extend(entries)
                continue
            for entry in entries:
                for name, value in entry.items():
                    items = (
                        {f"{name}.{label}": body for label, body in value.items()}
                        if kind == "resource"
                        else {name: value}
                    )
                    for key, body in items.items():
                        if key in result[kind]:
                            raise ValueError("duplicate configuration identity: " + key)
                        result[kind][key] = body
    return result


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def evaluate(module: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Check every registered property; unknown managed resources fail closed."""
    resources = module["resource"]
    if set(resources) != set(contract["resource_templates"]):
        raise ValueError("resource template inventory differs")
    if set(module["variable"]) != set(contract["required_inputs"]):
        raise ValueError("input contract differs")
    for name, declaration in module["variable"].items():
        if "default" in declaration:
            raise ValueError("required input acquired a default: " + name)
    for name, body in resources.items():
        if "provisioner" in body or "connection" in body:
            raise ValueError("unadmitted side effect in resource: " + name)
        if set(body) != set(contract["resource_templates"][name]):
            raise ValueError("resource attribute set differs: " + name)
    identifiers: set[str] = set()
    for rule in contract["rules"]:
        identifier = rule["id"]
        if identifier in identifiers:
            raise ValueError("duplicate resource control: " + identifier)
        identifiers.add(identifier)
        current: Any = module
        try:
            for segment in rule["path"]:
                current = current[segment]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("missing resource control: " + identifier) from error
        if _encoded(current) != _encoded(rule["equals"]):
            raise ValueError("resource control differs: " + identifier)
    return {
        "classification": "PARSED_HCL_PROPERTY_VALIDATION",
        "controls_passed": len(identifiers),
        "managed_addresses": contract["managed_address_count"],
        "aws_execution": False,
        "native_terraform_validation_required": True,
        "stage5_artifacts_required": True,
    }


def expand_addresses(
    module: dict[str, Any], catalog: dict[str, Any], inventory: dict[str, Any]
) -> list[str]:
    """Expand only reviewed finite for_each expressions, without Terraform eval."""
    references = {
        "${local.log_names}": module["locals"]["log_names"],
        "${local.services}": module["locals"]["services"],
        "${local.runtime_statements}": module["locals"]["runtime_statements"],
        "${local.catalog.tables}": catalog["tables"],
        "${toset([validator, controller])}": {"validator": None, "controller": None},
    }
    addresses = []
    for address, body in module["resource"].items():
        if "count" in body:
            raise ValueError("unreviewed count expression")
        if "for_each" not in body:
            addresses.append(address)
            continue
        expression = body["for_each"]
        if expression not in references:
            raise ValueError("unreviewed resource expansion: " + expression)
        mapping = references[expression]
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("resource expansion is not a nonempty map")
        addresses.extend(address + "[" + json.dumps(key) + "]" for key in mapping)
    expected = [member["address"] for member in inventory["members"]]
    if (
        len(expected) != len(set(expected))
        or sorted(addresses) != sorted(expected)
        or len(addresses) != inventory["managed_address_count"]
    ):
        raise ValueError("expanded managed address inventory differs")
    return sorted(addresses)
