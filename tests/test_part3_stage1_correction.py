from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_part2_stage3_admission import (
    bank_entry,
    build_bundle,
    journal,
    processor_event,
    processor_settlement,
    signed_record,
)

from ledgerguard.reconciliation import (
    AdmissionRejected,
    FinalizationStore,
    admit_bundle,
    canonical_json_bytes,
    canonical_sha256,
    reconcile_settlements,
    reconcile_transactions,
)
from ledgerguard.reconciliation.correction import correction_digest

ROOT = Path(__file__).resolve().parents[1]
TIME = "2026-09-06T00:00:00Z"


def correction_journal(identifier: str, amount: int, settlement: bool = False) -> dict[str, Any]:
    row = journal(journal_id=identifier)
    for posting in row["postings"]:
        posting["amount_minor"] = amount
    if settlement:
        row.pop("payment_id")
        row.update(
            entry_type="SETTLEMENT", settlement_id="settlement-1", settlement_cycle="cycle-1"
        )
        row["postings"][0]["side"] = "CREDIT"
        row["postings"][1]["side"] = "DEBIT"
    return signed_record(row)


def scenario(
    tmp_path: Path,
    amount: int = 100,
    policy: dict[str, Any] | None = None,
    *,
    late: bool = False,
    source_suffix: str = "",
) -> dict[str, Any]:
    families = {
        "PROCESSOR_EVENTS": [processor_event(amount_minor=1000)],
        "PROCESSOR_SETTLEMENTS": [
            processor_settlement(gross_minor=1000, fee_minor=0, reported_net_minor=1000)
        ],
        "LEDGER_JOURNALS": [
            correction_journal("original-txn" + source_suffix, 900),
            correction_journal("original-stl" + source_suffix, 900, True),
        ],
        "BANK_ENTRIES": [bank_entry(amount_minor=1000)],
    }
    if late:
        families["PROCESSOR_SETTLEMENTS"].append(
            processor_settlement(
                source_record_id="late-settlement",
                settlement_id="settlement-2",
                gross_minor=1000,
                fee_minor=0,
                reported_net_minor=1000,
            )
        )
        late_journal = correction_journal("original-late", 1000, True)
        late_journal["settlement_id"] = "settlement-2"
        families["LEDGER_JOURNALS"].append(signed_record(late_journal))
    store = FinalizationStore(ROOT, tmp_path / "store")
    pb, mb, objects, _ = build_bundle(families, run_id="correction-run-1")
    first_admitted = admit_bundle(ROOT, pb, mb, objects)
    first = store.finalize(
        attempt_id="correction-attempt-1",
        expected_head=None,
        created_at=TIME,
        transaction_batch=reconcile_transactions(first_admitted),
        settlement_batch=reconcile_settlements(first_admitted),
    )
    prior, tx, st = store.load_states()
    additions = deepcopy(families)
    additions["LEDGER_JOURNALS"] += [
        correction_journal("adjustment-txn", amount),
        correction_journal("adjustment-stl", amount, True),
    ]
    if late:
        additions["BANK_ENTRIES"].append(
            bank_entry(
                bank_record_id="late-bank", settlement_reference="settlement-2", amount_minor=1000
            )
        )
    pb, mb, objects, manifest = build_bundle(
        additions, policy_value=policy, run_id="correction-run-2"
    )
    admitted = admit_bundle(ROOT, pb, mb, objects, prior_state=prior)
    import json

    inputs = {
        "policy": json.loads(pb),
        "manifest": manifest,
        "object_encoding": "base64",
        "objects": {key: b64encode(raw).decode("ascii") for key, raw in objects.items()},
    }
    items = []
    for proof_ref, case_ref in zip(first.proofs, first.cases, strict=True):
        proof, case = (
            store.read_proof(proof_ref.object_sha256),
            store.read_case_revision(case_ref.object_sha256),
        )
        key = proof["reconciliation_key"]

        def refs(records: Any, prefix: str, key: str = key) -> list[dict[str, Any]]:
            return sorted(
                [
                    {"identity": list(row.source_identity), "business_sha256": row.business_sha256}
                    for row in records
                    if row.family == "LEDGER_JOURNAL"
                    and row.reconciliation_key == key
                    and row.source_identity[-1].startswith(prefix)
                ],
                key=lambda row: row["identity"],
            )

        if not refs(admitted.records, "adjustment"):
            continue
        items.append(
            {
                "reconciliation_key": key,
                "prior_proof_id": proof["proof_id"],
                "prior_case_revision_sha256": case["case_revision_sha256"],
                "initial_exception_proof_id": case["initial_exception_proof_id"],
                "prior_policy": json.loads(first_admitted.policy_canonical_bytes),
                "original_sources": refs(first_admitted.records, "original"),
                "corrective_sources": refs(admitted.records, "adjustment"),
            }
        )
    correction = {
        "schema_version": "1.0",
        "kind": "BALANCED_JOURNAL_ADJUSTMENT",
        "correction_id": "correction-1",
        "expected_head": first.commit_sha256,
        "manifest_sha256": admitted.manifest_sha256,
        "policy_sha256": admitted.policy_sha256,
        "items": sorted(items, key=lambda row: row["reconciliation_key"]),
    }
    correction["correction_sha256"] = correction_digest(correction)
    args = {
        "attempt_id": "correction-attempt-2",
        "expected_head": first.commit_sha256,
        "created_at": TIME,
        "transaction_batch": reconcile_transactions(admitted, tx),
        "settlement_batch": reconcile_settlements(admitted, st),
        "correction": correction,
        "correction_inputs": inputs,
    }
    return {
        "store": store,
        "first": first,
        "args": args,
        "admitted": admitted,
        "prior": prior,
        "tx": tx,
        "st": st,
        "families": families,
    }


def inventory(store: FinalizationStore) -> dict[str, str]:
    return {
        p.relative_to(store.root).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted([*store.root.rglob("*.json"), store.root / "control/HEAD"])
    }


def observation(name: str, value: Any) -> None:
    destination = os.environ.get("STAGE1_OBSERVATIONS")
    if destination:
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_bytes(canonical_json_bytes(value))


