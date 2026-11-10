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
