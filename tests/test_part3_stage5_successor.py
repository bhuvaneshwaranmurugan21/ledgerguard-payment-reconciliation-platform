from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from types import ModuleType
from typing import Any

import pytest
from test_part3_stage5_admission import fixture

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard.stage3.errors import Stage3Rejected
from ledgerguard_control import successor_job
from ledgerguard_control.contracts import ControlRejected, job_arguments
from ledgerguard_control.glue_arguments import (
    GlueServiceContract,
    adapt_glue_arguments,
    admitted_from_glue_arguments,
    release_from_glue_arguments,
)
from ledgerguard_control.successor_writer import candidate_manifest, materialize_candidates_uri

JOB_RUN = "jr_" + "9" * 64


def invocation() -> tuple[list[str], Any, GlueServiceContract]:
    value, _, _, release = fixture()
    job = value["job"]
    bucket = "ledgerguard-p3-857229544428-operation-01"
    job.update(
        workload_bucket=bucket,
        input_prefix="s3://" + bucket + "/runs/run-test1/inputs",
        candidate_output_prefix=(
            "s3://" + bucket + "/runs/run-test1/attempts/attempt-1/candidates"
        ),
        evidence_prefix="s3://" + bucket + "/runs/run-test1/attempts/attempt-1/evidence",
    )
    admitted = job_arguments(job)
    contract = GlueServiceContract(
        "ledgerguard-p3-operation-01-reconciliation",
        bucket,
        "/ledgerguard-p3-operation-01/glue",
        release,
    )
    values = {key.replace("_", "-"): item for key, item in asdict(admitted).items()}
    values.update(contract.configured())
    values["JOB_RUN_ID"] = JOB_RUN
    argv = [item for key, item in values.items() for item in (f"--{key}", item)]
    return argv, admitted, contract


def summaries() -> dict[str, dict[str, Any]]:
    return {
        "transactions": {"count": 3},
        "settlements": {"count": 2},
        "bank-allocations": {"count": 1},
    }


def test_successor_invocation_reconstructs_nonoverridable_release() -> None:
    argv, admitted, contract = invocation()
    assert release_from_glue_arguments(argv) == contract.release
    assert admitted_from_glue_arguments(argv) == admitted
    assert successor_job._service_contract(argv) == contract
    assert adapt_glue_arguments(argv, contract, admitted) == (admitted, JOB_RUN)


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--release-manifest-sha256", "bad"),
        ("--runtime-source-commit", "f" * 39),
        ("--runtime-source-tree", "f" * 39),
        ("--runtime-package-sha256", "f" * 63),
        ("--runtime-script-sha256", "f" * 63),
        ("--runtime-wheels-sha256", "f" * 63),
    ],
)
def test_successor_release_identity_rejections(flag: str, value: str) -> None:
    argv, _, _ = invocation()
    argv[argv.index(flag) + 1] = value
    with pytest.raises(ControlRejected, match="release identity"):
        release_from_glue_arguments(argv)


def test_successor_missing_business_and_deployment_bucket_reject() -> None:
    argv, _, _ = invocation()
    start = argv.index("--run-id")
    with pytest.raises(ControlRejected, match="business"):
        admitted_from_glue_arguments(argv[:start] + argv[start + 2 :])
    argv, _, _ = invocation()
    index = argv.index("--workload-bucket") + 1
    original = argv[index]
    argv[index] = "ledgerguard-other"
    for name in (
        "--TempDir",
        "--additional-python-modules",
        "--input-prefix",
        "--candidate-output-prefix",
        "--evidence-prefix",
    ):
        position = argv.index(name) + 1
        argv[position] = argv[position].replace(original, argv[index])
    with pytest.raises(Stage3Rejected, match="deployment-bound"):
        successor_job._service_contract(argv)


def test_v2_candidate_manifest_binds_terminal_job() -> None:
    physical = [
        {"path": "transactions/part.parquet", "size_bytes": 1, "sha256": "a" * 64}
    ]
    manifest, digest = candidate_manifest(
        summaries(), physical, "run-test1", "attempt-1", "control-1", JOB_RUN
    )
    assert manifest["schema_version"] == "2.0"
    assert manifest["glue_job_run_id"] == JOB_RUN
    assert manifest["physical_files"] == physical
    assert manifest["logical_sha256"] == digest
    with pytest.raises(Stage3Rejected, match="job run identity"):
        candidate_manifest(
            summaries(), physical, "run-test1", "attempt-1", "control-1", "invalid"
        )


@dataclass
class Result:
    root: str
    transaction_count: int
    settlement_count: int
    allocation_count: int
    logical_sha256: str
    candidate_manifest_sha256: str


class Expression:
    def alias(self, name: str) -> Expression:
        return self


class Writer:
    def __init__(self, calls: list[tuple[str, str]]):
        self.calls = calls

    def mode(self, value: str) -> Writer:
        assert value == "errorifexists"
        return self

    def parquet(self, location: str) -> None:
        self.calls.append(("parquet", location))

    def text(self, location: str) -> None:
        self.calls.append(("text", location))


