"""AWS Lambda controller entrypoint for durable Stage 5 run registration."""

from __future__ import annotations

from typing import Any

from .aws_authority import DynamoDBAuthority
from .contracts import ControlRejected
from .execution import HandlerConfig, register_run
from .runtime import aws_client, load_config


def _authority(config: HandlerConfig) -> Any:
    return DynamoDBAuthority(aws_client("dynamodb"), config.table)


def handler(event: Any, _context: Any) -> dict[str, Any]:
    """Register one run or return its verified committed replay."""
    if type(event) is not dict or event.get("action") != "register-run":
        raise ControlRejected("unsupported controller action")
    config = load_config()
    return register_run(event, _authority(config))
