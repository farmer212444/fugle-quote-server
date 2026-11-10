# V8.10.8 Prospective Drawdown Shadow — first-issued frozen cohort

## Objective
Prevent 2026-11's retrospective loss investigations from being presented as predictions made before those losses. We have historical research vintages (V8.9.7), but the newly introduced full-market drawdown warning layer must separately retain its **first actual registration date**, full live-market universe and immutable risk classifications.

## Data and integrity
- `scripts/prospective_drawdown_challenge.py issue` runs on main after the official reference-price/multi-issuer risk observation step; PR only runs synthetic tests and an uncommitted smoke check.
- It verifies **risk-report schema, exact quality source SHA, matched model formation and quote day, full market quote snapshot SHA, zero A+ and zero trade signals, and zero OOS performance claims**.
- Every snapshot member, including missing/invalid closes, is recorded in `experiments/prospective_drawdown_v1/cohorts/YYYY-MM-DD.json`. The manifest SHA and per-member risk label are sealed with a cohort digest. A repeated main-workflow run **does not change** the first registered risk labels, prices, or timestamp.
- The date in the filename is **the observation's market close date**, never the first-issue timestamp or retroactively available action date. `registered_at_utc` is the true first-issue time, recorded by the GitHub runner. `next_session_eligible_only_after` always equals that registration moment. The actual next market open and broker fills remain pending.
- The registration script refuses to first-register a market close older than seven UTC calendar days. This prevents old crash records being presented as current alerts. Only already frozen records may be re-verified later.
- Tests cover tampered historical warnings, missing market members (survivorship), incorrect quote/quality SHA, a not-yet-formed model, older reports and idempotency.

## Evaluation
First-registered prospective cohorts may be scored **only after actual later exchange sessions**, not with any data before registration. A valid score requires stock and benchmark matched trading days, independent original total-return adjustments, corporate actions and delistings, credible execution-cost policy, and OOS comparisons by matched sector/size/volatility. Planned horizon: 21 and 63 reference exchange sessions from the first eligible *future* open. No outputs are currently scored, and no improvement in maximum drawdown or win rate may be reported.

**Formal A+/13 gates remain unchanged. No buying, selling, concentration approval, percentage success, or price target is issued.**

## Commands
```bash
python -m unittest -v tests.test_prospective_drawdown_challenge
python scripts/prospective_drawdown_challenge.py report
python scripts/prospective_drawdown_challenge.py issue
```
The last command registers the first cohort in the current worktree, so it is only invoked during the successful main-branch publication stage.
