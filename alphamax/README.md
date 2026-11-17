# AlphaMax V1.0 — independent research, fail-closed

**Status: research scaffolding; no live buy signal, no certified 12-month expected return.**

This experiment is independent of the legacy V8 models. It imports no V8 factors,
scores, A+ gates or prior portfolio lists. It deliberately does **not** turn
unadjusted closing-price snapshots into investor total returns.

## What has actually been implemented

- Strict JSONL + SHA-256 input checks.
- Point-in-time availability for each feature; maturity timestamp for each label.
- Explicit gates for historic universe, delisted coverage, corporate actions,
  total-return verification, timestamps, execution quotes and source receipts.
- Trade-cost-aware regularized linear baseline (standardized ridge), trained
  **only** on returns observable before the ranking timestamp.
- 12-month rolling *cohort analysis* with full-cohort maturation and explicit
  non-executable share exclusion. Not a true backtested portfolio.
- Deterministic regression tests including future-feature rejection,
  label-leakage regression, missing receipts and non-executable securities.
- Separate GitHub Actions workflow for tests and recurring *readiness reporting*.
- **AlphaMax Concentration V1** (research-only): independent robust-return and joint-stress portfolio allocation, cash allowed, per-name/sector caps, minimum liquidity, tail-probability and confidence checks, forecast snapshot SHA-256, seven evidence assertions, and full fail-closed behavior. No imported V8 risk gates.

This is a **baseline for validating a research pipeline**, not yet the
multi-model calibrated predictive distribution described in the design brief.
There is no LightGBM/CatBoost, double probability, calibrated tail probability,
net portfolio CAGR, walk-forward statistical significance or statistically
optimized portfolio weights yet. The concentration allocator is a transparent
**greedy paper-only heuristic**, not a validated maximum-return optimizer.

## Commands

```bash
python -m unittest -v tests.test_alphamax tests.test_alphamax_concentration tests.test_alphamax_universe
python scripts/alphamax_run.py readiness --output alphamax-research-readiness.json
python scripts/alphamax_run.py research --bundle alphamax/datasets/production
python scripts/alphamax_concentration.py --output alphamax-concentration-readiness.json
python scripts/alphamax_universe_audit.py --output alphamax-universe-readiness.json
```

The final command **must** return BLOCKED until a separately audited
`alphamax/datasets/production` dataset is available and the historical training
window is adequate. Do not publish mock fixture predictions as stock rankings.

## Dataset contract

`manifest.json` and `observations.jsonl` must be co-located.
`manifest.json` must include:
- `schema: alphamax-research-v1`;
- a genuine SHA-256 `observations_sha256` of the exact JSONL bytes;
- an auditable, nonempty `source_receipts` array;
- every named boolean gate set to true with **independent documentary evidence**.

Each JSONL record needs security `code`, ISO `signal_date`, exactly the six
`features`, an ISO `feature_available_at` per feature, boolean
`execution_possible`, and optional `total_return_12m` with
`label_available_at`. A 12-month return must include appropriate price
adjustments, corporate action and dividend treatment. **Never mark the gates
true simply to silence the blocker.**

### Known source limitations, as checked November 10, 2026

`tw-market-data/prices/latest_manifest.json` reports:
- price date 2026-11-09; 1,994 TWSE/TPEx rows;
- `unadjusted_quotes: true`;
- `security_master_verified: false`.

Those historical data do not establish total-return labels, surviving/delisted
population at past timestamps or trading feasibility. They are not sufficient
for a trustworthy 12-month net-return ranking.


## 0050 historical raw-price cache continuity (2026-11-15)

The AlphaMax PR workflow now restores the most recent *successful* same-repo,
same-PR-branch Actions artifact as an **untrusted research cache**, validates
every restored original receipt and completed-month normalized-rows SHA-256,
checks the recomputed historical-session panel, and resumes at the earliest
missing completed month. A completed month's source-vintage conflict fails
closed. For the latest incomplete month, the current checkout's exchange
receipt takes precedence, without rebasing previously completed months.

