# Part 1 Stage 3 coherence requirements

Stage 3 closes the interpretation gaps between the frozen Stage 1 semantics and the immutable
Stage 2 active contracts. It validates one deterministic byte-level interpretation without adding
the reconciliation engine that belongs to Part 2.

| Requirement | Required outcome | Failure outcome |
|---|---|---|
| `COH-001` | Parse UTF-8 JSON with exact signed-64 integers and distinct booleans | Reject BOM, duplicate or NFC-colliding keys, decimals, exponents, non-finite values, overflow and Unicode surrogates |
| `COH-002` | Normalize strings and keys to NFC; sort keys by Unicode code point; emit compact UTF-8 | Reject normalized key collisions or unsupported value types |
| `COH-003` | Accept offset-aware RFC 3339, validate the calendar and emit UTC `Z` with at most six significant fractional digits | Reject naive time, impossible dates, leap seconds, excessive precision and invalid offsets |
| `COH-004` | Freeze source, policy, manifest, proof and case digest exclusions with golden bytes | Reject self-inclusion, transport-lineage inclusion or any golden-byte drift |
| `COH-005` | Derive transaction, settlement, proof and case identities from exact ordered component sets | Reject prefix, component or canonical-byte drift |
| `COH-006` | Resolve every manifest family to one digest-bound active schema ID | Reject missing, duplicate or unknown families |
| `COH-007` | Bind policy → manifest → proof → case by version, run, digest and identity | Reject any disconnected or substituted artifact |
| `COH-008` | Resolve every external and local JSON-reference fragment and prove shared domains are exact sets | Reject unresolved fragments or currency, event, reason or grain divergence |
| `COH-009` | Bind later case revisions to the immediate predecessor's canonical digest | Reject gaps, rewrites or predecessor substitution |
| `COH-010` | Map every coherence requirement to profile sections, vectors, tests, gates and owned artifacts | Reject orphan requirements, gates, tests or artifacts |
| `COH-011` | Produce deterministic validation and fail closed under adversarial mutation | Reject nondeterminism or accepted authority drift |
| `COH-012` | Preserve Stage 0–2, all v1/v2 schema bytes and the non-execution boundary | Reject historical drift, runtime additions, claim inflation, missing exact-head CI or missing post-merge CI |

The machine-readable authorities are
[`contract-coherence-v1.json`](../spec/contract-coherence-v1.json) and
[`contract-coherence-traceability-v1.json`](../spec/contract-coherence-traceability-v1.json).
