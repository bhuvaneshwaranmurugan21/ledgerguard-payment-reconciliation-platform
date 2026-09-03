#!/usr/bin/env python3
"""Validate one clean Part 2 Stage 1 environment and Spark/Parquet probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyspark
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType, LongType, StringType, StructField, StructType

from ledgerguard_part2_stage1 import validate_stage1
from ledgerguard_part2_stage1_evidence import parse_junit_counts


def execute(command: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def spark_probe(workspace: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("Spark probe requires exact CPython 3.11.13")
    if pyspark.__version__ != "3.5.6" or version("py4j") != "0.10.9.7":
        raise SystemExit("Spark dependency versions differ from the Stage 1 contract")
    if os.environ.get("PYSPARK_PYTHON") != sys.executable:
        raise SystemExit("Spark worker Python differs from the clean environment")
    if os.environ.get("PYSPARK_DRIVER_PYTHON") != sys.executable:
        raise SystemExit("Spark driver Python differs from the clean environment")
    java_line = subprocess.check_output(
        ["java", "-version"], stderr=subprocess.STDOUT, text=True
    ).splitlines()[0]
    if '"17.' not in java_line:
        raise SystemExit(f"Java major version is not 17: {java_line}")

    spark = (
        SparkSession.builder.master("local[1]")
        .appName("ledgerguard-part2-stage1")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.ansi.enabled", "true")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    try:
        if spark.version != "3.5.6":
            raise SystemExit(f"Spark runtime differs: {spark.version}")
        if spark.conf.get("spark.sql.ansi.enabled") != "true":
            raise SystemExit("Spark ANSI mode is disabled")
        if spark.conf.get("spark.sql.session.timeZone") != "UTC":
            raise SystemExit("Spark session timezone differs")
        schema = StructType(
            [
                StructField("event_id", StringType(), False),
                StructField("amount_minor", LongType(), False),
                StructField("quantity", LongType(), False),
                StructField("unit_price", DecimalType(38, 0), False),
            ]
        )
        rows = [
            ("evt-1", 9_007_199_254_740_991, 3, Decimal("3002399751580330")),
            ("evt-2", -9_007_199_254_740_000, -2, Decimal("4503599627370000")),
        ]
        calculated = (
            spark.createDataFrame(rows, schema=schema)
            .withColumn("recomputed_minor", F.col("quantity") * F.col("unit_price"))
            .withColumn(
                "delta_minor",
                F.col("amount_minor").cast(DecimalType(38, 0)) - F.col("recomputed_minor"),
            )
            .select("event_id", "amount_minor", "recomputed_minor", "delta_minor")
        )
        parquet_path = workspace / "parquet-proof"
        calculated.orderBy("event_id").write.mode("errorifexists").parquet(str(parquet_path))
        observed = [
            {
                "event_id": row["event_id"],
                "amount_minor": row["amount_minor"],
                "recomputed_minor": str(row["recomputed_minor"]),
                "delta_minor": str(row["delta_minor"]),
            }
            for row in spark.read.parquet(str(parquet_path)).orderBy("event_id").collect()
        ]
    finally:
        spark.stop()
    expected = [
        {
            "event_id": "evt-1",
            "amount_minor": 9007199254740991,
            "recomputed_minor": "9007199254740990",
            "delta_minor": "1",
        },
        {
            "event_id": "evt-2",
            "amount_minor": -9007199254740000,
            "recomputed_minor": "-9007199254740000",
            "delta_minor": "0",
        },
    ]
    if observed != expected:
        raise SystemExit(f"Spark/Parquet logical result differs: {observed}")
    logical_digest = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    toolchain = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "java_major": 17,
        "spark": pyspark.__version__,
        "py4j": version("py4j"),
        "spark_master": "local[1]",
        "ansi": True,
        "timezone": "UTC",
        "driver_worker_python_equal": True,
    }
    result = {
        "storage_format": "parquet",
        "row_count": len(observed),
        "logical_digest": logical_digest,
        "exact_long_and_decimal_assertions": "passed",
    }
    return toolchain, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    output = arguments.output.resolve()
    if root == output.parent or root in output.parents:
        raise SystemExit("Stage 1 run output must be outside the source repository")
    junit = output.parent / "pytest.xml"
    execute([sys.executable, "-m", "ruff", "format", "--check", "."], root)
    execute([sys.executable, "-m", "ruff", "check", "."], root)
    execute([sys.executable, "-m", "mypy", "src"], root)
    execute(
        [sys.executable, "-m", "pytest", "--junitxml", str(junit), str(root / "tests")],
        root,
    )
    workspace = Path(tempfile.mkdtemp(prefix="spark-probe-", dir=output.parent))
    try:
        toolchain, probe = spark_probe(workspace)
    finally:
        shutil.rmtree(workspace)
    frozen = validate_stage1(root)
    dependencies = sorted(
        line
        for line in subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze", "--all"], text=True
        ).splitlines()
        if not line.lower().startswith("ledgerguard")
    )
    result = {
        "actions": ["ruff-format", "ruff-check", "mypy", "pytest", "spark-parquet-probe"],
        "test_counts": parse_junit_counts(junit),
        "dependency_versions": dependencies,
        "authority": frozen,
        "toolchain": toolchain,
        "spark_probe": probe,
        "execution_boundary": {
            "aws_api_called": False,
            "aws_workflow_dispatched": False,
            "infrastructure_mutated": False,
        },
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
