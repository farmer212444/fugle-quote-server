# V8.10.5 September Insider Accumulation Research Overlay (2026-10-23)

**Status: unpromoted, synthetic tests only.** This feature is an isolated
research shadow, not an empirical return factor and not part of the formal
13-gate A+/A++ classifier. No trades, alerts, EPS/PE changes or Exit results.

## Motivation

Board buying headlines may mix legal entities, spouses, directors, off-market
transfers, pledges, and share-balance changes. The existing insider-shadow
script leaves the official-original gate pending; this overlay preserves that.

## Research heuristic (not calibrated)

The module tw_model_v880/insider_accumulation.py needs three consecutive
calendar months ending in the month before the offset-aware decision timestamp.

For every month it requires:
- MOPS original **post-trade market purchase/sale** SHA-256.
- Reconciled stable holder/account identities and share rollforwards.
- Confirmation that all counted flows are market trades, not gifts, transfers,
  pledges or mere changes in share-balance disclosures.
- Separate public publication and first-archive receipt timestamps, both
  no later than the decision timestamp.
- Independently sourced dated shares outstanding, with SHA-256.

The three-month positive net purchases must exceed **0.05% of issued shares**,
with a positive buy-minus-sell net for each month. This 0.05% materiality rule
is an uncalibrated research heuristic and has NOT been shown to beat 0050.

Source attestations provided by a caller are **not** independent audits.
Every output is research-only: formal insider gate pending; no formal A+,
EPS/PE override, automatic Exit or PIT backtest eligibility.

## Actual September 2026 research queue — SECONDARY, NOT CERTIFIED

- 4772 台特化: September secondary net +492 lots. Examine holder identity,
  source receipts, capital denominator and ownership/minority interest.
- 2520 冠德: Previous secondary estimate +6,235 lots **conflicts** with
  the infographic's +4,340 lots. Reconcile holder accounts, cutoff dates,
  and transaction classification BEFORE citing either number as official.
- 9802 鈺齊-KY: Previous insider-shadow records +231 lots for MEINDL INT'L
  nominee account, with an unresolved 1-lot holdings mismatch. This is
  NOT documented as chairman's personal buying. Q3 EPS 0.68 and GM ~13.2%
  need separate earnings-bridge analysis.

No September source originals are added or certified by this change.

## Tests

Run: python -m unittest -v tests.test_insider_accumulation_research

Tests cover synthetic positive persistence, future receipt/publication,
missing data, secondary source exclusion, duplicate periods, transfers,
sale months, and no formal model promotion. They do not prove historic alpha.

## Follow-on original evidence work

Archive signed primary filings, stable holder/account keys, dated share
capital records and immutable first receipts. Only thereafter perform a
genuine point-in-time walk-forward test with multiple-testing adjustments.
