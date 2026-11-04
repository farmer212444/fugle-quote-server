# Concentration watchlist evidence audit

This fixed watchlist audit follows the user's ten research candidates, not the
raw full-market upside ranking. It does not issue formal certificates or trade
orders. The existing thirteen gates and A+/A++ policies remain unchanged.

## Reproduce

Use a real observation timestamp with a timezone, or a date no later than today.
The runner resolves today's date to the current instant; an end-of-day timestamp
that has not happened yet is not an admissible estimate vintage.

```sh
python scripts/tw_v880_run.py --asof 2026-11-04 --target-date 2027-12-31 --out-dir /tmp/top10-model
python scripts/concentration_gate_audit.py --research /tmp/top10-model/v880_full_results.json.gz --observations tw-market-data/evidence/v880/concentration_reviews/2026-11-04.json --out-dir /tmp/top10-gates
```

Frozen dated reports in `tw-market-data/rankings/concentration_gate_audit_20261104.*`
include source and code digests. Re-running from a later date may use later
archives and must not be represented as a recreation of the original capture.

## Interpretation

- Eight normalized income/cashflow quarters are numerical coverage, not a full
  original statements-and-notes review. Standalone OCF is reconstructed by YTD
  subtraction, never by summing multiple cumulative periods.
- Twenty daily reported trading values are reconciled across issuer histories
  and market archives. Actual amount is not approximated by close times volume.
- Five million TWD at five percent of median daily amount, capped at five
  sessions, is an explicit unbacktested capacity screen. It does not establish
  actual fills, spread, depth, or the ability to exit a limit-down queue.
- Subsequent-quarter revenue is nine-month revenue minus six-month revenue on
  both sides of the year-on-year comparison. It is not a profit forecast.
- Fact observations retain publication date and independent discovery time.
  AI web review is not a documented human source-identity certificate. Original
  byte availability is recorded separately from web availability.
- Unissued shares, planned gross proceeds, incremental profit, an ex-rights
  calculation and a fair value have distinct meanings. The new 8390 price
  update cannot leak into estimates before its independent discovery time.
- For 8110, volatile nonoperating dependence and a newly published Q3 event are
  explicit blockers. This audit does not silently endorse its legacy Base price.

## Regression validation

```sh
PYTHONPATH=.:tests python -m unittest tests.test_equity_offering tests.test_integration_v880 tests.test_v881 tests.test_v884_evidence_probe tests.test_concentration_gate_audit tests.test_v880 tests.test_v893_tpex_daily_backfill tests.test_governance_events
```

112 tests passed locally on 2026-11-04. The associated pull-request workflow runs
the same suites. Tests cover separate discovery clocks, invalid prices/amounts,
missing versus zero, stale TPEX history reconciliation, contradictory/future
sessions, cumulative-to-standalone cash flow, dilution and uncertified scenarios.

The actual full-model run had 2,004 rows, 832 research-rankable issuers, no
issuer calculation failures and two separately disclosed 8383 source errors.
No formal A+ or A++ was created. The ten-company audit reconciled 10/10 numerical
eight-quarter income series, 10/10 numerical eight-quarter standalone OCF series
and 10/10 twenty-session amount windows; 130 formal gate decisions remain pending.

Against the same-price baseline, reported turnover changed for 1,406 rows.
9944 falls below the existing one-million-TWD amount floor and is excluded;
all other shared Base estimates are unchanged, including all ten focus issuers.
This behavior change is a correction of the existing screen, not a new threshold.
