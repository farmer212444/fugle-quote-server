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


## 2026-09 footwear insider research shadow (2026-10-20)

Supplemental source: \`tw-market-data/evidence/v880/insider_reviews/shoe_makers_202609_secondary_shadow.json\`.

- Six **selected footwear companies**, not a full sector census: 9802/9910/6965/
  6768/9904/6890. Secondary monthly market-net lots for Apr–Sep 2026:
  **+3254 / +5033 / +1143 / +95 / 0 / −42**, respectively. Derived from
  https://toalpha.tw/stock/{issuer}/filings; not directly from original MOPS
  post-trade declarations.
- \`scripts/tw_insider_shadow.py\` recalculates all six monthly totals, ensures
  source URLs and issuer identities align, and rejects any claim of completed
  official origin, valuation override, insider quality-gate PASS or auto Exit.
  Offline account/role-de-duplication tests use synthetic events only.
- Account types (personal, nominee-held, related family members, legal entities)
  are distinct. Do not add the same holdings repeatedly for directors who also
  appear as managers or major shareholders. Holder display names are not
  guaranteed to be unique stable identities.
- **9802:** Sep MEINDL INT'L +231 lots as nominee account; the month-by-month
  change 26,715→26,946 lots does not match another September holdings table's
  26,947. Preserve the one-lot difference until original declarations are
  independently reconciled. Nominee purchases are not chairman's personal
  trades.
- **9910:** 20,000 lots recorded as Apr *other-cause decrease* must NOT be
  classified as stock-market selling.
- **6890:** a third-party insider-holding estimate of 104.1% is invalid for
  share-percentage purposes; issuer identity/role de-duplication is required.
- The \`6768\` 2026-09 +89 lots is visible in a newer indexed result but some
  third-party snapshots still end 2026-08. Do not overwrite missing original
  document vintages with a claimed direct MOPS check.
- Official MOPS monthly declaration originals, their bytes/hashes, first
  publication timestamps and stable holder/account identities were **not
  obtained** in this pass. Official TWSE t187ap11_L is a *holdings balance*
  endpoint, not proof of market purchases/sales, and is not a substitute for
  the post-trade event report.
- Formal \`insider_claims\` gate stays **PENDING**; the shadow records are
  never PIT backtest inputs or automatic A+/A++/EPS/PE/Base/Exit changes.
  No new scheduled job or automatic alert was created.
