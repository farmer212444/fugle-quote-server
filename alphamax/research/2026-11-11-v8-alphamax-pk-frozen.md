# AlphaMax vs V8.10.8 — first exhibition PK / frozen research lineups

**Research match only; NOT 2027 expected returns, a valid model-vs-model performance result, or investment advice.**

- Lineup freeze day: 2026-11-11 (Taiwan).
- Common *reference* quote date: **2026-11-10 close**; this is NOT a guaranteed executable next-day entry.
- Alpha lane is the first 10 names from the existing `2026-11-10-top20-evidence.md` **human independent research triage**. It is **not** an output of trained AlphaMax Ridge regression.
- V8 lane is the top 10 from the **Growth** family in `tw-market-data/rankings/latest_return_model_search.json`, registered research experiment `search-1bd7a00c1991103076642296`, parameter `fba4fc7e0f98702ddc21`; NOT the overall V8 formally selected or A+ model.
- Preserve independent selection. Do not retrofit this independent AlphaMax research queue using V8 features, nor declare an adjusted V8 screen as the original freeze.
- Machine-readable, price-matched frozen exhibit: `alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json`.

| # | Alpha human triage | TWD 11/10 reference | V8 growth screen | TWD 11/10 reference |
|---:|---|---:|---|---:|
| 1 | 8299 群聯 | 1,675 | 6505 台塑化 | 89.6 |
| 2 | 6691 洋基工程 | 568 | 6221 晉泰 | 41.35 |
| 3 | 6274 台燿 | 982 | 3219 倚強科 | 109 |
| 4 | 2330 台積電 | 2,285 | 4155 訊映 | 17.5 |
| 5 | 2383 台光電 | 4,365 | 3287 廣寰科 | 79.2 |
| 6 | 2395 研華 | 593 | 6538 倉和 | 309.5 |
| 7 | 2408 南亞科 | 383 | 2059 川湖 | 8,565 |
| 8 | 2344 華邦電 | 135 | 4979 華星光 | 383 |
| 9 | 2360 致茂 | 1,310 | 4721 美琪瑪 | 68.8 |
| 10 | 5274 信驊 | 11,935 | 4931 新盛力 | 185.5 |

Overlap = **0/10**. V8 growth's 川湖 (2059) is Alpha's prior research rank 17, not an Alpha top-10 overlap.

## Ex-ante evidence/risk checks (V8 growth only; no comparable Alpha scenario sheet)

- **4 of 10** names have **negative V8 hypothetical base price upside**, despite being ranked into the top growth screen: 6221, 3287, 6538, 4979. This is not inherently a formula error: Growth scores use acceleration and gross-margin features, *not* a guaranteed positive valuation constraint. It is an important trading-signaling limitation.
- **2 of 10** show negative reported OCF-to-sales: 3219, 4721.
- V8's 10 equally weighted **base price-upside scenario arithmetic mean** is **+11.63%**, and its 10 equally weighted **bear price-upside scenario arithmetic mean** is **-42.47%**. The minimum *single-company* bear scenario is **-99.17%** (6538). These are **unvalidated scenario price gaps**, not expected returns, not independent probabilities, not actual executable portfolio returns or complete correlated-shock risk forecasts.
- V8 growth **zero** calibrated expected return values and **zero** formal A+ names; Alpha research triage likewise **zero** calibrated return values.
- **Alpha's industry concentration** is material: several semiconductor, hardware and memory-cycle names are exposed to overlapping demand/valuation shocks. Its 2026-11-09 research memo included 9M EPS and mechanical P/E proxy for some names; that proxy is not a 2027 forecast, and inconsistent issuer PIT dates preclude retrospective as-of 11/09 claim.
- Both fail verified historic universe, total-return and trade-fill evidence. There is **no financial performance winner**.

## Fair next-stage test (precommitted)

1. Keep both ten-name lists **unchanged**. Equal hypothetical 10% per name is a *comparison convention*, not a capital allocation recommendation.
2. Require first independently verifiable executable entry **after** both vintage/freeze timestamps. Do not treat the 2026-11-10 reference closes as fills, especially because V8's screen was published 2026-11-11.
3. Over 21, 63, 126 and 252 subsequent trading sessions, compare matched **after-fee/tax/slippage, dividend-and-corporate-action-adjusted** investable total returns. Report gaps/failed fills and delistings honestly.
4. Include an investable comparable **0050 total-return benchmark** with identical execution/cost assumptions. Reference ETF 0050 unadjusted 2026-11-10 close: **99.7**, not a fill or net benchmark result.
5. Separately compare maximum drawdown, cash drag, turnover, sector correlation and tail risk. Matured 252-session observations will not exist instantly; do not invent immediate CAGR or a return winner.
6. For true model-vs-model PK beyond this exhibition, generate a **real PIT dataset shared by both**, let AlphaMax's executable independent model score the same investable universe, freeze outputs prior to entries, and run multiple historical **purged, embargoed OOS** folds. Do not backfill target-day picks into past history.

**Provisional verdict:** V8 has more usable research production and a rule-based top10 screen today; AlphaMax has a stricter fail-closed evidence contract but has not yet emitted a legitimate trained research Top10. This match tests **output style and evidence deficits**, not who can beat 0050. Neither is approved for an actual 20% concentrated position.