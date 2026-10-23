# V8.10.5 | Footwear insider buying + low price + gross margin recovery

**2026-10-23 PRE-REGISTERED RESEARCH HYPOTHESIS. This is not a completed
historical return backtest, and does not modify the V8.10.5 production ranker.**

## Fixed independent conditions

1. Three *consecutive* full report months of strictly positive verified
   market-trade net insider purchases, original account/role deduplication,
   and 3-month cumulative market buys-minus-sells >= **0.05%** of independently
   verified shares outstanding.
2. Reference close in the **bottom 20%** of the range of the previous 252
   completed and exchange-verified trading-session *closes* at the actual
   disclosure-driven signal timestamp, not a reconstructed 52-week high/low.
3. The last two consecutively published standalone quarters have gross margin
   improvement >= **1.0 percentage point**, computed from actual quarterly
   gross profit and revenue (not year-to-date); source publication and first
   archive receipt must both precede the signal.

Wait until every input is publicly known. Taiwan insider monthly change
disclosures for a month are normally filed during the following month; never
assume Sep buying was observable by a trader in Sep.

## Exactly what an independent 12-month test will require

- Start the experiment as no earlier than **2026-10-23** for real prospective
  claims. Retroactively assembled older cases are labelled in-sample
  historical hypothesis inspection, never post-registration live predictions.
- First actually executable trading session **after** the signal, not the
  announcement day's earlier/same close; no assumed fill on suspended stocks.
- Exit only after at least **365 calendar days**, with exact dated fills.
  For each stock, benchmark **0050 dividend-adjusted net total return** over
  matched entry/exit sessions and the same independently verified costs.
- Complete original issuer/ETF dividends, splits, rights, delistings, broker
  fees, transaction taxes, slippage and capacity review; a trade accounting
  module's source booleans are not independent proof.
- No duplicate or overlapping windows for one issuer. A small correlated
  footwear-only cohort cannot yield reliable precision by counting every
  overlapping month as a new independent success.
- Publish a descriptive win rate, Wilson 95% interval, and average arithmetic
  excess percentage points only after **>=30** independently audited matured
  events. 60% is a preregistered *target*, not a measured win rate.

## Live historical readiness at 2026-10-23

- `tw-market-data/evidence/v880/insider_reviews/shoe_makers_202609_secondary_shadow.json`:
  six selected footwear manufacturers, Apr–Sep 2026 only; original MOPS
  purchases, unique holder identities and precise publication receipts
  **still pending**. Not a full shoe/shoe-materials census.
- `tw-market-data/financial_history/`: financial history back to 2024Q3
  with historical date-of-publication and revision certification incomplete.
- `tw-market-data/benchmarks/0050/latest_source_status.json`: Oct 2026
  unadjusted quotes, **total-return and matched corporate actions pending**.
- `tw-market-data/experiments/forward_top30_0050_v1/latest_status.json`:
  zero independently verified investment outcomes as of this report.

**Current real 12-month footwear-strategy OOS win rate: unavailable / null.**
No numeric performance claim is derived from the synthetic regression tests.

## Three-factor peer research triage, not A+ evidence

- 9802 鈺齊: Secondary Apr–Sep insider net positive each month; verified
  official post-trade original remains missing. Q1 2026 GM 15.85%, Q2
  13.94%; Oct 20 Q3 company self-reported GM approximately 13.23% —
  **quarter-to-quarter deterioration**, fails the GM recovery requirement.
- 6965 中傑: Secondary Jul–Sep net +63/+20/+228 lots; official
  identity/events still pending. Company's 2026-08-28 investor release
  reports Q1 GM ~10.1% and Q2 ~12.8% (+2.7 percentage points).
  The 2026-10-22 close 64.3 and vendor-reported 52-week extremes
  59.3–94.3 suggest proximity to the low-price region, **not** a verified
  252-closing-session window. Trading volume and next-open fillability
  must be explicitly verified before any large allocation.
- 9910 豐泰 has Sep zero net, and 6768 志強 has Jul/Aug zero net in the
  shadow source: neither meets three strictly positive recent months.
  9904 寶成 and 6890 來億 do not qualify on recent insider persistence.

Selected sources:
- TWSE law: https://twse-regulation.twse.com.tw/TW/law/DAT0201.aspx?FLCODE=FL072299
- CHUNGJYE 2026-Q2: https://www.chungjye.com.tw/zh-tw/news/2026-08-28-q2-financial-results/
- 9802 and 6965 secondary monthly filings: https://toalpha.tw/stock/9802/filings and https://toalpha.tw/stock/6965/filings

## Code and CI

- `tw_model_v880/insider_accumulation.py` — official-only,
  fail-closed 3-month account-level research overlay.
- `tw_model_v880/footwear_insider_holdout.py` — 252-close, quarter-PIT
  and 12-month matched-return research contracts.
- `tests/test_insider_accumulation_research.py` and
  `tests/test_footwear_insider_holdout.py` — synthetic tests only.
- `.github/workflows/insider-pit-research-tests.yml` — PR branch CI.

No broad historical sample, actual broker orders, schedule or A+ rating change
is created by this PR. This study is separate from the existing forward
TOP30-vs-0050 experiment.


## 2026-10-23 extension: split early A and confirmed B

**Path A — early:** same verified three monthly insider market-buying months
and bottom-20% of actual 252-session closes, but **no** gross-margin
requirement. It is explicitly exposed by
`evaluate_signal(..., require_margin=False)`; every result remains
`RESEARCH_...` rather than certified trade permission.

**Path B — confirmed:** the original
`evaluate_signal(..., require_margin=True)` additionally requires most
recent two separately published single-quarter margins to improve by >=1pp.

Reproducible repository audit:
`python scripts/v8105_footwear_two_path_audit.py`
(secondary-only source; cannot create transactions or real P&L).

As of this study, only **9802** (July/August/September secondary market net
+464/+1101/+231 lots, +1796 combined) and **6965** (+63/+20/+228 lots, +311
combined) meet the three-positive-month **secondary precheck** among the six
available footwear companies. The six are NOT a complete shoe/footwear
materials industry universe; 9938 百和 remains outside this table.
Official account-level identity, share capital materiality, and full 252
price-window proof are missing, so **certified A and B signals = zero**.

GM evidence context:
- 9802 2026Q2 ~13.94%, 2026Q3 company self-report 2026-10-20 ~13.23%;
  no quarter-over-quarter margin recovery for B.
- 6965 2026Q1 10.1%, Q2 12.8% (company Aug 28 release) suggests B's
  margin test may pass, but official insider and close-history PIT gates
  remain pending.

### Matched one-year outcomes, conditional selection, and bias

`tw_model_v880/footwear_strategy_pair.py` reports **A full cohort**, the
**A subset of B-confirmed episodes**, and the **B-confirmed subset** separately.
An A episode that *never* confirms B stays recorded as B-no-signal, not silently
discarded. B occurs at its own public-knowledge timestamp and can **never**
be backdated to A's entry. If an outcome is unmatured, nonexecutable, or
lacks full 0050 net-total-return audit, the affected win-rate remains null.

Even after 30 matured records in each arm, B vs A among later-confirmed
stocks alone is a *conditional subset comparison*, **not** proof one
standalone strategy performs better across all opportunities. Measuring
the investor's deployable full-cohort B strategy requires an additional
explicit cash/0050 opportunity-cost policy for the stocks that never
confirm, no hindsight selection, and historically frozen portfolios.
All calculations must remain prospective/OOS after 2026-10-23 for actual
predeclared model performance.

This extension does **not** modify main, formal A+, Exit, future cash
dividend estimates, 2027 EPS or PE.