def test_two_grains_correction_is_persisted_and_history_verified(tmp_path: Path) -> None:
    case = scenario(tmp_path)
    store = case["store"]
    before = {p.name: p.read_bytes() for p in (store.root / "objects").iterdir()}
    receipt = store.finalize(**case["args"])
    golden = json.loads((ROOT / "spec/part3-stage1-correction-golden-v1.json").read_bytes())
    assert len(receipt.proofs) == len(receipt.cases) == 2
    for proof_ref, case_ref in zip(receipt.proofs, receipt.cases, strict=True):
        proof = store.read_proof(proof_ref.object_sha256)
        revision = store.read_case_revision(case_ref.object_sha256)
        assert proof["status"] == "MATCHED"
        field = (
            "transaction_totals"
            if proof_ref.reconciliation_key.startswith("txn:")
            else "settlement_totals"
        )
        assert proof["totals"] == golden[field]
        prior_proof = store.read_proof(
            next(
                p.object_sha256
                for p in case["first"].proofs
                if p.reconciliation_key == proof_ref.reconciliation_key
            )
        )
        prior_case = store.read_case_revision(
            next(
                p.object_sha256
                for p in case["first"].cases
                if p.reconciliation_key == case_ref.reconciliation_key
            )
        )
        assert proof["prior_proof_id"] == prior_proof["proof_id"]
        assert revision["case_id"] == prior_case["case_id"]
        assert revision["prior_case_revision_id"] == prior_case["case_revision_sha256"]
        assert revision["initial_exception_proof_id"] == prior_proof["proof_id"]
        assert revision["proof_id"] == proof["proof_id"]
        assert revision["status"] == "RESOLVED_BY_CORRECTION"
        assert revision["revision"] == 2
    assert all((store.root / "objects" / name).read_bytes() == raw for name, raw in before.items())
    assert FinalizationStore(ROOT, store.root).verify_history() is not None
    assert store.load_states()[0].source_records
    assert store.finalize(**case["args"]) == receipt
    observation(
        "golden-correction",
        {"inventory": inventory(store), "receipt": receipt.value(), "expected": golden},
    )


def test_partial_correction_remains_open(tmp_path: Path) -> None:
    case = scenario(tmp_path, 40)
    store = case["store"]
    receipt = store.finalize(**case["args"])
    assert all(
        store.read_proof(p.object_sha256)["totals"]["difference_minor"] == 60
        for p in receipt.proofs
    )
    assert all(store.read_case_revision(c.object_sha256)["status"] == "OPEN" for c in receipt.cases)


@pytest.mark.parametrize(
    "field", ["prior_proof_id", "prior_case_revision_sha256", "initial_exception_proof_id"]
)
def test_wrong_predecessor_is_not_authoritative(tmp_path: Path, field: str) -> None:
    case = scenario(tmp_path)
    correction = case["args"]["correction"]
    correction["items"][0][field] = "0" * 64
    correction["correction_sha256"] = correction_digest(correction)
    with pytest.raises(AdmissionRejected, match="predecessor differs"):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_context_changes_change_request_identity(tmp_path: Path) -> None:
    case = scenario(tmp_path)
    receipt = case["store"].finalize(**case["args"])
    changed = deepcopy(case["args"])
    changed["correction"]["correction_id"] = "another-correction"
    changed["correction"]["correction_sha256"] = correction_digest(changed["correction"])
    from ledgerguard.reconciliation import FinalizationRejected

    with pytest.raises(FinalizationRejected, match="different request"):
        case["store"].finalize(**changed)
    assert case["store"].read_head() == receipt.commit_sha256


def recovery_args(case: dict[str, Any], attempt: str | None = None) -> dict[str, Any]:
    admitted, args = case["admitted"], case["args"]
    return {
        "attempt_id": attempt or args["attempt_id"],
        "expected_head": args["expected_head"],
        "created_at": args["created_at"],
        "run_id": admitted.run_id,
        "policy_version": admitted.policy_version,
        "policy_sha256": admitted.policy_sha256,
        "manifest_sha256": admitted.manifest_sha256,
        "correction": args["correction"],
        "correction_inputs": args["correction_inputs"],
    }


