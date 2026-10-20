# V8.8.1 Official Chip Evidence — fail-closed pipeline

Official original sources:
- TWSE T86: https://www.twse.com.tw/rwd/zh/fund/T86
- TPEx three-institution per-stock: https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading
- TDCC ownership distribution: https://openapi.tdcc.com.tw/v1/opendata/1-5

The feeds have different date conventions, investor definitions, and refresh schedules. All net quantities are **shares**, not lots. TWSE reported non-dealer foreign is separate from foreign proprietary dealers. TPEx official total is retained verbatim, not inferred from incomplete components. TDCC levels 12–15 are statistical shareholder buckets, **not identified insiders**.

## Operation

The new GitHub Actions workflow (tw_chip_evidence.yml) captures independently at 20:10 Taiwan time Monday-Friday, and attempts TDCC weekly update on Saturday. No new ChatGPT reminder task is created.

Offline tests: python -m unittest discover -s tests -p 'test_tw_chip_*.py' -v

Connected execution:
1. python scripts/tw_chip_capture.py
2. python scripts/tw_chip_diagnostic.py

A successful capture archives normalized exchange reports, raw gzip responses, dated receipts, original and normalized SHA256, plus a complete two-market manifest only if both exchanges show the same date. TDCC daily API's most recent published weekly observation is stored with its source response and receipt. Source failures do not erase previous snapshots. All failed and successful HTTP source attempts are retained in the Actions artifact for 90 days.

The diagnostic reads the existing full issuer queue, then computes independently observed daily net values, 5/20/60 **actual session** aggregates, and two-snapshot TDCC ownership-bucket change only if verified historical snapshots and individual issuer records exist. Unobserved data remains null; no fabricated zero or PIT backfill.

## Explicit limitations

1. This is not a complete securities master, margin/borrow/short-series source, or verified beneficial-owner/insider identity service.
2. Initially no historical 5/20/60-session chip windows are available; cloud endpoints can deny GitHub hosted requests. Passing offline tests is not a claim of successful live capture.
3. Historical investment backtests require historically accessible original records, dated issuer universe, announcements/revisions, and corporate actions. Do not infer past availability from a modern snapshot.
4. Chip evidence does **not** directly change EPS/forward PE, the 2027 scenarios, Exit, or A+/A++ labels. All original 13 evidence gates remain necessary.
5. Any unavailable or stale evidence is a visible PENDING status, never a certified marketwide result.

## Next verification requirements

1. Reconcile 1,978 financial identities, including 1,059 unmodeled, to a dated official security master.
2. Confirm the live TWSE/TPEx/TDCC official response schemas on the GitHub runner and preserve failure receipts.
3. Add and audit margin/short/borrow/insider public data by official identifiers and published availability.
4. Accumulate full historical observations and calibrate chip ranking weights on genuine walk-forward tests only.

## 20-session institutional retreat research watch

The existing chip diagnostic also publishes an unpromoted stock-level
\`institutional_retreat_20d\` status, never a trade, formal A+/A++ promotion,
Exit, or a separate scheduled task.

- Trigger: **trust net selling over 20 individually observed, dated exchange
  snapshots is at least 0.30% of officially reported issued ordinary shares**.
  Both sides are counted in **shares**, not lots; exactly -0.30% meets the
  threshold. The denominator must come from the hashed V8.8 evidence snapshot,
  with a dated official company share record and source receipt no later than
  the model reference price date.
- When 20 snapshots, source hashes, dated shares, or issuer identity are missing,
  the value is \`PENDING_*\`, never zero. A single source outage does not
  erase previously captured data or stop unrelated issuers.
- An observed breach is \`OBSERVED_RETREAT_REQUIRES_FUNDAMENTAL_REVIEW\`.
  This triggers **analyst review**, not claims that funds knew undisclosed
  results. Require a separate, issuer-specific public accounting bridge
  and contemporaneous publication receipts before making any stronger
  economic inference.
- \`complete_trading_calendar_independently_certified=false\`: twenty
  observations do not by themselves prove twenty *consecutive* official
  market sessions. This signal has not been PIT performance-calibrated.
- Files are incorporated into the existing chip coverage output at
  \`tw-market-data/rankings/chip_coverage.json\`. No extra schedule,
  notifications, forced Exit, or EPS/PE/Base override are created.

Offline tests:
\`python -m unittest discover -s tests -p 'test_tw_chip_*.py' -v\`.
