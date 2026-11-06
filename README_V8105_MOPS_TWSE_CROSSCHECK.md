# V8.10.5 — 2026-10-23 MOPS / TWSE balance original-source reconciliation

**Scope:** exactly two selected footwear companies (9802 and 6965), July–September 2026 insider market flow, September 2026 reported directors' balances, and October 22, 2026 issued-share snapshot. Not full sector, not yearly out-of-sample backtest.

## Two separate official original source families

1. Original MOPS post-trade monthly `query6_1` response bytes for July, August and September 2026 (both issuers) are captured, gzipped, and SHA-256 archived in:
   `tw-market-data/evidence/v880/insider_reviews/original_probe_archive/run_39947008213_1/`.

2. Official TWSE OpenAPI `t187ap11_L` (current directors' *balances*) and `t187ap03_L` (company *issued share counts*) were actually fetched from live official endpoints (HTTP 200) and archived with original raw bytes and SHA-256:
   `tw-market-data/evidence/v880/insider_reviews/twse_current_ownership_archive/run_39953995531_1/`.
   Director holdings rows indicate **2026-09**, reported **2026-10-20**. Basic issued-shares rows indicate **2026-10-22**. These are **not** proof that the data existed at the end of July or August.

## Real original source crosschecks

`python scripts/v8105_insider_evidence_reconcile.py`

The output is committed to
`tw-market-data/evidence/v880/insider_reviews/20261023_two_official_sources_reconciliation.json`.

| Issuer | 7–9月 MOPS market net (lots) | 2026-10-22 shares issued | Net ÷ shares | September balance matches |
|---|---:|---:|---:|---:|
| 9802 鈺齊 | +1,796 | 200,991,673 | 0.89357% | **23 / 23** |
| 6965 中傑 | +311.052 | 156,336,000 | 0.19896% | **25 / 25** |

All MOPS original **per-row** opening+market movements+other movements=closing arithmetic in these six issuer/month files reconciles. Same-period September holder *name* and share balance agree across the two distinct official source families (including one numeric HTML entity name which must be decoded). This gives strong **source consistency**, not unique beneficial account proof.

Both exceed the proposed **0.05% 3-month market-net materiality threshold** when using the October 22 denominator, but this research-only materiality check is NOT the full formal insider gate.

## What is still not certified

- Shared entity names/positions across director, manager and 10% shareholder roles may be the same beneficial owner; unnamed spouse/minors have no stable account IDs. A matching aggregate/name/balance does **not** independently confirm one unique account per signature. As a result, `beneficial_owner_unique_accounts_certified=false`.
- Original market trade files captured in October are not guaranteed to have been available to the market as of earlier July/August historical investment signals. Historical **publication/revision/first seen** evidence needs independent PIT treatment.
- October 22 issued-share counts must not be retroactively used as July/August issued-share denominators without verifying all intervening corporate capital changes.
- MOPS market buys and share-balance changes are different measures. Do not infer trades from `t187ap11_L`, or make a false buy based on a gifting/trust/pledge.
- Formal 13 quality gates, 2027 projected EPS/PE, Base price, A+/A++, and Exit are **untouched**. The trading-signal strategy still lacks independently checked 252-session low-price closes and complete gross-margin-release PIT; 0050 net-total-return outcomes require 365 days of independently matched execution and corporate-action coverage.
- **Validated strategy A or B one-year alpha vs 0050: null**. Exceeding a buy-size heuristic does not constitute proof of alpha.

## Failed historical endpoint and fallback

The legacy `siis.twse.com.tw/publish/listed/115IRB110_07.HTM` through `_09.HTM` sources returned HTTP 404 on the research runner. They are marked source unavailable, **not zero holding change**. The official current TWSE OpenAPI endpoints supply September 2026 holdings and October current capital but cannot manufacture July/August archived IRB110 history.

## Validation

[GitHub crosscheck Actions](https://github.com/farmer212444/fugle-quote-server/actions/runs/39954651601): 3 unit/integration tests passed, including all 48 live-original September balances, six monthly holding movements, archive original-byte hashes, and null performance. CI requires the archived official originals to exist, rejects missing originals instead of inventing zero positions, and leaves formal quality gates PENDING.

The PR remains an **unmerged research draft**.
