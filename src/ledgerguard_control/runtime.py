"""Deployment-bound Lambda runtime bootstrap.

The handler configuration is supplied as canonical JSON plus its independently
qualified digest.  AWS reserved environment variables are ignored, while the
workload bucket and control table must match the derived operation identity.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from typing import Any

from .contracts import ControlRejected
from .execution import REGION, HandlerConfig, parse_config


def load_config(environment: Mapping[str, str] | None = None) -> HandlerConfig:
    """Load and verify the one deployment-controlled handler configuration."""
    values = os.environ if environment is None else environment
    raw = values.get("HANDLER_CONFIG_JSON")
    digest = values.get("HANDLER_CONFIG_SHA256")
    if type(raw) is not str or type(digest) is not str:
        raise ControlRejected("handler configuration environment is incomplete")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeError as error:
        raise ControlRejected("handler configuration environment is invalid") from error
    config = parse_config(encoded, digest)
    if values.get("WORKLOAD_BUCKET") != config.bucket:
        raise ControlRejected("runtime workload bucket differs from configuration")
    if values.get("CONTROL_TABLE") != config.table:
        raise ControlRejected("runtime control table differs from configuration")
    return config


def aws_client(service: str) -> Any:
    """Construct one regional AWS SDK client from the Lambda-provided SDK."""
    if service not in {"dynamodb", "glue", "s3"}:
        raise ControlRejected("unsupported runtime AWS client")
    boto3 = importlib.import_module("boto3")
    return boto3.client(service, region_name=REGION)
