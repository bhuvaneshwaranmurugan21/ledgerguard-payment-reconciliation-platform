"""AWS Lambda controller entrypoint for durable Stage 5 run registration."""

from __future__ import annotations

from typing import Any

from .aws_authority import DynamoDBAuthority
from .contracts import ControlRejected
from .execution import HandlerConfig, admit_attempt, register_run
from .runtime import aws_client, load_config


def _authority(config: HandlerConfig) -> Any:
    return DynamoDBAuthority(aws_client("dynamodb"), config.table)


def handler(event: Any, _context: Any) -> dict[str, Any]:
    """Dispatch only the implemented registration and attempt transitions."""
    if type(event) is not dict or event.get("action") not in {
        "register-run",
        "admit-attempt",
    }:
        raise ControlRejected("unsupported controller action")
    config = load_config()
    authority = _authority(config)
    if event["action"] == "register-run":
        return register_run(event, authority)
    return admit_attempt(event, authority)
