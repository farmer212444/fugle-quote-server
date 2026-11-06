# V8.10.5 | ETF 0050 split and dividend accounting control

**Research-control only; no historical excess-return claim.**

Primary TWSE 0050 ETF announcements:
- TWSE 2025-06-17 split reference:
  https://www.twse.com.tw/zh/ETFortune/announcement?company=A00005&date=20250617&fund=0050&seq=1&type=other
- Effective 2025-06-18: original beneficial units multiplied by **4**,
  so official 2025-06-10 pre-split close **188.65** corresponds to
  resumption reference **47.16** (rounding). Unadjusted price-only returns
  over this date are invalid: the unit count changes.
- TWSE official ETF dividend data:
  https://www.twse.com.tw/zh/ETFortune/dividendList
  and https://www.twse.com.tw/zh/ETFortune/etfInfo/0050

2025-01-17 ex-dividend 2.7 **on the old pre-split unit base**;
post-split price-history presentations may show the economically equivalent
0.675 per current unit for that past payout. **Do not include both**, and
do not pay 2.7 on four new units when computing cash entitlements.

2025-07-21 ex-dividend 0.36 on post-split units;
2026-01-22 ex-dividend 1.0; 2026-07-21 ex-dividend 0.6.
Record each event using original contemporaneous fund units and effective
dates before computing actual 0050 total-return comparisons.

Unit test:
`python -m unittest -v tests.test_v8105_0050_split_accounting`
This validates arithmetic in the existing
`tw_model_v880.execution.net_trade`. It is **not** a verified market-order
fill, historical corporate-action completeness, or a source-hashed original
historical publication proof. Independent source capture and split/dividend
revision accounting are still required for actual 12-month research returns.

A/B footwear strategy returns remain **null** until all issuer and
benchmark actions, observations and independent 365-day outcomes mature.
