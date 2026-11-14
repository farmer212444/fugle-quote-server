# AlphaHunter V1: independent high-return opportunity research

**State: PROTOTYPE / UNCALIBRATED / NOT INVESTABLE.** No production buy list, no A+,
no 2027 calibrated expected returns, and no AlphaMax/V8 performance claims.

## What is different
AlphaMax is a regularized statistical research baseline; V8 uses quality gates.
AlphaHunter instead begins with an auditable **scenario payoff distribution**,
the cost to buy/sell, a downside penalty, an operating-cash-conversion penalty,
a leverage penalty, and a separate profitability-inflection flag.

For every as-of input stock:
- 25% bear, 50% base, 25% bull are *illustrative, not calibrated probabilities*.
- Each scenario gross payoff = (EPS × assumed PE + cash dividend) / observed
  reference close - 1; subtract 0.6% illustrative round-trip trading costs.
- Score = scenario-weighted payoff - 0.35 × bear-loss - 0.08 × cash-conversion
  shortfall below 0.75 - 0.025 × net-debt/EBITDA excess above 2.
- Inflection evidence is a *separate* indicator: sales growth ≥10% and gross
  margin up ≥0.50 percentage points. It does **not** secretly change rank.
- Weights are initial research hypotheses, not validated or optimized alpha.

This is not calibrated 12-month expected return or a reliable order of winners.
Do not promote the scenario score to a trading recommendation.

## Inputs and PIT safeguards
Research bundle folder: `manifest.json` and `observations.jsonl`.
Manifest requires schema `alphahunter-research-v1`, SHA256 of raw observations,
all six provenance gates, and nonempty source receipt references. Those flags
are declarations only; they **cannot prove an independent audit**.

Each JSONL row requires:
- `code`, `signal_date`, `reference_price`,
  `reference_price_available_at`, `forecast_available_at`,
  `execution_possible`.
- `features`: `revenue_yoy` (decimal), `gross_margin_change_pp`
  (percentage points), `cash_conversion` (ratio),
  `net_debt_to_ebitda` (ratio), each with `feature_available_at`.
- `scenarios` keys `bear`, `base`, `bull`; each has `eps`, `pe`,
  `dividend`. Their implied total values must be ordered.
- Optional `realized_total_return_12m` and `label_available_at`; when
  provided, labels cannot mature before 12 calendar months after signal.

The reference close is a **research reference price**, never proof of actual
execution at that price. Corporate actions, delistings, liquidity, data
publication time and realistic fills need independent external verification.
This first version uses date-level PIT; it is **not** intraday PIT certified.

## CLI
```sh
python scripts/alphahunter_run.py readiness
python scripts/alphahunter_run.py research --bundle /path/to/audited-data --asof 2024-12-01 --top-n 10
python -m unittest discover -s tests -p 'test_alphahunter.py' -v
```

The production dataset intentionally does not exist. Running readiness
without it must print `BLOCKED`; a research result can only be emitted when a
contract-conforming bundle is supplied, and still remains `UNCALIBRATED_RESEARCH_ONLY`.

## Next prerequisites before formal evaluation
1. Audit each issuer's historical PIT membership (including delisted names),
   actual filing availability timestamps, and original receipts.
2. Reconstruct split/dividend/rights/delisting-adjusted **12-month total
   returns** with audited open/close execution and turnover/capacity.
3. Freeze unmodified candidate-selection and scoring rules **before** OOS tests;
   compare on the same dated universe with V8, AlphaMax and 0050.
4. Measure 2025/2026 matured cohorts, benchmark-relative total returns,
   turnover, slippage, tail drawdown and selection uncertainty. Calendar-year
   2026 12-month labels may still be immature in November 2026.
5. Only after independent review may another version enable rankings or
   investment certification; this PR never alters the existing two engines.

**Do not merge solely because CI passes.** Synthetic checks establish software
properties only, not market outperformance.


## Independent EPS bridge (research-only)
`alphahunter/earnings_bridge.py` exposes `build_eps_scenarios(financials, assumptions, signal_date)`.
It derives each scenario's EPS from a **trailing reported revenue baseline**,
assumed sales growth, gross margin, operating expense ratio, net non-operating
income, estimated cash tax rate and fully diluted shares:

```
scenario_sales = trailing_reported_revenue × (1 + scenario_growth)
scenario_operating_profit = scenario_sales × (gross_margin - opex_ratio)
scenario_net_profit = (scenario_operating_profit + net_nonoperating_income)
                      × (1 - tax_rate)  # only for positive pretax income
scenario_eps = scenario_net_profit / diluted_shares
```

All monetary amounts must be **TWD, not NT$ millions**, and all shares must be
actual individual diluted shares, not lots. Each financial record carries its
original fiscal period end and *declared* public availability date, and every
research assumption carries an as-of date. No input can postdate the
signal. The as-of flags require **independent original filing verification**
before any result can be treated as publicly available in the real market.

P/E is not defined for losses. For a loss-making scenario only, the earnings
bridge provides a **zero EPS P/E payoff proxy** and separately preserves its
negative raw EPS and `loss_making_scenario_not_pe_valued=true`. This is a
diagnostic floor and *not* an independently defensible terminal equity
valuation. Validate balance-sheet values, liquidation risk and capital
raising separately before applying the model to distressed firms.

The bridge's outputs fit the existing `scenarios` field but are
**uncalibrated**, not forward earnings endorsed by the exchange, a broker, or
the model. Historical training labels still do not exist in the production
dataset, and the first version never issues a trade signal.

```sh
python -m unittest discover -s tests -p 'test_alphahunter*.py' -v
```