The cache lives under `alphamax-0050-data/` only inside the runner: the
legacy V8 source tree is read, **not rewritten**. Each CI run downloads a
maximum of four additional official TWSE STOCK_DAY month sources. Failed
downloads remain explicit gaps. The artifact records source bytes, receipts,
derived sessions and restore progress. Previous archives remain traceable to
individual GitHub Actions run IDs.

Verified engineering observations:
- CI #79: 0050 raw-price observed sessions rose from 45 to 120.
- CI #83: restored 7 months, captured 2025-05 to 2025-08; 200 sessions.
- CI #87: captured 2025-09 to 2025-12; 283 sessions.
- CI #90: captured 2026-01 to 2026-04; 358 sessions, with
  2026-05 through 2026-08 still missing from the independent cache.
- The formal PK gap audit reads an independent original main-branch snapshot:
  its 45-session result is **not** overwritten by this temporary research
  cache. These two provenance scopes must never be combined or confused.

**Limitations:** Actions artifacts expire after 90 days and are **not a
permanent independently signed data warehouse**. Raw prices can cross a
cash-dividend ex-date or ETF share split; 0050's 2025 corporate actions
need their own official verification and share-adjusted investor total-return
ledger. A full raw-price archive alone certifies neither historical PIT
feature vintages nor 12-month after-cost returns.

The audit now requires a near-contiguous, sufficiently dense one-year raw
price window. A sparse 252-plus-session archive drawn from disjoint years
must not pass that diagnostic. Even a passing diagnostic remains
**NOT A CERTIFIED BACKTEST**.


## Next implementation milestones

1. Build audited issuer+date security master (include delisted names and
   active class) and corporate-action/dividend adjustment ledger.
2. Reconstruct a multi-year 12-month PIT feature/label panel with original
   announcement timestamps, adjusted total returns, liquidity and tradeability.
3. Introduce purged walk-forward folds (plus embargo), calibration and
   distributional uncertainty with baseline comparison.
4. Add actual execution simulation with portfolio equity curve, benchmark total
   returns and cost-sensitive turnover.
5. Document calibration, market regime tests and model-selection trial counts.
   Promote to paper trading only after all relevant checks are reproducible.

The daily GitHub workflow publishes a diagnostic artifact, not an investment
recommendation. PR CI is active upon pull-request creation, while cron only
operates after the workflow is merged to the default branch.


## Concentration decision engine: explicit boundary and dataset contract

Implementation: `alphamax/concentration.py`. Runner: `scripts/alphamax_concentration.py`.
Both are **research-only** and must never issue live recommendations or brokerage orders.
A `BLOCKED` output and 100% cash is correct if verified data are missing.

The optional production file `alphamax/datasets/production/concentration.json`
has keys:

- `candidates`: list of unique code/sector rows with identical `asof` dates,
  `horizon_months=12`, `expected_net_return_12m`,
  `lower_bound_net_return_12m`, `probability_loss_30pct`,
  `confidence`, `daily_turnover_ntd` and Boolean `executable`.
  The returns **must already be net of all trading costs**. The lower bound
  must arise from an actual out-of-sample uncertainty method, not a guess.
- `scenarios`: at least two named **joint** stress scenarios, with a
  nonnegative loss fraction (0..1) for **every** candidate in each scenario.
  Scenarios are portfolio-wide, not unrelated single-company stress guesses.
- `evidence`: `asof`, `receipt_ids` (nonempty, independently verifiable),
  `forecast_sha256` and all seven evidence gates specified in
  `alphamax/concentration.py` as actual audited `true` values.
  Compute digest with `forecast_digest(candidates, scenarios)`.
  The gates and hashes are **self-reported contract fields**, not proof that an
  external source has been independently audited; evidence must be inspected
  separately before any real deployment.
- `cash_net_return_12m`: benchmark cash opportunity return (not stock 0050).
- `policy`: optional limits defined by `ConcentrationPolicy`, including
  20% single-stock, 30% sector, 12% worst joint-stress portfolio-loss caps,
  1% allocation increments. These are preliminary limits, **not optimized**.

The result includes research portfolio weights, remaining cash, joint-scenario
losses and explicit rejection reasons. The engine purposely returns
`buy_signal=false` under all conditions, including synthetic test fixtures.
Do not bypass missing PIT, calibration or external verification by copying
Boolean values from synthetic fixtures.

