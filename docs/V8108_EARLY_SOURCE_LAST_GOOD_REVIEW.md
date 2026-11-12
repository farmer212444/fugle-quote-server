# V8.10.8 early-quarter MOPS source recovery (fail-closed)

## Root cause

The 2026-11-12 research workflow passed the tests and market source refresh but stopped when two new MOPS issuer notices failed source-specific parsing: 4912 (`EARLY_ANNOUNCEMENT_REPORT_WINDOW_INVALID`) and 8155 (`EARLY_ANNOUNCEMENT_VALUE_INVALID`). Six other notices initially had temporary network failures. The collector correctly rejected the new material, but returned a nonzero status even when a previously verified archive remained available, causing unrelated research stages to stop.

## New rule

The original `early_bulk_earnings.py` CLI stays strict by default. Only the scheduled research workflow uses `--retain-verified-on-error`:

- Reject **all** newly attempted early sources when any source fails. No partially retrieved sample enters the forecast, and the existing `early_bulk/manifest.json` is never overwritten or backdated.
- Re-parse and rehash **every** receipt in that original manifest; check official source URLs, issuer identities, duplicate keys, schema, UTF/quarter identity and the original compressed bytes.
- Require a preexisting manifest, all currently requested markets present and latest captured receipt no older than 7 days. No manifest, bad SHA, malformed old source, duplicate notices or stale capture means a nonzero error; fail closed.
- Write `rankings/early_bulk_intake_health_latest.json` with the exact failure reasons, previous manifest SHA, last verified capture time and newly requested issuers not present in that earlier manifest.
- The cached collection is explicitly **not fresh**. Previously unavailable newer earnings are not represented as zero and historical PIT, quality gates, A+ and return estimates are not upgraded.
- A successful fresh run replaces the health status with `ALL_CURRENT_EARLY_SOURCES_CAPTURED` only after all requested new sources have been validated.

### Validation

6 new regression tests for old-SHA replay, tampering, missing markets, new scope, stale archive, nonexistent source. CI replays the real GitHub archive on a pull request without fetching any live new source.

The original parser remains strict; this changes only the operational response to an upstream source failure after an independently replayable last-good receipt exists.

**Not a company-original audited statement review. Not a certified PIT forecast, A+ accreditation or trade signal.**
