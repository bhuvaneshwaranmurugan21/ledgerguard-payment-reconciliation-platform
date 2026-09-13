"""AWS Lambda controller entrypoint for durable Stage 5 run registration."""

from __future__ import annotations

from typing import Any

from .aws_authority import DynamoDBAuthority
from .aws_objects import S3ImmutableObjects
from .contracts import ControlRejected
from .execution import HandlerConfig, admit_attempt, register_run
from .failure import record_failure
from .runtime import aws_client, load_config


def _authority(config: HandlerConfig) -> Any:
    return DynamoDBAuthority(aws_client("dynamodb"), config.table)


def _failure_dependencies(config: HandlerConfig) -> tuple[Any, Any]:
    s3 = aws_client("s3")
    return S3ImmutableObjects(s3, config.bucket), DynamoDBAuthority(
        aws_client("dynamodb"), config.table
    )


def handler(event: Any, _context: Any) -> dict[str, Any]:
    """Dispatch only implemented durable controller transitions."""
    if type(event) is not dict or event.get("action") not in {
        "register-run",
        "admit-attempt",
        "record-failure",
    }:
        raise ControlRejected("unsupported controller action")
    config = load_config()
    if event["action"] == "record-failure":
        objects, authority = _failure_dependencies(config)
        return record_failure(event, config, objects, objects, authority)
    authority = _authority(config)
    if event["action"] == "register-run":
        return register_run(event, authority)
    return admit_attempt(event, authority)