**Promotion remains blocked** until real independently verified multi-year
PIT total-return data, calibrated 12m return distributions, joint stress
evidence, an executable costed portfolio equity curve, independent reviewer
signoff and paper-trading results exist. The GitHub workflow checks coding
contracts and research readiness only; it does NOT promote production automatically.

## Historical observation coverage audit (not an issuer master)

`alphamax/universe_audit.py` and `scripts/alphamax_universe_audit.py` scan
`tw-market-data/prices/issuer_history/{TWSE,TPEX}/*.json`, checking each
session's immutable market+code identity, duplicate session dates, sane
closing prices, and publication-time impossibilities. They compare those
histories with the last dated TWSE/TPEx quote snapshot and count 252-session
and 756-session coverage, invalid files, missing histories and finite
sample errors. No history is inferred from the newest close alone.

**A first or last observed price is not an official listing/delisting date.**
A market/code with many observations may still be missing delisted peers,
corporate action adjustments, dividend cash flows or contemporaneous company
information. The resulting `BLOCKED_NOT_A_PIT_SECURITY_MASTER` is intentional.
No green CI can substitute original, timestamped official listings and delistings,
independent source receipts, and corporate-action-adjusted total returns.

The GitHub workflow publishes `alphamax-universe-readiness.json` as a research
artifact and summarizes observable coverage next to the research and concentration
readiness states. Do not copy V8 certification fields into AlphaMax.

## Current official company-profile capture (NEW, prospective only)

The independent collector in alphamax/security_master.py and runner
scripts/alphamax_security_master.py capture TWSE company profiles via
https://openapi.twse.com.tw/v1/opendata/t187ap03_L and TPEx company
profiles via https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O.
If the TPEx JSON source is blocked, the official MOPSFIN CSV endpoint
https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv is tried explicitly;
the first-source error is retained in the attempt log.

Each actual raw source response is preserved byte-for-byte with its SHA-256,
fetch timestamp, ROC batch date and normalization output. The CI ZIP artifact
also includes a reconciliation of profile market/code identities with the
latest daily quote snapshot. Empty/partial sources stay BLOCKED. Old stock
profiles are never retroactively created by a current capture.

This source does not provide a queryable historical membership series; a
company's reported historical listing date alone cannot prove continued
listing on every historical day or the membership/delisting of companies no
longer in the current source. Different securities in quote data (such as
ETFs) need separate class information. The source capture therefore never
turns historical_PIT_universe_approved or investment_certified to true.

Run:
    python -m unittest -v tests.test_alphamax_security_master
    python scripts/alphamax_security_master.py --output-dir alphamax-profile-capture

GitHub Actions raw artifacts currently expire in 90 days. They are not a
permanent audited as-of vintage archive. A dated, immutable source archive
and full historical delisting event ledger must be implemented and
independently reviewed before this data can be admitted to real backtests.


## TWSE historical delisting event evidence (retrospective)

AlphaMax now ingests the TWSE official "terminated listing" historical table:
https://www.twse.com.tw/company/suspendListingCsvAndHtml?lang=zh&type=html

- The independent event collector in alphamax/delist_ledger.py tries official
  CSV first, falling back to the official HTML table.
- It stores the raw response with a SHA-256 byte digest, capture timestamp,
  event effective date, market/code/name and an explicit 4-digit/6-digit split.
- It rejects duplicate market/code/effective-date events, invalid issuer codes,
  impossible future dates and unrecognized dated rows. Its CI output is a
  research artifact only, not a trading engine.
- The effective date of termination is NOT the first public announcement date,
  last executable trading day, merger consideration or realized investment
  loss. These require separate independently dated exchange disclosures.
- TPEx historical delisting is NOT included in this collector. Until both
  markets, past listed issuers, original announcement timestamps and investor
  total-return paths are reconstructed, historical/PIT stock universes and
  production expected-return rankings remain BLOCKED.
- An event appearing in a retrospective 2026 download may be used to mark
  historical missing/delisted observations for reconstruction, but cannot be
  used as a preannouncement predictive input in a 2024, 2025 or 2026 backtest.

