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

This is a **baseline for validating a research pipeline**, not yet the
multi-model calibrated predictive distribution described in the design brief.
There is no LightGBM/CatBoost, double probability, calibrated tail probability,
net portfolio CAGR, walk-forward statistical significance or optimized
portfolio weights yet.

## Commands

```bash
python -m unittest -v tests.test_alphamax
python scripts/alphamax_run.py readiness --output alphamax-research-readiness.json
python scripts/alphamax_run.py research --bundle alphamax/datasets/production
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
