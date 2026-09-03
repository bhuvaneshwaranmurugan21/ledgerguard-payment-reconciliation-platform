# Part 2 Stage 2 independent reference oracle

## Purpose

`ledgerguard_reference_oracle` is a deliberately separate expected-result implementation. It
translates the frozen Part 1 financial authorities into deterministic calculations that future
runtime implementations can be compared against without sharing their calculation code.

## Public surface

- Strict JSON parsing rejects floats, non-finite numbers, duplicate keys, Unicode key collisions,
  a UTF-8 BOM, and integers outside signed 64-bit range.
- Canonical JSON uses UTF-8, Unicode NFC, lexicographic keys, normalized RFC 3339 UTC timestamps,
  and compact separators.
- Source identities and business digests distinguish transport-only replay from identity conflict.
- Transaction expectations apply event and ledger signs, reference validity, capture capacity,
  missing-evidence counts, differences, tolerance, and financial reasons.
- Settlement expectations recompute net, apply clearing and bank signs, allocate exact normalized
  references, reject ambiguity, prevent duplicate use, enforce account policy, and calculate all
  three deltas.
- Proof and case helpers calculate the frozen content identities; they do not persist output.
- Journal validation distinguishes admission-invalid imbalance from a balanced wrong-role financial
  exception.

## Deterministic reason order

Financial reasons use the order frozen in `common-v2.schema.json`. `TOLERATED_DIFFERENCE` is a
special non-failure reason and is the only reason permitted for `WITHIN_TOLERANCE`. Admission
rejections return their owning admission reason and `authoritative_proof: false`.

## Independence controls

The package has no import of the `ledgerguard` production namespace, Spark, AWS clients, data-frame
libraries, databases, HTTP clients, or persistence libraries. The Stage 2 validator parses the
package import graph and scans production modules for reverse imports. The oracle itself performs
no filesystem, network, environment, clock, random, or process operations.

## Validation

Run the installed candidate directly:

```bash
ledgerguard-part2-stage2
```

Run the hermetic two-run validator with exact CPython 3.11.13:

```bash
python tools/run_part2_stage2.py --clean-runs 2 --output /tmp/ledgerguard-part2-stage2
```

Output must be outside the repository. Both clean runs must produce equal logical evidence and
equal reproducible wheel digests.
