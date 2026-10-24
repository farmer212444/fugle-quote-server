# V8.x 庫藏股事件實證（隔離研究模組）

**狀態：程式架構與防前視檢查已加入研究分支；尚無2020–2025逐筆事件、全市場存續／下市歷史和完整含息價格資料，不得報正式勝率。**

## 事件與交易規則（先定義，不能看到結果後改）

- 股票母體：事件當時所有上市及上櫃普通股（含當時存在、如今已下市的公司），不從2026年存續清單反推。
- 事件一：董事會庫藏股**公告**的實際公開揭露時間（announce）。
- 事件二：實際買回**完成公告**的公開揭露時間（completion），絕不可用原定執行結束日假定市場已知道結果。
- 同一家公司在不同時間有多個公告，逐案保留；重疊樣本不是獨立試驗，解讀時按公司／事件日群聚。
- 進場：**公告日之後第一個交易日收盤**（保守，不捕捉公告當天報酬；此規格與另一套next-open前瞻策略不同，不可混用）。
- 出場：進場後3／6／12個曆月屆滿的第一個有效交易日收盤，不允許除息價、停牌、下市缺值被偷偷跳過；延遲逾7日須人工驗證退市處理。
- 0050：同一進出場日期的**含息總報酬指數／還原淨值**；單純0050股價不得冒充含息績效。
- 個股：完整公司行動已核對的**含息總報酬調整價格**。純歷史未還原收盤價不合格。
- 個股交易研究成本：買賣費率各0.0285%、賣出證交稅0.3%、買賣滑價各0.1%；0050採未扣交易成本的總報酬，對研究策略較嚴格。成交量與極端滑價仍需另行實證。
- 將2020～2023標成探索群、2024～2025標成回顧式留出群。**今天才設定的規則不能把過去2024～2025結果包裝成當年事前封存的正式樣本外**。
- 每一個3／6／12個月視窗：列出事件數、實際可核對樣本數、未到期、缺資料或未調整筆數、淨報酬>0勝率、跑贏0050比例、平均/中位數淨報酬與0050超額報酬。
- 買回占股本比例可在公告日使用，**實際執行率只可在完成公告日後使用**。研究階段不要依執行率事後篩選公告日名單（前視偏誤）。
- 多重檢驗、群聚不獨立、流動性與產業市值對照組尚待驗證；不得由高報酬直接宣稱庫藏股造成股價上漲。

## CSV證據格式

**以下資料尚未填入；不能將範例或單元測試模擬資料冒充台股歷史結果。**

1. tw-market-data/buybacks/events_2020_2025.csv

   event_id,stock_id,event_type,disclosed_at,source_url,source_sha256,execution_rate

   - disclosed_at 必須是公開揭露當時有時區的時間戳（ISO8601）；來源原文或MOPS原始回應需可追溯。
   - source_sha256 為原始來源bytes之SHA256；本程式**只檢查格式**，未自行下載原件校驗，原件需另列稽核清單。
   - event_type=announce 時 execution_rate **必須空白**；completion 時必須填0～1的小數。
   - 主來源為公開資訊觀測站 t35sc09 庫藏股統計彙總表，需另以每日重大訊息核對公告時間。不能把董事會決議日當成資訊已公布日。

2. tw-market-data/buybacks/issuer_tr_daily.csv

   date,stock_id,total_return_close,corporate_actions_verified,source_id

   - 完整含息還原歷史；若無公司行動驗證，corporate_actions_verified=false，演算法必須阻擋該筆計算。
   - 下市、減資、分割、現增、配息歷程須追溯；單點close不合格。

3. tw-market-data/buybacks/0050_tr_daily.csv

   date,total_return_index,total_return_verified,source_id

   - 含息總報酬序列並和個股**同一交易日**比較，驗證前total_return_verified=false。

## 執行

    python -m pytest -q tests/test_buyback_event_backtest.py
    python scripts/buyback_event_backtest.py

缺來源時腳本**故意以exit code 2**結束，建立狀態檔
tw-market-data/experiments/buyback_event_oos_v1/latest.json，
記錄 BLOCKED_MISSING_SOURCE_FILES、所有缺件、零實際成果與null勝率，
絕不默默報告成功。三份來源完整後則輸出各視窗
grouping、逐筆observations、blocked、immature及來源CSV SHA256。
即使所有數值到齊也只標示 RESEARCH_OBSERVATIONS_UNCERTIFIED，
須再人工／獨立機器審核歷史母體完整度、原件雜湊及公司行動。

