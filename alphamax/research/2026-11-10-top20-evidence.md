# AlphaMax independent research: 2026-11-10 Top 20 evidence triage
**Status: RESEARCH-ONLY / NO CERTIFIED RANKING / NO PORTFOLIO BUY SIGNAL**

## Scope and methodology
- Date written: 2026-11-10; consistent last complete local price snapshot: **2026-11-09 close**. 2026-11-10 intraday / unverified final prices are NOT blended.
- This is an **independent research verification-priority queue**, not a trained machine-learning output, not the return-optimal ordering, and not a continuation of V8 / A+ scores. Ordering reflects analyst investigation priority based on available earnings evidence, valuation uncertainty, business expansion and missing-data risk.
- October 2026 revenue YoY signals are public disclosures independently compared with [AHI revenue page](https://ahijournal.com/revenue/2026-10), [TSMC official October press release](https://pr.tsmc.com/chinese/news/3349), [6223 Oct announcement](https://tw.stock.yahoo.com/news/%E5%85%AC%E5%91%8A-%E6%97%BA%E7%9F%BD-2026%E5%B9%B410%E6%9C%88%E5%90%88%E4%BD%B5%E7%87%9F%E6%94%B622-32%E5%84%84%E5%85%83-%E5%B9%B4%E5%A2%9E92-091241273.html), and [6691 Oct announcement](https://tw.stock.yahoo.com/news/%E5%85%AC%E5%91%8A-%E6%B4%8B%E5%9F%BA%E5%B7%A5%E7%A8%8B-2026%E5%B9%B410%E6%9C%88%E5%90%88%E4%BD%B5%E7%87%9F%E6%94%B647-23%E5%84%84%E5%85%83-%E5%B9%B4%E5%A2%9E136-092334187.html). These are month-over-month independent source summaries, **not annual earnings forecasts**.
- Price source: `tw-market-data/prices/2026-11-09.json` (unadjusted quote snapshot; `fillability_verified=false`). Data are not dividend-adjusted historical total returns.
- EPS source: `tw-market-data/financial/2026Q3/TWSE_income.json`, `TPEX_income.json`, plus separately published company disclosures for 2330, 2360, 5274, 6691. `latest_manifest.json` explicitly says issuer-specific publication PIT is **NOT certified**. 2026 9M EPS is Jan-Sep cumulative; “—” means not source-verified in this pass, **not EPS=0**.
- **P/E proxy = 2026-11-09 close / (2026 9M EPS × 4/3)**, only where 9M EPS has been independently retrieved. This is NOT TTM P/E, forward P/E, 2027 EPS projection, fair value, or ranking score. It is especially misleading when cyclic earnings are near peak.

## Research-verification priority queue
| Research queue | Ticker | 2026-11-09 close TWD | Oct revenue YoY | 2026 9M basic EPS TWD | Mechanical P/E proxy |
|---:|---|---:|---:|---:|---:|
| 1 | 8299 群聯 | 1,650 | +346.3% | 325.49 | 3.8 |
| 2 | 6691 洋基工程 | 554 | +136.3% | 30.62 | 13.6 |
| 3 | 6274 台燿 | 962 | +127.0% | 25.41 | 28.4 |
| 4 | 2330 台積電 | 2,235 | +59.7% | 78.75 | 21.3 |
| 5 | 2383 台光電 | 4,070 | +203.1% | 82.92 | 36.8 |
| 6 | 2395 研華 | 583 | +88.4% | 16.21 | 27.0 |
| 7 | 2408 南亞科 | 370 | +487.7% | 49.28 | 5.6 |
| 8 | 2344 華邦電 | 132.5 | +257.0% | 15.32 | 6.5 |
| 9 | 2360 致茂 | 1,250 | +163.3% | 34.61 | 27.1 |
| 10 | 5274 信驊 | 11,700 | +177.8% | 126.41 | 69.4 |
| 11 | 3443 創意 | 6,705 | +127.0% | 40.84 | 123.1 |
| 12 | 6446 藥華藥 | 1,370 | +102.0% | 18.43 | 55.8 |
| 13 | 2345 智邦 | 1,405 | +91.2% | — | — |
| 14 | 2376 技嘉 | 309.5 | +136.7% | — | — |
| 15 | 6223 旺矽 | 3,705 | +92.7% | — | — |
| 16 | 3665 貿聯-KY | 1,420 | +80.0% | — | — |
| 17 | 2059 川湖 | 8,010 | +191.1% | — | — |
| 18 | 3017 奇鋐 | 2,540 | +34.4% | — | — |
| 19 | 3231 緯創 | 168.5 | +118.0% | — | — |
| 20 | 2317 鴻海 | 239 | +45.7% | — | — |

## Illustrative valuation sensitivity (NOT a forecast)
The following are hypothetical exit P/E assumptions chosen for sensitivity, **not estimated fair multiples**. Required full-year 2027 EPS for a **+20% capital price change** without dividends and costs: `EPS_required = 1.20 × 2026-11-09_price / hypothetical_exit_PE`. Compare only mechanically against annualized 9M FY2026 EPS, not as a predictive assumption:
| Ticker | Hypothetical exit multiple | Required 2027 EPS for +20% | 2026 9M EPS ×4/3 (NOT forecast) |
|---|---:|---:|---:|
| 8299 | 6x | 330.0 | 434.0 |
| 6691 | 15x | 44.3 | 40.8 |
| 6274 | 25x | 46.2 | 33.9 |
| 2330 | 22x | 121.9 | 105.0 |
| 2383 | 30x | 162.8 | 110.6 |

## Risk review and active blockers
- **8299, 2408, 2344**: extraordinarily strong 2026 cyclical memory earnings can normalize sharply; use through-cycle gross margin, ASP and inventory; 8299 requires diluted-share/convertible adjustments. See [8299 official disclosure](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=0d2e3979-e6d5-49bd-a4af-c918837b5b9f), [2408 company 2026 Q3](https://www.nanya.com/tw/IR/16/%E6%96%B0%E8%81%9E%E7%A8%BF?IRId=14188).
- **6691**: verified nine-month EPS and strong disclosed project revenues, but contract assets, project timing, collections, gross margin stability and order conversion must be audited. [Official disclosure summary](https://www.moneydj.com/KMDJ/news/newsviewer.aspx?a=d5917f0e-cb6c-487d-a94f-6aed5ec2a6b3).
- **6274, 2383**: earnings growth corroborated; 2027 EPS must be independently estimated and stressed against valuation multiple contraction. [Q3 earnings](https://money.udn.com/money/story/5612/9843366).
- **2330**: 2026 Q3 EPS 29.43 and Jan-Sep EPS 78.75, with strong October revenue. [Company Q3](https://pr.tsmc.com/chinese/news/3346), [Jan-Sep cumulative independent coverage](https://ec.ltn.com.tw/article/breakingnews/5607120).
- **2395**: Jan-Sep EPS 16.21; validate backlog conversion and earnings quality. [Company press release](https://adv-www-jp.azurewebsites.net/zh-tw/resources/news/%E7%A0%94%E8%8F%AF%E5%85%AC%E5%91%8A2026%E5%B9%B4%E7%AC%AC%E4%B8%89%E5%AD%A3%E6%AF%8F%E8%82%A1%E7%9B%88%E9%A4%98715%E5%85%83-%E7%87%9F%E9%81%8B%E5%86%8D%E7%B7%A0%E6%96%B0%E7%8C%B7).
- **3443, 5274**: high mechanical P/E sensitivity and earnings-growth execution risk; do not extrapolate monthly growth into sustainable EPS.
- **2317/3231**: latest publicly documented 2026 Q3 earnings were pending in the sources checked, so Q2 EPS is **not** mislabeled as Q3 or YTD; [2317 11/12 IR schedule](https://www.honhai.com/zh-tw/investor-relations/investor-relations-activities/event-calendar).
- **Historical universe, delisted coverage, corporate actions, executable fills, PIT filing timestamps, 2027 forecast probability calibration and real portfolio CAGR remain BLOCKED**. Do not promote this list to buy signal.

## Next executable steps
1. Verify issuer-specific earnings filing date/time, diluted shares, 2026 cash flows, 2025/2026 quarter comparisons, 2027 capex and order quality for 8299/6691/6274/2330/2383.
2. Build entire-market adjusted PIT 5+ year training panel; exclude returns not matured by ranking date; preserve delistings and non-executable sessions.
3. Train and calibrate out-of-sample return distribution; then publish ranked after-cost **expected returns and tail risk**. Any missing evidence must remain explicit, not plugged with arbitrary EPS or odds.

**No 2027 expected returns, upside percentages, target prices, certified AlphaMax rank, or recommended position sizes have been generated here.**
