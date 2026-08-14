# Failure lab

| Scenario | Expected result |
|---|---|
| Duplicate identical record | Idempotent replay |
| Reused record ID with changed amount | Whole feed batch blocked |
| Unbalanced journal | Journal rejected |
| Missing settlement | Exception with exact difference |
| Split settlement | Explicit one-to-many sum |
| Reversal before original | Contract violation |
| Currency mismatch | Separate exception domain |
| Worker failure before commit | No record becomes visible |
| Late settlement | Audited exception-to-match transition |
| Tolerance change | New policy version required |

