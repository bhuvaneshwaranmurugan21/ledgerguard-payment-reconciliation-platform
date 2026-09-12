"""AWS Lambda validator entrypoint for admitted Stage 5 transitions."""

from __future__ import annotations

from typing import Any

from .aws_objects import S3ImmutableObjects, S3VersionedObjects
from .candidate_validation import validate_candidate
from .contracts import ControlRejected
from .execution import HandlerConfig, validate_execution
from .objects import VersionedObjects
from .runtime import aws_client, load_config


def _objects(_config: HandlerConfig) -> VersionedObjects:
    return S3VersionedObjects(aws_client("s3"))


def _candidate_dependencies(config: HandlerConfig) -> tuple[Any, Any]:
    return S3ImmutableObjects(aws_client("s3"), config.bucket), aws_client("glue")


def handler(event: Any, _context: Any) -> dict[str, Any]:
    """Admit only implemented validator actions; unknown work cannot fail open."""
    if type(event) is not dict or event.get("action") not in {
        "validate-execution",
        "validate-candidate",
    }:
        raise ControlRejected("unsupported validator action")
    config = load_config()
    if event["action"] == "validate-execution":
        return validate_execution(event, config, _objects(config))
    objects, glue = _candidate_dependencies(config)
    return validate_candidate(event, config, objects, glue, objects)