def test_new_attempt_retry_has_no_second_effect(tmp_path: Path) -> None:
    case = scenario(tmp_path)
    store = case["store"]
    receipt = store.finalize(**case["args"])
    before = {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*.json")}
    assert store.recover_attempt(**recovery_args(case, "new-attempt")) == receipt
    assert store.finalize(**{**case["args"], "attempt_id": "another-attempt"}) == receipt
    assert before == {
        str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*.json")
    }
    assert store.read_head() == receipt.commit_sha256


def test_recovery_cannot_hide_attempt_identity_conflict(tmp_path: Path) -> None:
    from ledgerguard.reconciliation import FinalizationRejected

    case = scenario(tmp_path)
    receipt = case["store"].finalize(**case["args"])
    with pytest.raises(FinalizationRejected, match="correction context differs"):
        case["store"].recover_attempt(**recovery_args(case, "correction-attempt-1"))
    changed = recovery_args(case)
    changed["created_at"] = "2026-09-07T00:00:00Z"
    with pytest.raises(FinalizationRejected, match="different inputs"):
        case["store"].recover_attempt(**changed)
    assert case["store"].read_head() == receipt.commit_sha256


@pytest.mark.parametrize(
    "field", ["run_id", "policy_version", "policy_sha256", "manifest_sha256", "expected_head"]
)
def test_new_attempt_retry_checks_all_metadata(tmp_path: Path, field: str) -> None:
    case = scenario(tmp_path)
    receipt = case["store"].finalize(**case["args"])
    args = recovery_args(case, "new-attempt")
    args[field] = "0" * 64
    with pytest.raises(AdmissionRejected, match="retry metadata differs"):
        case["store"].recover_attempt(**args)
    assert case["store"].read_head() == receipt.commit_sha256


def test_reused_correction_id_with_changed_provenance_rejects(tmp_path: Path) -> None:
    case = scenario(tmp_path)
    receipt = case["store"].finalize(**case["args"])
    args = deepcopy(case["args"])
    args["attempt_id"] = "new-attempt"
    args["correction"]["items"][0]["original_sources"][0]["business_sha256"] = "0" * 64
    args["correction"]["correction_sha256"] = correction_digest(args["correction"])
    with pytest.raises(AdmissionRejected, match="correction identity reused"):
        case["store"].finalize(**args)
    assert case["store"].read_head() == receipt.commit_sha256


@pytest.mark.parametrize(
    "alteration",
    [
        "version",
        "digest",
        "duplicate-key",
        "duplicate-source",
        "unsorted",
        "extra",
        "missing-policy",
        "operator-state",
    ],
)
def test_companion_shape_and_canonical_identity_fail_closed(
    tmp_path: Path, alteration: str
) -> None:
    case = scenario(tmp_path)
    c = case["args"]["correction"]
    if alteration == "version":
        c["schema_version"] = "3.0"
    elif alteration == "duplicate-key":
        c["items"].append(deepcopy(c["items"][0]))
    elif alteration == "duplicate-source":
        c["items"][0]["original_sources"] *= 2
    elif alteration == "unsorted":
        c["items"].reverse()
    elif alteration == "extra":
        c["unbound"] = True
    elif alteration == "missing-policy":
        c["items"][0].pop("prior_policy")
    elif alteration == "operator-state":
        c["status"] = "WRITTEN_OFF"
    c["correction_sha256"] = "0" * 64 if alteration == "digest" else correction_digest(c)
    with pytest.raises(AdmissionRejected):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


@pytest.mark.parametrize("field", ["original_sources", "corrective_sources"])
@pytest.mark.parametrize("alteration", ["missing", "digest", "wrong-key"])
def test_exact_source_targets_are_required(tmp_path: Path, field: str, alteration: str) -> None:
    case = scenario(tmp_path)
    c = case["args"]["correction"]
    row = c["items"][0][field][0]
    if alteration == "missing":
        row["identity"][-1] = "does-not-exist"
    elif alteration == "digest":
        row["business_sha256"] = "0" * 64
    else:
        c["items"][0][field] = deepcopy(c["items"][1][field])
    c["correction_sha256"] = correction_digest(c)
    with pytest.raises(AdmissionRejected):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_policy_relaxation_cannot_resolve_incomplete_correction(tmp_path: Path) -> None:
    from test_part2_stage3_admission import policy

    updated = policy()
    updated["policy_version"] = "v2"
    for row in updated["currency_rules"].values():
        row["transaction_tolerance_minor"] = 100
        row["settlement_tolerance_minor"] = 100
    updated["policy_sha256"] = canonical_sha256(updated, {"policy_sha256"})
    case = scenario(tmp_path, amount=40, policy=updated)
    with pytest.raises(AdmissionRejected, match="policy change rather than source correction"):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_actual_correction_can_accompany_policy_revision(tmp_path: Path) -> None:
    from test_part2_stage3_admission import policy

    updated = policy()
    updated["policy_version"] = "v2"
    updated["policy_sha256"] = canonical_sha256(updated, {"policy_sha256"})
    case = scenario(tmp_path, policy=updated)
    result = case["store"].finalize(**case["args"])
    assert all(
        case["store"].read_case_revision(c.object_sha256)["status"] == "RESOLVED_BY_CORRECTION"
        for c in result.cases
    )


def test_predecessor_policy_tampering_rejects(tmp_path: Path) -> None:
    case = scenario(tmp_path)
    c = case["args"]["correction"]
    c["items"][0]["prior_policy"]["policy_version"] = "forged-policy"
    c["correction_sha256"] = correction_digest(c)
    with pytest.raises(AdmissionRejected):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


@pytest.mark.parametrize("amount", [101, 200])
def test_nonreducing_or_overshooting_correction_cannot_resolve(tmp_path: Path, amount: int) -> None:
    case = scenario(tmp_path, amount)
    if amount == 101:
        receipt = case["store"].finalize(**case["args"])
        assert all(
            case["store"].read_proof(p.object_sha256)["totals"]["difference_minor"] == 1
            for p in receipt.proofs
        )
        for ref in receipt.cases:
            revision = case["store"].read_case_revision(ref.object_sha256)
            assert revision["status"] == (
                "OPEN" if ref.reconciliation_key.startswith("txn:") else "RESOLVED_BY_CORRECTION"
            )
        for ref in receipt.proofs:
            proof = case["store"].read_proof(ref.object_sha256)
            if ref.reconciliation_key.startswith("stl:"):
                assert proof["status"] == "WITHIN_TOLERANCE"
                assert "TOLERATED_DIFFERENCE" in proof["reason_codes"]
    else:
        with pytest.raises(AdmissionRejected, match="does not reduce"):
            case["store"].finalize(**case["args"])
        assert case["store"].read_head() == case["first"].commit_sha256


def write_inputs(case: dict[str, Any], root: Path) -> list[str]:
    import sys

    root.mkdir(exist_ok=True)
    inputs = case["args"]["correction_inputs"]
    for name in ("policy", "manifest"):
        (root / f"{name}.json").write_bytes(canonical_json_bytes(inputs[name]))
    (root / "correction.json").write_bytes(canonical_json_bytes(case["args"]["correction"]))
    objects = root / "inputs"
    objects.mkdir(exist_ok=True)
    for descriptor in inputs["manifest"]["objects"]:
        relative = descriptor["relative_path"]
        (objects / relative).write_bytes(b64decode(inputs["objects"][f"local:{relative}"]))
    return [
        sys.executable,
        "-m",
        "ledgerguard_part3_stage1_correct",
        "--repository",
        str(ROOT),
        "--policy",
        str(root / "policy.json"),
        "--manifest",
        str(root / "manifest.json"),
        "--input-root",
        str(objects),
        "--store",
        str(case["store"].root),
        "--correction",
        str(root / "correction.json"),
        "--attempt-id",
        case["args"]["attempt_id"],
        "--expected-head",
        case["args"]["expected_head"],
        "--created-at",
        TIME,
    ]


def test_cli_real_source_correction_and_both_retries(tmp_path: Path) -> None:
    import json
    import subprocess

    case = scenario(tmp_path)
    command = write_inputs(case, tmp_path / "cli")
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    receipt = json.loads(first.stdout)
    assert len(receipt["proofs"]) == len(receipt["cases"]) == 2
    assert (
        subprocess.run(command, capture_output=True, text=True, check=True).stdout == first.stdout
    )
    command[command.index("--attempt-id") + 1] = "new-cli-attempt"
    assert (
        subprocess.run(command, capture_output=True, text=True, check=True).stdout == first.stdout
    )
    assert case["store"].read_head() == receipt["commit_sha256"]
    case["store"].verify_history()


@pytest.mark.parametrize(
    "failure", ["missing-input", "duplicate-json", "bad-store", "unavailable-store"]
)
def test_cli_failure_ownership(tmp_path: Path, failure: str) -> None:
    import json
    import subprocess

    case = scenario(tmp_path)
    command = write_inputs(case, tmp_path / "cli")
    if failure == "missing-input":
        (tmp_path / "cli/policy.json").unlink()
    elif failure == "duplicate-json":
        (tmp_path / "cli/correction.json").write_text(
            '{"schema_version":"1.0","schema_version":"1.0"}'
        )
    elif failure == "bad-store":
        (case["store"].root / "control/HEAD").write_text("invalid")
    else:
        blocker = tmp_path / "unavailable"
        blocker.write_text("file blocks directory")
        command[command.index("--store") + 1] = str(blocker / "store")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == (3 if failure in ("bad-store", "unavailable-store") else 2), (
        result.stderr
    )
    assert json.loads(result.stdout)["outcome"] != "AUTHORITATIVE_PROOFS_FINALIZED"


WORKER = """
import json,sys,time
from base64 import b64encode
from pathlib import Path
from ledgerguard.reconciliation import (FinalizationStore,admit_bundle,canonical_json_bytes,
    reconcile_transactions,reconcile_settlements,FinalizationRejected)
repository,root,store_path,attempt,expected,fault,ready,go=sys.argv[1:]
root=Path(root)
store=FinalizationStore(Path(repository),Path(store_path))
a,t,s=store.load_states()
policy=(root/'policy.json').read_bytes(); manifest=(root/'manifest.json').read_bytes()
m=json.loads(manifest)
objects={}
for d in m['objects']:
    objects['local:'+d['relative_path']]=(root/'inputs'/d['relative_path']).read_bytes()
admitted=admit_bundle(Path(repository),policy,manifest,objects,prior_state=a)
tb=reconcile_transactions(admitted,t); sb=reconcile_settlements(admitted,s)
if ready!='NONE':
    Path(ready).write_text('ready')
    deadline=time.monotonic()+20
    while not Path(go).exists():
        if time.monotonic()>deadline: raise RuntimeError('barrier timeout')
        time.sleep(.02)
try:
    receipt=store.finalize(attempt_id=attempt,expected_head=expected,created_at='2026-09-06T00:00:00Z',
        transaction_batch=tb,settlement_batch=sb,fault_point=None if fault=='NONE' else fault,
        correction=json.loads((root/'correction.json').read_bytes()),
        correction_inputs={'policy':json.loads(policy),'manifest':m,
                           'object_encoding':'base64',
                           'objects':{k:b64encode(v).decode('ascii') for k,v in objects.items()}})
    print(json.dumps(receipt.value(),sort_keys=True))
except FinalizationRejected as error:
    print(json.dumps(error.as_dict(),sort_keys=True))
    raise SystemExit(3)
"""


def worker_command(
    case: dict[str, Any],
    root: Path,
    fault: str = "NONE",
    attempt: str | None = None,
    ready: str = "NONE",
    go: str = "NONE",
) -> list[str]:
    import sys

    return [
        sys.executable,
        "-c",
        WORKER,
        str(ROOT),
        str(root),
        str(case["store"].root),
        attempt or case["args"]["attempt_id"],
        case["args"]["expected_head"],
        fault,
        ready,
        go,
    ]


@pytest.mark.parametrize(
    "fault,exit_code",
    [("after_attempt", 71), ("after_objects", 72), ("after_commit", 73), ("after_head", 74)],
)
def test_correction_real_process_crash_and_recovery(
    tmp_path: Path, fault: str, exit_code: int
) -> None:
    import subprocess

    case = scenario(tmp_path)
    root = tmp_path / "worker"
    write_inputs(case, root)
    before = inventory(case["store"])
    head_before = case["store"].read_head()
    result = subprocess.run(worker_command(case, root, fault), capture_output=True, text=True)
    assert result.returncode == exit_code, result.stderr
    store = FinalizationStore(ROOT, case["store"].root)
    if fault != "after_head":
        assert store.read_head() == case["first"].commit_sha256
    else:
        assert store.read_head() != case["first"].commit_sha256
    store.verify_history()
    after_crash = inventory(store)
    head_after_crash = store.read_head()
    result = store.finalize(**case["args"])
    assert all(store.read_case_revision(c.object_sha256)["revision"] == 2 for c in result.cases)
    assert store.finalize(**case["args"]) == result
    assert store.recover_attempt(**recovery_args(case, "new-crash-retry")) == result
    observation(
        "crash-" + fault,
        {
            "fault": fault,
            "exit_code": exit_code,
            "before": before,
            "after_crash": after_crash,
            "head_before": head_before,
            "head_after_crash": head_after_crash,
            "head_after_recovery": store.read_head(),
            "after_recovery": inventory(store),
            "receipt": result.value(),
        },
    )


def test_competing_corrections_have_one_conditional_winner(tmp_path: Path) -> None:
    import subprocess
    import time

    case = scenario(tmp_path)
    left, right = tmp_path / "left", tmp_path / "right"
    write_inputs(case, left)
    other = {**case, "args": deepcopy(case["args"])}
    other["args"]["correction"]["correction_id"] = "competing-correction"
    other["args"]["correction"]["correction_sha256"] = correction_digest(
        other["args"]["correction"]
    )
    write_inputs(other, right)
    go = tmp_path / "go"
    processes = [
        subprocess.Popen(
            worker_command(c, root, attempt=attempt, ready=str(root / "ready"), go=str(go)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for c, root, attempt in [(case, left, "left-attempt"), (other, right, "right-attempt")]
    ]
    try:
        deadline = time.monotonic() + 20
        while not all((root / "ready").exists() for root in (left, right)):
            assert time.monotonic() < deadline, (
                "both contenders must reach the prepublication barrier"
            )
            time.sleep(0.02)
        go.write_text("publish")
        outputs = [p.communicate(timeout=30) for p in processes]
        assert sorted(p.returncode for p in processes) == [0, 3], outputs
        observation(
            "concurrency",
            {
                "head_before": case["args"]["expected_head"],
                "head_after": case["store"].read_head(),
                "exit_codes": [p.returncode for p in processes],
                "outputs": [list(pair) for pair in outputs],
                "inventory": inventory(case["store"]),
            },
        )
        assert "stale authoritative control head" in "".join(o[0] for o in outputs)
        head = case["store"].verify_history()
        assert head is not None and head["parent_sha256"] == case["first"].commit_sha256
        assert all(
            case["store"].read_case_revision(d)["revision"] == 2
            for d in head["case_heads"].values()
        )
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
            p.wait()


@pytest.mark.parametrize(
    "tamper", ["provenance", "request-version", "downgrade", "input-bytes", "case-status"]
)
def test_mixed_history_rejects_rehashed_tampering(tmp_path: Path, tamper: str) -> None:
    import json
    from hashlib import sha256

    from ledgerguard.reconciliation import FinalizationRejected

    case = scenario(tmp_path)
    store = case["store"]
    receipt = store.finalize(**case["args"])
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_bytes())
    request_path = store.root / "attempts" / receipt.attempt_id / "request.json"
    request = json.loads(request_path.read_bytes())
    if tamper == "provenance":
        request["correction"]["items"][0]["prior_case_revision_sha256"] = "0" * 64
        request["correction"]["correction_sha256"] = correction_digest(request["correction"])
    elif tamper == "request-version":
        request["schema_version"] = "3.0"
    elif tamper == "downgrade":
        request["schema_version"] = "1.0"
    elif tamper == "input-bytes":
        key = next(iter(request["correction_inputs"]["objects"]))
        request["correction_inputs"]["objects"][key] += " "
    else:
        ref = receipt.cases[0]
        value = store.read_case_revision(ref.object_sha256)
        value["status"] = "RESOLVED_BY_LATE_DATA"
        value["case_revision_sha256"] = canonical_sha256(value, {"case_revision_sha256"})
        raw = canonical_json_bytes(value)
        digest = sha256(raw).hexdigest()
        (store.root / "objects" / f"{digest}.json").write_bytes(raw)
        commit["case_heads"][ref.reconciliation_key] = digest
        commit["written_cases"] = sorted(
            digest if x == ref.object_sha256 else x for x in commit["written_cases"]
        )
    raw = canonical_json_bytes(request)
    request_path.write_bytes(raw)
    commit["request_sha256"] = sha256(raw).hexdigest()
    raw = canonical_json_bytes(commit)
    digest = sha256(raw).hexdigest()
    (store.root / "commits" / f"{digest}.json").write_bytes(raw)
    store._replace_head(digest)
    with pytest.raises(FinalizationRejected):
        store.verify_history()
    with pytest.raises(FinalizationRejected):
        store.load_states()


def test_mixed_late_bank_and_correction_are_classified_per_key(tmp_path: Path) -> None:
    case = scenario(tmp_path, late=True)
    result = case["store"].finalize(**case["args"])
    statuses = [case["store"].read_case_revision(c.object_sha256)["status"] for c in result.cases]
    assert statuses.count("RESOLVED_BY_CORRECTION") == 2
    assert statuses.count("RESOLVED_BY_LATE_DATA") == 1
    assert all(
        case["store"].read_proof(p.object_sha256)["totals"]["difference_minor"] == 0
        for p in result.proofs
    )


def raw_families(case: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    import json

    inputs = case["args"]["correction_inputs"]
    return {
        d["family"]: [
            json.loads(line)
            for line in b64decode(inputs["objects"]["local:" + d["relative_path"]]).splitlines()
        ]
        for d in inputs["manifest"]["objects"]
    }


def rebind_sources(
    case: dict[str, Any],
    families: dict[str, list[dict[str, Any]]],
    *,
    run: str = "correction-run-2",
) -> None:
    import json

    args = case["args"]
    pb, mb, objects, manifest = build_bundle(
        families, policy_value=args["correction_inputs"]["policy"], run_id=run
    )
    admitted = admit_bundle(ROOT, pb, mb, objects, prior_state=case["prior"])
    args["correction_inputs"] = {
        "policy": json.loads(pb),
        "manifest": manifest,
        "object_encoding": "base64",
        "objects": {k: b64encode(v).decode("ascii") for k, v in objects.items()},
    }
    args["transaction_batch"] = reconcile_transactions(admitted, case["tx"])
    args["settlement_batch"] = reconcile_settlements(admitted, case["st"])
    c = args["correction"]
    c["manifest_sha256"] = admitted.manifest_sha256
    c["policy_sha256"] = admitted.policy_sha256
    records = {r.source_identity: r for r in admitted.records}
    for item in c["items"]:
        for row in item["corrective_sources"]:
            record = records.get(tuple(row["identity"]))
            if record is not None:
                row["business_sha256"] = record.business_sha256
    c["correction_sha256"] = correction_digest(c)
    case["admitted"] = admitted


@pytest.mark.parametrize(
    "scope", ["payment_id", "merchant_id", "processor", "currency", "ledger_system"]
)
def test_correction_cannot_cross_identity_or_currency_scope(tmp_path: Path, scope: str) -> None:
    case = scenario(tmp_path)
    families = raw_families(case)
    row = next(r for r in families["LEDGER_JOURNALS"] if r["journal_id"] == "adjustment-txn")
    row[scope] = "USD" if scope == "currency" else "unrelated"
    row.update(signed_record(row))
    with pytest.raises(AdmissionRejected):
        rebind_sources(case, families)
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


@pytest.mark.parametrize(
    "invalid",
    [
        "identity-conflict",
        "unbalanced",
        "orientation",
        "role",
        "same-key-late-bank",
        "same-key-late-event",
    ],
)
def test_invalid_or_ambiguous_financial_evidence_is_not_a_correction(
    tmp_path: Path, invalid: str
) -> None:
    case = scenario(tmp_path)
    families = raw_families(case)
    row = next(r for r in families["LEDGER_JOURNALS"] if r["journal_id"] == "adjustment-txn")
    if invalid == "identity-conflict":
        row["journal_id"] = "original-txn"
    elif invalid == "unbalanced":
        row["postings"][0]["amount_minor"] = 99
    elif invalid == "orientation":
        for posting in row["postings"]:
            posting["side"] = "CREDIT" if posting["side"] == "DEBIT" else "DEBIT"
    elif invalid == "role":
        row["postings"][0]["account_role"] = "MERCHANT_PAYABLE"
    elif invalid == "same-key-late-bank":
        families["BANK_ENTRIES"].append(bank_entry(bank_record_id="extra-bank", amount_minor=1))
    else:
        families["PROCESSOR_EVENTS"].append(
            processor_event(source_record_id="extra-event", amount_minor=1)
        )
    row.update(signed_record(row))
    with pytest.raises(AdmissionRejected):
        rebind_sources(case, families)
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_genuine_second_correction_uses_latest_predecessor_once(tmp_path: Path) -> None:
    case = scenario(tmp_path, 40)
    store = case["store"]
    partial = store.finalize(**case["args"])
    families = raw_families(case)
    families["LEDGER_JOURNALS"] += [
        correction_journal("second-txn", 60),
        correction_journal("second-stl", 60, True),
    ]
    prior, tx, st = store.load_states()
    case.update(prior=prior, tx=tx, st=st)
    c = case["args"]["correction"]
    c["expected_head"] = partial.commit_sha256
    c["correction_id"] = "correction-2"
    case["args"].update(expected_head=partial.commit_sha256, attempt_id="second-correction")
    for item in c["items"]:
        key = item["reconciliation_key"]
        proof = next(p for p in partial.proofs if p.reconciliation_key == key)
        revision = next(r for r in partial.cases if r.reconciliation_key == key)
        item.update(
            prior_proof_id=proof.proof_id, prior_case_revision_sha256=revision.case_revision_sha256
        )
        item["corrective_sources"][0]["identity"][-1] = (
            "second-txn" if key.startswith("txn:") else "second-stl"
        )
    rebind_sources(case, families, run="correction-run-3")
    result = store.finalize(**case["args"])
    for proof in result.proofs:
        value = store.read_proof(proof.object_sha256)
        assert value["totals"]["difference_minor"] == 0 and value["revision"] == 3
    for revision in result.cases:
        value = store.read_case_revision(revision.object_sha256)
        assert value["status"] == "RESOLVED_BY_CORRECTION" and value["revision"] == 3
        original = next(
            r for r in case["first"].cases if r.reconciliation_key == revision.reconciliation_key
        )
        assert revision.case_id == original.case_id
    store.verify_history()


def test_correction_requires_real_open_predecessor(tmp_path: Path) -> None:
    case = scenario(tmp_path)
    empty = FinalizationStore(ROOT, tmp_path / "empty")
    args = {**case["args"], "expected_head": None}
    with pytest.raises(AdmissionRejected, match="predecessor is missing"):
        empty.finalize(**args)
    assert empty.read_head() is None
    case["args"]["correction"]["items"][0]["reconciliation_key"] = "txn:" + "0" * 64
    case["args"]["correction"]["items"].sort(key=lambda r: r["reconciliation_key"])
    case["args"]["correction"]["correction_sha256"] = correction_digest(case["args"]["correction"])
    with pytest.raises(AdmissionRejected, match="no authoritative exception"):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_stale_correction_does_not_rebase_itself(tmp_path: Path) -> None:
    from ledgerguard.reconciliation import FinalizationRejected

    case = scenario(tmp_path)
    args = case["args"]
    later = case["store"].finalize(
        attempt_id="ordinary-successor",
        expected_head=args["expected_head"],
        created_at=TIME,
        transaction_batch=args["transaction_batch"],
        settlement_batch=args["settlement_batch"],
    )
    with pytest.raises(FinalizationRejected, match="stale authoritative control head"):
        case["store"].finalize(**args)
    assert case["store"].read_head() == later.commit_sha256


def test_policy_only_legacy_revision_is_never_correction(tmp_path: Path) -> None:
    from test_part2_stage3_admission import policy

    case = scenario(tmp_path)
    updated = policy()
    updated["policy_version"] = "v2"
    for rule in updated["currency_rules"].values():
        rule["transaction_tolerance_minor"] = 100
        rule["settlement_tolerance_minor"] = 100
    updated["policy_sha256"] = canonical_sha256(updated, {"policy_sha256"})
    pb, mb, objects, _ = build_bundle(case["families"], policy_value=updated, run_id="policy-only")
    admitted = admit_bundle(ROOT, pb, mb, objects, prior_state=case["prior"])
    result = case["store"].finalize(
        attempt_id="policy-only",
        expected_head=case["first"].commit_sha256,
        created_at=TIME,
        transaction_batch=reconcile_transactions(admitted, case["tx"]),
        settlement_batch=reconcile_settlements(admitted, case["st"]),
    )
    for ref in result.proofs:
        proof = case["store"].read_proof(ref.object_sha256)
        assert proof["status"] == "WITHIN_TOLERANCE" and proof["totals"]["difference_minor"] == 100
    assert all(
        case["store"].read_case_revision(r.object_sha256)["status"] == "RESOLVED_BY_LATE_DATA"
        for r in result.cases
    )
    case["store"].verify_history()


def test_after_head_correction_recovers_after_later_authority(tmp_path: Path) -> None:
    import json
    import subprocess

    case = scenario(tmp_path)
    root = tmp_path / "worker"
    write_inputs(case, root)
    result = subprocess.run(
        worker_command(case, root, "after_head"), capture_output=True, text=True
    )
    assert result.returncode == 74, result.stderr
    store = case["store"]
    correction_head = store.read_head()
    assert correction_head is not None
    committed = json.loads((store.root / "commits" / f"{correction_head}.json").read_bytes())
    a, t, s = store.load_states()
    inputs = case["args"]["correction_inputs"]
    admitted = admit_bundle(
        ROOT,
        canonical_json_bytes(inputs["policy"]),
        canonical_json_bytes(inputs["manifest"]),
        {k: b64decode(v) for k, v in inputs["objects"].items()},
        prior_state=a,
    )
    later = store.finalize(
        attempt_id="later-attempt",
        expected_head=correction_head,
        created_at=TIME,
        transaction_batch=reconcile_transactions(admitted, t),
        settlement_batch=reconcile_settlements(admitted, s),
    )
    for attempt in (case["args"]["attempt_id"], "new-after-later"):
        recovered = store.recover_attempt(**recovery_args(case, attempt))
        assert recovered is not None and recovered.commit_sha256 == correction_head
        assert recovered.request_sha256 == committed["request_sha256"]
        assert store.read_head() == later.commit_sha256
    store.verify_history()


def test_current_correction_storage_failure_has_execution_ownership(tmp_path: Path) -> None:
    from ledgerguard.reconciliation import FinalizationRejected

    case = scenario(tmp_path)
    blocker = case["store"].root / "attempts" / case["args"]["attempt_id"]
    blocker.write_text("this real file prevents an attempt directory")
    with pytest.raises(FinalizationRejected, match="storage operation failed"):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_input_order_and_timestamp_do_not_choose_causal_state(tmp_path: Path) -> None:
    first = scenario(tmp_path / "first")
    second = scenario(tmp_path / "second")
    sources = raw_families(second)
    for rows in sources.values():
        rows.reverse()
    rebind_sources(second, dict(reversed(sources.items())))
    second["args"]["created_at"] = "2026-09-07T00:00:00Z"
    results = [case["store"].finalize(**case["args"]) for case in (first, second)]
    for left, right in zip(results[0].proofs, results[1].proofs, strict=True):
        one = first["store"].read_proof(left.object_sha256)
        two = second["store"].read_proof(right.object_sha256)
        assert one["totals"] == two["totals"] and one["reason_codes"] == two["reason_codes"]
    assert all(
        case["store"].read_case_revision(c.object_sha256)["status"] == "RESOLVED_BY_CORRECTION"
        for case, result in zip((first, second), results, strict=True)
        for c in result.cases
    )
    assert results[0].request_sha256 != results[1].request_sha256


def test_independent_equal_input_stores_reproduce_all_authority_bytes(tmp_path: Path) -> None:
    first = scenario(tmp_path / "first")
    second = scenario(tmp_path / "second")
    assert first["store"].finalize(**first["args"]) == second["store"].finalize(**second["args"])

    def inventory(case: dict[str, Any]) -> dict[str, bytes]:
        return {
            str(p.relative_to(case["store"].root)): p.read_bytes()
            for p in case["store"].root.rglob("*.json")
        }

    assert inventory(first) == inventory(second)


def test_source_file_partitioning_preserves_exact_financial_results(tmp_path: Path) -> None:
    from hashlib import sha256

    original = scenario(tmp_path / "original")
    partitioned = scenario(tmp_path / "partitioned")
    inputs = partitioned["args"]["correction_inputs"]
    manifest = inputs["manifest"]
    descriptor = next(d for d in manifest["objects"] if d["family"] == "LEDGER_JOURNALS")
    raw = b64decode(inputs["objects"].pop("local:" + descriptor["relative_path"]))
    manifest["objects"].remove(descriptor)
    for i, line in enumerate(raw.splitlines(), 1):
        relative = f"journal-part-{i}.jsonl"
        data = line + b"\n"
        inputs["objects"]["local:" + relative] = b64encode(data).decode("ascii")
        manifest["objects"].append(
            {
                **descriptor,
                "relative_path": relative,
                "record_count": 1,
                "size_bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        )
    manifest["manifest_sha256"] = canonical_sha256(manifest, {"manifest_sha256"})
    admitted = admit_bundle(
        ROOT,
        canonical_json_bytes(inputs["policy"]),
        canonical_json_bytes(manifest),
        {k: b64decode(v) for k, v in inputs["objects"].items()},
        prior_state=partitioned["prior"],
    )
    args = partitioned["args"]
    args["correction"]["manifest_sha256"] = admitted.manifest_sha256
    args["correction"]["correction_sha256"] = correction_digest(args["correction"])
    args["transaction_batch"] = reconcile_transactions(admitted, partitioned["tx"])
    args["settlement_batch"] = reconcile_settlements(admitted, partitioned["st"])
    results = [case["store"].finalize(**case["args"]) for case in (original, partitioned)]
    for left, right in zip(results[0].proofs, results[1].proofs, strict=True):
        one = original["store"].read_proof(left.object_sha256)
        two = partitioned["store"].read_proof(right.object_sha256)
        for field in (
            "totals",
            "reason_codes",
            "reconciliation_key",
            "status",
        ):
            assert one[field] == two[field]
    assert results[0].request_sha256 != results[1].request_sha256


@pytest.mark.parametrize("method", ["finalize", "recover_attempt"])
def test_inputs_without_provenance_cannot_enter_correction_protocol(
    tmp_path: Path, method: str
) -> None:
    case = scenario(tmp_path)
    args = dict(case["args"]) if method == "finalize" else recovery_args(case)
    args.pop("correction")
    with pytest.raises(AdmissionRejected, match="inputs without provenance"):
        getattr(case["store"], method)(**args)
    assert case["store"].read_head() == case["first"].commit_sha256


def test_reader_rejects_invalid_companion_even_with_new_request_and_commit_hashes(
    tmp_path: Path,
) -> None:
    import json
    from hashlib import sha256

    from ledgerguard.reconciliation import FinalizationRejected

    case = scenario(tmp_path)
    store = case["store"]
    receipt = store.finalize(**case["args"])
    path = store.root / "attempts" / receipt.attempt_id / "request.json"
    request = json.loads(path.read_bytes())
    request["correction"]["schema_version"] = "9.0"
    request["correction"]["correction_sha256"] = correction_digest(request["correction"])
    raw = canonical_json_bytes(request)
    path.write_bytes(raw)
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_bytes())
    commit["request_sha256"] = sha256(raw).hexdigest()
    raw = canonical_json_bytes(commit)
    digest = sha256(raw).hexdigest()
    (store.root / "commits" / f"{digest}.json").write_bytes(raw)
    store._replace_head(digest)
    with pytest.raises(FinalizationRejected, match="persisted correction context differs"):
        store.load_states()


def test_cli_import_does_not_run_or_publish() -> None:
    import importlib

    module = importlib.import_module("ledgerguard_part3_stage1_correct")
    assert callable(module.main)


def test_recovery_rejects_another_attempts_valid_committed_outcome(tmp_path: Path) -> None:
    from ledgerguard.reconciliation import FinalizationRejected

    case = scenario(tmp_path)
    result = case["store"].finalize(**case["args"])
    root = case["store"].root / "attempts"
    original = (root / case["first"].attempt_id / "outcome.json").read_bytes()
    (root / result.attempt_id / "outcome.json").write_bytes(original)
    with pytest.raises(FinalizationRejected, match="outcome belongs to another request"):
        case["store"].recover_attempt(**recovery_args(case))
    assert case["store"].read_head() == result.commit_sha256


def test_supplied_candidate_cannot_override_readmitted_financial_truth(tmp_path: Path) -> None:
    from dataclasses import replace

    case = scenario(tmp_path, 40)
    batch = case["args"]["transaction_batch"]
    candidate = replace(
        batch.candidates[0],
        ledger_minor=1000,
        processor_ledger_delta_minor=0,
        difference_minor=0,
        status="MATCHED",
        reason_codes=(),
    )
    case["args"]["transaction_batch"] = replace(batch, candidates=(candidate,))
    with pytest.raises(AdmissionRejected, match="candidates differ from admitted source truth"):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_undeclared_same_key_journal_cannot_supply_correction_causation(tmp_path: Path) -> None:
    case = scenario(tmp_path)
    sources = raw_families(case)
    sources["LEDGER_JOURNALS"].append(correction_journal("unlinked-adjustment", 60))
    rebind_sources(case, sources)
    with pytest.raises(AdmissionRejected, match="correction additions differ"):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_non_normalized_utf8_transport_survives_canonical_request_storage(tmp_path: Path) -> None:
    from hashlib import sha256

    case = scenario(tmp_path)
    args = case["args"]
    inputs = args["correction_inputs"]
    manifest = inputs["manifest"]
    descriptor = next(d for d in manifest["objects"] if d["family"] == "LEDGER_JOURNALS")
    locator = "local:" + descriptor["relative_path"]
    raw = (
        b64decode(inputs["objects"][locator]).decode().replace("batch-1", "batch-e\u0301").encode()
    )
    inputs["objects"][locator] = b64encode(raw).decode("ascii")
    descriptor.update(size_bytes=len(raw), sha256=sha256(raw).hexdigest())
    manifest["manifest_sha256"] = canonical_sha256(manifest, {"manifest_sha256"})
    args["correction"]["manifest_sha256"] = manifest["manifest_sha256"]
    args["correction"]["correction_sha256"] = correction_digest(args["correction"])
    admitted = admit_bundle(
        ROOT,
        canonical_json_bytes(inputs["policy"]),
        canonical_json_bytes(manifest),
        {k: b64decode(v) for k, v in inputs["objects"].items()},
        prior_state=case["prior"],
    )
    args["transaction_batch"] = reconcile_transactions(admitted, case["tx"])
    args["settlement_batch"] = reconcile_settlements(admitted, case["st"])
    result = case["store"].finalize(**args)
    assert case["store"].read_head() == result.commit_sha256
    case["store"].verify_history()


@pytest.mark.parametrize(
    "alteration", ["encoding", "missing", "type", "invalid", "unicode", "pad-bits"]
)
def test_opaque_source_encoding_fails_closed(tmp_path: Path, alteration: str) -> None:
    case = scenario(tmp_path)
    inputs = case["args"]["correction_inputs"]
    locator = next(iter(inputs["objects"]))
    if alteration == "encoding":
        inputs["object_encoding"] = "utf8"
    elif alteration == "missing":
        del inputs["object_encoding"]
    else:
        inputs["objects"][locator] = {
            "type": 12,
            "invalid": "!",
            "unicode": "é",
            "pad-bits": "Zh==",
        }[alteration]
    with pytest.raises(AdmissionRejected):
        case["store"].finalize(**case["args"])
    assert case["store"].read_head() == case["first"].commit_sha256


def test_canonically_equivalent_correction_identity_retries(tmp_path: Path) -> None:
    case = scenario(tmp_path, source_suffix="-é")
    correction = case["args"]["correction"]
    for item in correction["items"]:
        for row in item["original_sources"]:
            row["identity"][-1] = row["identity"][-1].replace("é", "e\u0301")
    correction["correction_sha256"] = correction_digest(correction)
    result = case["store"].finalize(**case["args"])
    assert case["store"].recover_attempt(**recovery_args(case)) == result
    assert case["store"].recover_attempt(**recovery_args(case, "equivalent-retry")) == result
    assert case["store"].finalize(**case["args"]) == result


def test_companion_source_identifiers_preserve_the_accepted_domain_contract() -> None:
    schema = json.loads(
        (ROOT / "contracts/part3/correction-provenance-v1.schema.json").read_bytes()
    )
    common = json.loads((ROOT / "contracts/v2/common-v2.schema.json").read_bytes())
    for field in ("original_sources", "corrective_sources"):
        identity = schema["properties"]["items"]["items"]["properties"][field]["items"][
            "properties"
        ]["identity"]
        assert identity["prefixItems"][1:] == [common["$defs"]["identifier"]] * 2
