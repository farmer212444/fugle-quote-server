# V8.11 Buffett Owner Economics (candidate research overlay)

**Not an activated version:** current valuation runtime is V8.10.8. This sidecar does NOT change EPS, PE, Base/Bull/Bear, the original 13 quality gates, formal A+/A++, rank position, allocation, broker orders, historical signals or model-selection parameters.

## Modules

1. Owner Earnings (1986): parent-attributable profit + depreciation and amortization - documented maintenance capex - documented extra sustaining working capital. Never double-count working capital by using operating cash flow as net profit; maintenance versus growth capex must be independently established.
2. Incremental ROIC: comparable annual normalized change in NOPAT divided by added invested capital. This requires independent source reconciliation, including acquisitions and leases.
3. Moat durability: review multi-year pricing, market share, customer concentration, competitive response, and returns on capital; single-quarter gross margins do not certify moat.
4. Three-to-five-year discounted owner earnings: explicit annual forecasts, diluted shares, required return and terminal growth with proof. Historical half-years cannot become an automatic future EPS or fair value.
5. Capital allocation: historic reinvestment, cash distributions and dilution must be reconciled against incremental returns.

## Original cash-flow case: 9802

2026 H1 values are TWD thousands: operating cashflow -274,010; PPE cash expense 608,517; net after all PPE spending -882,527 (**-8.82527 億元**); dividends cash paid 401,983.

2025 H1 comparison: OCF -287,575; PPE cash expense 1,154,071; net after all PPE spending -1,441,646 (**-14.41646 億元**).

These are historical free-cash-flow diagnostics including growth capex, **not Buffett Owner Earnings**. Maintenence capex and sustaining working capital are unverified. The next year and economic moat are also unverified.

Source: latest_9802_cash_review.json. The script re-hashes the two archived PDF originals and validates issuer, cashflow period, archive capture timestamps, prior review time and current model/price vintage before publishing.

## Run

    python scripts/buffett_owner_review.py
    python -m unittest -v tests.test_buffett_owner_economics

Outputs: tw-market-data/rankings/latest_buffett_review.json and latest_buffett_review.md.

This is separate from the official ranking and observes only the institutional-focus issuers, **not the full market**. It does not create A+ certificates. Invalid provenance fails closed.

## Remaining evidence

No validated maintenance/growth capex split, normalized working capital, multi-year audited NOPAT and invested capital, durable moat checks, independent discount inputs or complete 0050 cost-inclusive sample-out returns. Any future owner earnings value or long-term fair price must retain pending status until its actual sources can be reviewed.