Run (online GitHub Actions environment):
    python -m unittest -v tests.test_alphamax_delist
    python scripts/alphamax_delist.py --output-dir alphamax-delist-capture

CI reports are immutable per run but the artifact retention is 90 days;
it is not a permanent independent original-source archive.


## TPEx terminated-OTC historical year slices (2021–2026)

A separate official-source collector uses the TPEx webpage-declared action
`company/deListed`, served at
https://www.tpex.org.tw/www/zh-tw/company/deListed?response=json
and year-filtered requests with exact `date=YYYY&reason=-1&response=json`.
This route was verified from the official TPEx terminated-OTC webpage
https://www.tpex.org.tw/zh-tw/mainboard/listed/delisted.html,
rather than derived from 2026's current listed-company names.

Collector: `alphamax/tpex_delist_ledger.py`
Runner: `scripts/alphamax_tpex_delist.py`
Tests: `tests/test_alphamax_tpex_delist.py`

Each reported historical year is admitted to a **bounded retrospective event
ledger** only when the response echoes the requested year, every event has a
valid effective termination date in that year, and the provider's
`tables[0].totalCount` equals the parsed row count. Every accepted source
year preserves its raw JSON and SHA-256 receipt. When a year is incomplete,
missing, mismatched or has unsatisfied pagination, that year is left
unverified. This is *not* a listing-date or delisting-announcement vintage
certification. The current public form starts at 2021, so any older TPEx
company history remains unproven from this source.

Six-digit history codes (e.g. 911613 in 2021) are **preserved as historical
events**, but tagged `security_class_review_required=true`; they are not
implicitly ordinary four-digit stocks. The termination reason is retained as
official raw text without guessing bankruptcy, merger consideration, share
conversion terms, last executable close or realized investor loss.

The outcome always sets `investment_certified=false` and
`full_history_coverage_verified=false`, even if all bounded annual slices
pass. Missing full historical PIT membership, corporate action and dividend
ledgers, public-announcement vintages, and valid investment total returns
still block a formal AlphaMax Top 20 or a concentrated position decision.

## Independent operating-to-EPS and entry-price bridge (2026-11-17)

`alphamax/earnings_bridge.py` adds a calculation layer for explicit annual
bear/base/bull operating assumptions. It computes gross profit, operating
profit, pretax income, tax expense, profit attributable to the parent,
diluted EPS, positive-EPS P/E scenario prices, and a maximum entry price for
an explicitly chosen net return through a dated valuation horizon.

It does **not** estimate its own operating assumptions or probabilities,
authenticate original source bytes, generate portfolio weights, or certify
concentration eligibility. It cannot feed the concentration allocator's
calibrated-return fields. Its status is always
`SCENARIO_RESEARCH_ONLY_NOT_CALIBRATED`; `buy_signal` and
`investment_certified` remain false. A future model must learn and validate
the assumptions and return distributions separately.

Run with an explicitly prepared JSON specification:

```sh
python -m alphamax.earnings_bridge assumption-spec.json
python -m unittest discover -s tests -p 'test_alphamax_earnings_bridge.py'
```

The input contract is `schema=alphamax-earnings-bridge-v2`, `code`,
`currency=TWD`, `shares_unit=shares`, timezone-aware `asof`, a later
`valuation_date` in YYYY-MM-DD, nonnegative `required_net_return`, and:

| Input | Required fields and interpretation |
| --- | --- |
| `source_receipts` | Nonempty list of unique `id`, HTTPS `source_url`, declared original-byte `sha256`, timezone-aware `published_at` and `observed_at`. Both clocks must precede `asof`; source declarations alone do not authenticate bytes or prove PIT history. |
| `quote` | Positive `close_twd`, timezone-aware `available_at`, and a known `source_receipt_id`. Quote age is disclosed, never silently updated to a later price. |
| `costs` | Explicit `buy_fee_rate`, `buy_slippage_rate`, `sell_fee_rate`, `sell_tax_rate`, `sell_slippage_rate`; no assumed broker tariff. |
| `scenarios` | Exactly `bear`, `base`, `bull`; each has all operating fields below, an `assumption_note`, and nonempty known `source_receipt_ids`. |