class Frame:
    def __init__(self, spark: Spark, calls: list[tuple[str, str]]):
        self.sparkSession = spark
        self.write = Writer(calls)

    def select(self, *values: Any) -> Frame:
        return self

    def coalesce(self, value: int) -> Frame:
        assert value == 1
        return self

    def collect(self) -> list[dict[str, Any]]:
        return [{"path": "unused", "size_bytes": 1, "sha256": "a" * 64}]


class Reader:
    def __init__(self, spark: Spark, calls: list[tuple[str, str]]):
        self.spark = spark
        self.calls = calls

    def parquet(self, location: str) -> Frame:
        return Frame(self.spark, self.calls)

    def format(self, value: str) -> Reader:
        assert value == "binaryFile"
        return self

    def load(self, locations: list[str]) -> Frame:
        assert len(locations) == 3
        return Frame(self.spark, self.calls)


class Spark:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.read = Reader(self, self.calls)

    def range(self, value: int) -> Frame:
        assert value == 1
        return Frame(self, self.calls)


def install_fake_spark_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = ModuleType("pyspark.sql")
    functions = ModuleType("pyspark.sql.functions")
    functions.col = lambda value: Expression()  # type: ignore[attr-defined]
    functions.sha2 = lambda value, bits: Expression()  # type: ignore[attr-defined]
    functions.lit = lambda value: Expression()  # type: ignore[attr-defined]
    sql.functions = functions  # type: ignore[attr-defined]
    pyspark = ModuleType("pyspark")
    pyspark.sql = sql  # type: ignore[attr-defined]
    pipeline = ModuleType("ledgerguard.stage3.spark_pipeline")
    pipeline.MaterializationResult = Result  # type: ignore[attr-defined]
    pipeline._logical_summary = lambda frame: {"count": 1}  # type: ignore[attr-defined]
    pipeline._physical_inventory = lambda prefix, rows: [  # type: ignore[attr-defined]
        {"path": "transactions/part.parquet", "size_bytes": 1, "sha256": "a" * 64}
    ]
    monkeypatch.setitem(sys.modules, "pyspark", pyspark)
    monkeypatch.setitem(sys.modules, "pyspark.sql", sql)
    monkeypatch.setitem(sys.modules, "pyspark.sql.functions", functions)
    monkeypatch.setitem(sys.modules, "ledgerguard.stage3.spark_pipeline", pipeline)


def test_successor_writer_emits_data_manifest_then_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_spark_modules(monkeypatch)
    spark = Spark()
    frames = type(
        "Candidates",
        (),
        {
            "transactions": Frame(spark, spark.calls),
            "settlements": Frame(spark, spark.calls),
            "allocations": Frame(spark, spark.calls),
        },
    )()
    result = materialize_candidates_uri(
        frames,
        "s3://bucket/candidates",
        "run-test1",
        "attempt-1",
        "control-1",
        JOB_RUN,
    )
    assert result.transaction_count == result.settlement_count == result.allocation_count == 1
    assert [kind for kind, _ in spark.calls] == ["parquet"] * 3 + ["text"] * 2
    assert spark.calls[-1][1].endswith("/completion")
    with pytest.raises(Stage3Rejected, match="canonical"):
        materialize_candidates_uri(
            frames, "file:/tmp/candidates", "run-test1", "attempt-1", "control-1", JOB_RUN
        )


def test_successor_main_wires_strict_parse_and_stops_spark(monkeypatch: pytest.MonkeyPatch) -> None:
    argv, admitted, _ = invocation()

    class Runtime:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    runtime = Runtime()
    job = ModuleType("ledgerguard.stage3.job")
    job._spark = lambda: runtime  # type: ignore[attr-defined]
    job._managed_inputs = lambda spark, arguments: "inputs"  # type: ignore[attr-defined]
    pipeline = ModuleType("ledgerguard.stage3.spark_pipeline")
    pipeline.reconcile_sources = lambda spark, inputs: "candidates"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ledgerguard.stage3.job", job)
    monkeypatch.setitem(sys.modules, "ledgerguard.stage3.spark_pipeline", pipeline)
    called: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        successor_job, "materialize_candidates_uri", lambda *args: called.append(args)
    )
    assert successor_job.main(argv) == 0
    assert called[0][2:5] == (
        admitted.run_id,
        admitted.attempt_id,
        admitted.control_record_identity,
    )
    assert called[0][-1] == JOB_RUN
    assert runtime.stopped

    runtime.stopped = False
    pipeline.reconcile_sources = lambda spark, inputs: (_ for _ in ()).throw(RuntimeError("x"))  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="x"):
        successor_job.main(argv)
    assert runtime.stopped


def test_successor_script_is_a_real_entrypoint() -> None:
    source = open("glue/ledgerguard_stage5_job.py", encoding="utf-8").read()
    compile(source, "ledgerguard_stage5_job.py", "exec")
    assert "ledgerguard_control.successor_job import main" in source
    assert canonical_bytes({"entrypoint": "ledgerguard_control.successor_job:main"})
