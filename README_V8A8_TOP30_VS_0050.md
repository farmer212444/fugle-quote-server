# Forward experiment: research TOP30 versus 0050

**Status: predeclared forward-selection design, NOT validated investment results.**
This adds an auditable new monthly experiment to the existing research pipeline.
It **does not** declare that TOP30 beats 0050, and it does **not** place orders.

## Fixed policy before outcomes

- Policy: `tw-market-data/config/forward_top30_0050_v1.json` (hash recorded per selection).
- Activation: **2026-10-23 00:00 Asia/Taipei**. Never recast older research vintages as this experiment's actual predictions.
- Formation: the first genuinely archived `current-information` variant of each Taiwan calendar month on or after activation. If the workflow misses a month, do **not** retrospectively invent its selection.
- Universe: exact top 30 of the frozen `top30_quality_priority` list, restricted to existing original-numeric research candidates. Equally weighted; reference capital **NT$10,000,000**, purely hypothetical.
- A separate formal-A+ strategy remains in **cash** until all 13 original gates pass. A research TOP30 is **not** A+.
- Allocation signal is recorded at **actual program publication time**, which cannot precede the archived research creation or policy activation. No use of same close for assumed fills.
- Execution policy: after signal, the *next actually eligible trade/open*, respecting 5% daily value/volume participation. Unfillable orders remain cash until verifiably filled, never magically at an advantageous close.
- Transaction-cost policy fixed in JSON, and distinguished from actual broker fills. Model ranking may not be adjusted after seeing realized outcomes.
- Benchmarks: 0050 **dividend-adjusted total return** (investable ETF) and TAIEX **total return** (noninvestable benchmark). Periods: 1, 3, 6, 12 months; time-matched and including all issuer dividends, splits and delistings.

## Current implementation

`python scripts/v8a8_forward_top30_0050.py`

1. Validates immutable original research archival receipts.
2. Refuses preactivation signals and retrospective formation.
3. Saves first monthly Top30 with policy SHA, source SHA, selection SHA, timestamp and 2027 Base frozen assumptions in `tw-market-data/experiments/forward_top30_0050_v1/monthly/YYYY-MM.json`; refuses changing an existing selection.
4. Publishes `latest_status.json` with explicitly **null** model/0050/index returns, alpha, drawdown and hit rate until independently verified execution, complete company actions and benchmark history exist.
5. Will run in the **existing** V8.8.2 research GitHub Action after the freeze/observation phases. **No new cron**.
6. Tests prove activation/first monthly signal, idempotence, tamper resistance, policy-change rejection, A+ separation, and no fake performance.

## Outstanding — do not mark success yet

This commit does **not** implement/verify matched full-history execution returns or the 0050 benchmark collector. To publish genuine alpha, add an independent receipt-backed, timestamped official 0050/index total-return collector and issuer corporate-action registry, next-open/partial-fill evaluator using `tw_model_v880.execution.net_trade`, and out-of-sample inference respecting non-overlapping horizons and trial multiplicity. Include brokerage/tax/ETF cost differences. Until these are complete, report is correctly `MONTHLY_TOP30_FROZEN_AWAITING_VERIFIED_FILLS_AND_BENCHMARK` with **null returns**.

### Useful testing commands

```bash
python -m unittest -v tests.test_v8a8_forward_top30_0050
python scripts/v8a8_forward_top30_0050.py
```

This is an *actual precommitted experimental selection*, not reconstructed 2025-12-31 stock picks, which remain PIT-blocked.
