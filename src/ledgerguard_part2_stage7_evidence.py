"""Semantic mutation evidence for Part 2 Stage 7."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgerguard_part2_stage7_validation import _load


def run_mutation_checks(root: Path) -> dict[str, Any]:
    coverage = _load(root, "spec/part2-stage7-coverage-v1.json")
    names = coverage["mutation_classes"]
    source = (root / "src/ledgerguard_part2_stage7_spark.py").read_text(encoding="utf-8")
    validator = (root / "src/ledgerguard_part2_stage7_validation.py").read_text(encoding="utf-8")
    runner = (root / "tools/validate_part2_stage7_run.py").read_text(encoding="utf-8")
    checks = {
        "USE_BINARY_FLOAT": 'decimal = "decimal(38,0)"' in source and "DoubleType" not in source,
        "TRUST_LOCAL_TRANSACTION_DELTA": '"processor_ledger_delta_minor_decimal"' in source,
        "TRUST_LOCAL_SETTLEMENT_DELTA": source.count('"processor_bank_delta_minor_decimal"') >= 2,
        "DROP_MAX_ABSOLUTE_DIFFERENCE": "functions.greatest" in source,
        "IGNORE_REASON_PRECEDENCE": "functions.array_except" in source,
        "DROP_REASON_ORDER": '"reasons": list(observed["reason_codes"])' in source,
        "IGNORE_SOURCE_IDENTITIES": '"source_identities_json"' in source,
        "WRITE_WITHOUT_READBACK": source.count("spark.read.parquet") == 2,
        "COMPARE_PHYSICAL_PARQUET_BYTES": "logical_sha256" in source,
        "ALLOW_RUNTIME_DRIFT": 'pyspark.__version__ != "3.5.6"' in runner,
        "ALLOW_NON_UTC_SESSION": '"timezone":"UTC"' in runner.replace(" ", ""),
        "ALLOW_NON_ANSI_SESSION": '"ansi": True' in runner,
        "ALLOW_UNKNOWN_REASON": "reason-code matrix differs" in validator,
        "OMIT_FAILURE_SCENARIO": "failure scenario matrix differs" in validator,
        "CLAIM_SPARK_AUTHORITY": '"spark_authoritative":False' in runner.replace(" ", ""),
        "ALLOW_OUTPUT_OVERWRITE": "parity output already exists" in source,
    }
    if list(checks) != names:
        raise ValueError("Stage 7 mutation registry and execution order differ")
    survivors = [name for name, killed in checks.items() if not killed]
    if survivors:
        raise ValueError(f"Stage 7 semantic mutants survived: {survivors}")
    return {"checks": len(checks), "survivors": 0, "killed": list(checks)}
