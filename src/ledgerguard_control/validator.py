"""AWS Lambda validator entrypoint for admitted Stage 5 transitions."""

from __future__ import annotations

from typing import Any

from .aws_objects import S3VersionedObjects
from .contracts import ControlRejected
from .execution import HandlerConfig, validate_execution
from .objects import VersionedObjects
from .runtime import aws_client, load_config


def _objects(_config: HandlerConfig) -> VersionedObjects:
    return S3VersionedObjects(aws_client("s3"))


def handler(event: Any, _context: Any) -> dict[str, Any]:
    """Admit only implemented validator actions; unknown work cannot fail open."""
    if type(event) is not dict or event.get("action") != "validate-execution":
        raise ControlRejected("unsupported validator action")
    config = load_config()
    return validate_execution(event, config, _objects(config))
