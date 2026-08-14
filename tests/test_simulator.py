from ledgerguard.simulator import simulate


def test_simulator_is_reproducible() -> None:
    assert simulate() == simulate()
    evidence = simulate()
    assert evidence["result"] == "PASS"
    assert evidence["metrics"]["checks_total"] == evidence["metrics"]["checks_passed"]
    assert not evidence["production_claim"]

