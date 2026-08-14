from ledgerguard.aws_evidence import validate_aws_lab_evidence
from ledgerguard.model import digest


def valid_bundle() -> dict[str, object]:
    payload: dict[str, object] = {
        "project": "ledgerguard-payment-reconciliation-platform",
        "claim_level": "AWS_LAB_VERIFIED",
        "production_claim": False,
        "result": "PASS",
        "region": "ap-south-1",
        "run_id": "lg-20260814-001",
        "commit_sha": "0123456789abcdef",
        "resources": {
            "feeds_bucket": "ledgerguard-redacted-feeds",
            "evidence_bucket": "ledgerguard-redacted-evidence",
            "case_table": "ledgerguard-lab-cases",
            "state_machine_arn": "redacted:state-machine",
            "cloudwatch_log_group": "/aws/ledgerguard/redacted",
        },
        "failure_tests": [
            "conflicting_replay",
            "unbalanced_journal",
            "missing_settlement",
            "worker_crash",
            "late_settlement_recovery",
        ],
        "metrics": {"records_reconciled": 1000, "runtime_seconds": 29.4, "cost_usd": 0.64},
        "teardown": {"destroyed": True, "verified_at": "2026-08-14T12:00:00Z"},
    }
    payload["evidence_digest"] = digest(payload)
    return payload


def test_complete_aws_evidence_contract_passes() -> None:
    assert validate_aws_lab_evidence(valid_bundle()) == ()


def test_evidence_contract_fails_closed() -> None:
    payload = valid_bundle()
    payload["failure_tests"] = []
    payload["teardown"] = {"destroyed": False}
    errors = validate_aws_lab_evidence(payload)
    assert any("failure tests missing" in error for error in errors)
    assert any("teardown" in error for error in errors)
    assert any("evidence_digest" in error for error in errors)

