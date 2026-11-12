# V8 vs AlphaMax: frozen exhibition PK — evidence first

**Research study, NOT an investment recommendation, not an official certified
out-of-sample backtest, and NOT model-vs-model.**

The fixed, original teams are stored in:
`alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json`

- Alpha lane is a human-picked independent research triage from the existing
  `2026-11-10-top20-evidence.md` memo. It does not come from trained AlphaMax.
- V8 lane is the Growth research screen, not the certified V8 A+ model.
- Both lists contain ten stocks; there is no stock overlap.
- Both use the same **2026-11-10 official raw closing-price reference**.
- Both lists were frozen on 2026-11-11, so **2026-11-11 raw closing-price
  changes are retrospective observation only, NOT a fair executable entry and
  NOT PK performance**. No winner is allowed from that snapshot.

## Already implemented

`alphamax/pk_exhibition.py` validates two unchanged 10-security lists,
immutable security identities (market plus code), price dates, duplicate
quotes, quote coverage, and an original source-freeze SHA-256 digest. The
`observed_quotes()` function reports daily **unadjusted close-to-reference
change, solely as an observation**. It does not produce adjusted total
returns, trades, an official winner, or a model superiority claim.

`evidence_scorecard()` provides a *separate*, strict total-return input
contract for a future matched 21/63/126/252-session test. It requires:

- Exactly the same strictly post-freeze first session for all 20 securities
  and one **0050 ETF** benchmark.
- Exactly the registered number of unique ordered trading sessions with
  matched end dates and mature outcome dates; an independently verified
  exchange calendar is still needed.
- 21 nonmissing, identity-matched investor total-return factors, covering
  dividends and all relevant corporate actions including delisting.
- Per-stock source receipts and explicit dividend/company-action review flags.
- Matched share trading costs (configurable reference costs); ETF reference
  has a different selling tax.

Even fully populated self-reported inputs return
`CONTRACT_ONLY_EXTERNAL_AUDIT_REQUIRED` and **no official winner**.
A receipt string or `true` flag cannot establish that the original
corporate actions, fills, dividends, bid/ask and corporate-finance adjustments
were independently verified.

## Reproduce

Run tests:
```bash
python -m unittest -v tests.test_alphamax_pk_exhibition
```

With a main-branch official snapshot and its manifest from the **same commit**:
```bash
python scripts/alphamax_pk_exhibition.py \
  --manifest alphamax-pk-source/manifest.json \
  --snapshot alphamax-pk-source/prices.json \
  --output alphamax-pk-observation.json
```

The `.github/workflows/alphamax-research.yml` workflow fetches the
latest `main` manifest and precise corresponding archived JSON quote file
from the same main commit, runs the independent tests, writes the diagnostic
artifact, and explicitly states there is **no certified winner**.

## What is still blocking a real PK?

1. **Actual model vs model**: AlphaMax must independently train and rank using
   audited PIT data. This frozen exhibit is AlphaMax *human research vs V8
   research*, not AlphaMax predictive engine vs V8 predictive engine.
2. **Execution**: first common tradable opening quote strictly after the
   2026-11-11 vintage date, with market/calendar and tradeability receipts.
   The reference closes cannot be retroactively assumed as trades.
3. **Investor outcomes**: all cash dividends, ex-right/ex-dividend, splits,
   delistings, corporate actions and end-to-end trading costs must be audited
   for all 20 names and 0050.
4. **Performance statistics**: matured 21/63/126/252-session benchmark excess,
   max drawdown and tail risk under the same independent PIT/OOS protocol.
5. **Official results**: require independent original-source audit and human
   reviewer signoff before labeling a winner. A passing CI only establishes
   programming contracts.

Do **not** transform the initial raw-close comparison into a forward return.
A favorable raw close move on 2026-11-11 is uninvestable evidence for this
freeze; that date was chosen only to test the diagnostic data path.

## New: pinned post-freeze prospective PRICE-ONLY shadow tracking

The archived 2026-11-12 official market session now exists in main as
`tw-market-data/prices/2026-11-12.json`, containing quote **open and close**
for all 20 exhibition names and ETF 0050. The reference quote date is
2026-11-10 and the selection freeze date is 2026-11-11. For a forward
*research* shadow display, the shared first **post-freeze** auction-opening
price proxy is fixed to **2026-11-12**. It cannot be reselected retrospectively
to maximize performance:

- Module: `alphamax/pk_shadow_monitor.py`
- CLI: `scripts/alphamax_pk_shadow_monitor.py`
- Tests: `tests/test_alphamax_pk_shadow_monitor.py`
- Entry blob Git SHA-1: `58231b3ee3e6fcd3a96aa02c379eb40496c9d8d6`
- Entry prices are separately fetched from `origin/main` and fail closed if
  their original Git blob differs. The daily latest snapshot and its manifest
  are fetched from **the same main commit**, and the cohort weights use
  equal INITIAL capital per frozen ticker (no daily rebalancing).
- A missing open in the baseline or missing 0050 entry prevents shadow
  initialization. A missing latest issuer price blocks its entire ten-name
  result rather than pretending an unknown delisted/suspended stock returned 0%.
- A valid latest 0050 price is necessary to show excess relative to 0050.

**All output returns are raw price ratios, NOT investor profits or model
skill.** Opening-price records are official reported prices, but the archive
declares `fillability_verified=false` and `open_at` is only a scheduled
session timestamp. Therefore these quotes do not prove execution of an
actual order of any size, especially during wide opening gaps. Raw prices also
omit dividends, corporate actions, delisting payouts, brokerage fees, stamp
duties, and spread/slippage. The program returns `official_winner=null` and
`is_model_vs_model=false` in all cases.

The main-branch quote archive is research evidence, not yet a signed,
independently reviewed investor total-return ledger. On future sessions, the
monitor may report *price-only* change since the same 2026-11-12 opening price
if the archive is present and untampered. Nothing runs on the default branch
until the PR workflow is merged.