Each scenario specifies `revenue_twd`, `gross_margin` (fraction, not percent),
`operating_expenses_twd`, `other_operating_income_twd`,
`net_nonoperating_income_twd`, `effective_tax_rate`,
`noncontrolling_profit_twd`, actual `diluted_shares`, positive `exit_pe`, and
`net_dividends_per_share_twd`. Money amounts are actual TWD, not report
thousands/millions. Net dividends mean cash received per initial share by
the valuation date, after any assumed investor dividend tax and without
reinvestment. Split/conversion paths and bank/insurance balance-sheet
valuation require separate models; they are not simulated here.

Formulae:

- Parent profit = `(revenue * gross_margin - operating_expenses +
  other_operating_income + net_nonoperating_income) - tax - noncontrolling_profit`.
- Tax = `max(pretax_profit, 0) * effective_tax_rate`; no speculative tax
  credit is created for losses. Nonpositive EPS leaves P/E value and entry
  ceiling null rather than fabricating a fair price.
- Net proceeds = `scenario_price * (1 - sell_costs) + net_dividends`.
- Net return = `net_proceeds / (entry_price * (1 + buy_costs)) - 1`.
- Entry ceiling = `net_proceeds / ((1 + required_net_return) * (1 + buy_costs))`.

Cash dividends are not charged stock sale tax. Horizon returns are labeled
through `valuation_date`, never relabeled as 12-month returns. Bear/base/bull
names do not prove scenario price ordering or a maximum-loss bound; the
output flags ordering failures. Input hashing permits change tracking,
not independent source certification. Synthetic regression tests cover
financial reconciliation, dilution, cash-dividend cost treatment, entry-price
inversion, loss companies, input timestamps, units and false calibration.

## Shared factual income integration (2026-11-18)

`alphamax/reported_income.py` independently reads shared normalized official
general-industry MOPS income snapshots, without reusing V8 estimates, scores
or certification fields. The runner `scripts/alphamax_reported_income.py`
requires an explicit original unit declaration, preserves YTD period scope,
and checks the exact normalized-file SHA-256 against its capture manifest.
The source Git commit, file digest, source URL, fiscal period and capture
clock are retained. These checks do not authenticate the original response
or establish an issuer's actual filing-publication timestamp.

The focus set is 2330, 2317, 6206 and 9802. Missing issuers and mixed fiscal
periods are disclosed per company; coverage of these four is not whole-market
coverage. Blank required lines are rejected, rather than turned into zero.
Revenue/cost/gross profit, operating/nonoperating/pretax, tax/net income and
parent/noncontrolling attribution are reconciled within one source unit.
When an optional other-operating line is blank, any algebraic residual is
labeled derived; that line is not claimed as independently checked.

The first real-data run is frozen in
`research/2026-11-18-reported-income.json` against shared source commit
`de6c94b35e69ac36a6b434da8526ccacae89517f`. All four requested 2026Q3
YTD income records reconcile. TSMC's other operating income is TWD
7,453,368,000; omitting that line from gross-profit-minus-expense math would
understate reported operating profit. The operating scenario contract is
therefore v2 and now requires explicit `other_operating_income_twd`. A v1
specification must be amended explicitly; missing amounts never default to
zero. Reported basic EPS is preserved as a sourced observation, not recomputed
by inferring diluted shares from rounded EPS or share capital.

CI stages the pinned shared main-branch manifest and exact normalized source
bytes in `alphamax-reported-source/`, outside both legacy V8 data and AlphaMax
production datasets. It publishes the separate report as an artifact. A
source gap is reported as BLOCKED and does not generate a forecast or trade.
The normalizer does not annualize nine-month earnings into an annual forecast.
Actual diluted weighted-average shares, full statements/notes, forward
operating assumptions and calibrated return distributions remain missing.

```sh
python scripts/alphamax_reported_income.py \
  --source-root alphamax-reported-source \
  --source-ref-file alphamax-pk-source/source-commit.txt \
  --money-unit TWD_thousands --period-basis year_to_date \
  --output alphamax-reported-income.json
```
