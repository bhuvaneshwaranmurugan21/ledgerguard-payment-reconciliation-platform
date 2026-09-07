# Append-only source correction

Status: implementation in progress; acceptance requires Part 3 Stage 1 gates.

The Part 2 finalizer has no causal source-correction protocol. Its historical non-exception successor label is broad: `RESOLVED_BY_LATE_DATA` also covers policy reprocessing. Historical version 1 request bytes and their interpretation remain fixed. A new internal request version 2 binds the strict correction companion and the actual policy, manifest, and exact source bytes encoded as canonical base64 ASCII (`object_encoding: base64`) through the request digest, immutable commit, and atomic HEAD. Proof and case identity equations and the active v1/v2 registry are unchanged.

## Applicability

| Source family | Accepted representation | Correction classification | Required rejection or unresolved behavior |
|---|---|---|---|
| Ledger journals, transaction grain | A new balanced journal with distinct immutable identity, permitted roles, capture/refund/etc. orientation, exact processor/merchant/payment/event-class/currency key | `BALANCED_JOURNAL_ADJUSTMENT` may repair an under-recorded movement; original and adjustment business digests must be linked | Changed bytes under an existing identity reject. Wrong orientation, roles, references, currency, or nonreducing discrepancy cannot gain a correction exemption. |
| Ledger journals, settlement grain | A new balanced settlement journal with exact processor/merchant/settlement/cycle/currency key | Same companion kind; processor, clearing, and allocated-bank deltas remain independently enforced | No invented bank allocation; bank and processor facts remain unchanged for the corrected grain. |
| Processor events | Existing immutable event classes, identity and negative-event reference rules | Ordinary admitted arrivals retain the legacy path. An event is not a journal adjustment. | A new reversal belongs to its declared event-class grain; it cannot erase an erroneous capture. Same-grain concurrent non-journal additions make journal-correction causation ambiguous and reject. |
| Processor settlements | Existing immutable settlement reports with frozen net/fee arithmetic | Ordinary arrival and policy reprocessing remain available | Replacing a report is unsupported by v2 and rejected; no silent supersession or tolerance waiver. |
| Bank entries | Existing immutable credit/debit entries and exact reference allocation | Genuine late bank arrival retains the existing late-data case transition | No synthetic credit to hide an error, replacement of an old identity, or cross-currency allocation. |

This implementation claims the two representable journal-adjustment modes, including partial and successive adjustments. It does not claim arbitrary replacement of immutable financial facts. A future requirement to remove or supersede erroneous immutable movements requires an additive domain version, compatibility readers, identity rules, and independent tests; it cannot be accepted through this companion. The master requirement for corrected-source resolution is demonstrated with actual financial corrections at both required grains, not source replacement.

## Financial and causal decision

For each linked key, an authoritative OPEN predecessor proof and case must exist. The companion supplies their exact identities, the initial exception identity, and the actual predecessor policy document. All prior source identities and business digests survive. Original references must identify existing same-key journals. Corrective references must equal all newly admitted same-key records and must consist entirely of distinct journals.

The finalizer independently re-admits the persisted source objects, reconstructs both batches, and compares every candidate and state byte with the supplied batch. It also re-evaluates those sources under the digest-verified predecessor policy. The manifest for this counterfactual evaluation changes only policy identity and its own digest; it is not substituted for the persisted input manifest. The discrepancy must strictly decrease. To classify a non-exception as correction-resolved, the predecessor policy evaluation must also be non-exception. A relaxed policy cannot supply the missing causal proof. Partial improvement outside tolerance stays OPEN. Within tolerance retains its nonzero difference and TOLERATED_DIFFERENCE reason. Operator-only states remain unavailable.

The simple exact cases start with processor 1,000 and clearing 900. A balanced adjustment 100 yields 1,000; settlement bank allocation remains 1,000. Adjustment 40 leaves 60. A second distinct adjustment 60 references the latest predecessor and counts the first adjustment exactly once. No timestamp chooses causation.

## Identity, replay, and storage

Correction digest is SHA-256 of canonical JSON `{domain: "ledgerguard.correction-provenance.v1", payload: <companion excluding correction_sha256>}`. Arrays of keys and source references must be unique and sorted. The manifest binds transport bytes; repartitioning may change manifest/request identity while preserving financial logical results. Timestamp changes may change proof bodies and request identity but never causal classification.

Same-attempt reuse requires identical request bytes including canonical timestamp and correction inputs. New-attempt retry may return the original committed correction receipt only after validating the entire authoritative history and identical correction/input content. Reusing a correction ID with changed provenance rejects. Attempt IDs already bound to another request cannot use correction lookup to evade their binding. A genuine second correction requires a new ID, new journal identities, and latest HEAD/proof/case links.

Publication uses the existing process lock and one conditional HEAD replacement. Pre-HEAD crashes leave only non-authoritative orphan files. Post-HEAD recovery returns the original committed result even after later commits. Version 2 readback re-runs causal admission and relationship checks; malformed or tampered stored content has execution-failure ownership. Invalid incoming source/provenance has admission-failure ownership. Missing input documents are admission failures; unavailable stores and failed writes are execution failures.

## Compatibility and acceptance

Unchanged historical validators run in their complete immutable snapshots. Current financial, recovery, schema, and bounded Spark/Parquet tests also run against the new installed wheel. Stage 1 is not complete until all 32 planned scenarios, critical branch coverage, mutation, two-run reproducibility, exact-head CI artifact inspection, and post-squash main verification pass. No AWS execution or complete source-to-proof DataFrame implementation is claimed here; the latter remains Stage 3's packaging prerequisite.

Opaque source payloads must never undergo Unicode normalization. The request canonicalizer normalizes JSON strings, so raw UTF-8 text is not a safe transport representation. Strict base64 decoding and canonical re-encoding preserve every source byte, including decomposed Unicode and line endings; admission still verifies each original manifest byte length and SHA-256. Unknown encoding, malformed base64, and noncanonical pad bits reject before publication. The decomposed-Unicode regression reproduces the original post-publication readback failure and now requires successful history verification.

Source-reference namespace and journal identifiers retain the exact accepted common-v2 identifier constraints, including Unicode. The new correction control ID uses its own ASCII profile. Companion and input documents are canonicalized before both initial publication and retry comparison, so canonically equivalent references cannot cause a false identity conflict. Opaque base64 payloads remain byte-identical.
