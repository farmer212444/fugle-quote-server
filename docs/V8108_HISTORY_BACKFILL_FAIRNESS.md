# V8.10.8 historical-source backlog fairness / full-market coverage

## Root causes fixed

1. The TWSE candidate picker previously treated an older `price_reference_asof` as sufficient reason to re-fetch the same issuer. The date changes on every trading session, which can starve other companies of the 8 available fetch slots, even when the archived 20/60-session price evidence was already collected.
2. TWSE input collection prioritized A+ research and benchmark cohorts, but allocated **no guaranteed lane** to the rest of the 1,994-stock daily market universe.
3. TPEx date snapshots contain all exchange quotes, but the issuer history builder selected primarily research candidates; the remaining uncovered issuer codes could wait indefinitely.

## Changes

- New `marketwide_history_priority.py` picks previously unarchived valid-close issuers by exchange and dated turnover. This is **only network collection priority**, not selection/stock recommendation and not a backtested liquidity indicator.
- TWSE `prioritized_candidates`: retain frozen-benchmark and model research order, but avoid repetitive timestamp-only refreshing of a source-complete issuer. Allocate at least one-third of each batch (when capacity >= 6) to uncovered, previously unarchived securities, and use unused focus slots for broader inclusion.
- TWSE scheduled budget is now **10 issuers, most recent 4 months, maximum 3 new months per issuer** per run. This targets bounded 60-session readiness rather than repeatedly revisiting 24 historical months. This **does not satisfy** longer-horizon PIT OOS history or 13 formal gates; those remain independent.
- TPEx marketwide collector adds at most 6 previously unarchived issuers per run, using the full-market archived date sources where available. Existing retained cohorts still take precedence. Do not increase daily API call budget.
- Preserve official source archives and SHA receipts; unknown close, later reference dates and ineligible exchanges never become priced valid signals.

## Validation and limits

Test both source parsers, existing reference-year backfills and new queue fairness regression. Verify the PR is only tested (no collection publication on PR), and on main the original scheduled workflows publish only source-based data. History scripts are subject to network throttling and occasional TPEx source gaps.

**Not yet complete:** adjusted stock total returns, exact security master/current listing PIT, suspension & daily calendar per issuer, old data originally available by forecast time, and independent nonoverlapping OOS test. A+ remains 0, no trading instructions or orders.