## 不變更正式模型

這是*觀察用事件回測模組*，未修改 tw_model_v880 核心、13項A+驗收、主榜單、任何自動委託。
買回庫藏股不得直接加分升級A+；須先有驗證過的樣本外超額報酬及風險歸因，再另提模型加權PR。

主要來源：

- [MOPS庫藏股統計彙總表](https://mops.twse.com.tw/mops/#/web/t35sc09)
- [FinLab：庫藏股策略歷史回測](https://finlab.finance/blog/treasury-stock-investment-strategy)
- [台股事件研究：公告](https://8888fortune.com/events/buyback-announce)
- [台股事件研究：完成](https://8888fortune.com/events/buyback-completion)

其他網站的策略年化報酬或CAR/BHAR不是本程式計算結果，不可混成模型勝率。


## 2026-10-24 official-source checkpoint (actual CI observations)

The [TWSE Taiwan50 total-return index archive](https://github.com/farmer212444/fugle-quote-server/actions/runs/40040560674) successfully fetched **72/72 months** for 2020-2025, with **1,459 official trading-day observations** (2020:245; 2021:244; 2022:246; 2023:239; 2024:242; 2025:243). Annual CI artifacts hold monthly response bytes, SHA256 receipts, manifest and CSV. This is the **Taiwan50 index**, **not** the 0050 investable ETF dividend-adjusted total return. CI artifacts have limited retention and must be made durable before certification.

The [MOPS historical POST check](https://github.com/farmer212444/fugle-quote-server/actions/runs/40040712021) returned HTTP 200 **security-blocked pages**, not buyback events, in both listed and OTC markets: "因為安全性考量，您所執行的頁面無法呈現". Hence ACCESS_RESTRICTED ≠ zero events. Do not attempt to bypass website access limits.

[TEJ/TQuant TWN/APITRS](https://tquant.tejwin.com/%E8%B3%87%E6%96%99%E9%9B%86/) is an identified **licensed** alternative for historical listed/OTC/delisted buyback events, still requiring rights and verification of the actual public-disclosure timestamp.

The checkpoint file is:
tw-market-data/experiments/buyback_event_oos_v1/source_readiness_2026-10-24.json

**Unresolved:** historical event rows + announcements timestamps, fully adjusted issuer TR with delisting actions, original ETF 0050 total-return history, independent data-completeness audit. No 3/6/12-month hit rate or alpha has been demonstrated. Third-party CAR/BHAR studies cannot substitute for the missing per-event evidence.


## 2026-10-24 licensed third-party vendor adapter (research-only)

An additional source is the [Apify Taiwan treasury-stock buyback API](https://apify.com/chamarix/taiwan-treasury-stock-buybacks).
The vendor advertises 5,857 board resolutions, but that number is
**not independent validation**, and authorized access may be paid.
[FinHa](https://finha.rockmanagent.com/datasets) also lists a historic
buyback dataset, but no permitted unauthenticated data export was confirmed.

An operator with legitimate access can normalize an authorized JSON export:

    python scripts/buyback_vendor_adapter.py --vendor-json LICENSED_FILE.json --out /tmp/buyback-vendor-quarantine

Output contains vendor_buyback_candidates_QUARANTINED.csv and a
manifest, **never the events_2020_2025.csv trading-backtest input**.
Guards: TWSE/TPEX, 2020-2025 board-resolution scope, positive planned
shares, valid plan windows, duplicate checks, completed-program arithmetic,
and no post-outcome values on an open-programme record.

**PIT protection:** A board resolution DATE is not an independently verified
public ANNOUNCEMENT TIMESTAMP; a vendor bulk export's completion boolean,
amount and execution rate may represent information that was only reported
later, not on the resolution day. The importer sets both announcement and
completion eligibility FALSE and all publication timestamps blank.
Original event announcement/completion publication evidence, exact historic
exchange universe, issuer total returns with actions and delisting, and
ETF 0050 adjusted total-return benchmarks remain necessary.

All importer unit tests are synthetic and do not certify returns,
the claimed vendor count or executable trading decisions. The PR
does not change A+, current rankings or brokerage orders.
