# V8.A6 — ETF成分股異動 × 集保／投信 × 獲利交叉警示

此功能接入 V8.8.2 原有研究排程。產出 v8a6_etf_rotation_watch.json/.md，並把ETF研究結果連到 v8a5_quality_decision_lane.json/.md。前者揭露所有建檔歷史事件，後者只將具有真正近期三訊號共振的股票列為更優先的風險核查對象。

## 第一批TIP官方異動（9802）

| 官方公告時點 | ETF | 異動 | 生效日 | 原始技術通知 |
|---|---|---|---|---|
| 2024/10/21 17:00 | 00905 FT臺灣Smart | 刪除 | 2024/10/22 | https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/940/tw |
| 2025/04/18 17:30 | 00733 富邦臺灣中小 | 刪除 | 2025/04/21 | https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/1028/tw |
| 2025/04/18 17:30 | 00905 FT臺灣Smart | 納入 | 2025/04/21 | https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/1021/tw |
| 2025/07/16 17:00 | 00905 FT臺灣Smart | 刪除 | 2025/07/17 | https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/1088/tw |

上述官方公開技術通知已核對，但原始PDF並非2024-2025當時即由本模型存成不可變快照。**不能把2026年事後收集的資料，冒充歷史PIT回測時已知事件。**

## 模型何時發出三訊號研究警示？

三項必須同時有具體證據：

1. 過去120日內有正式公布的成分股剔除，原始TIP官方技術通知位元組、SHA-256、首次系統觀測時間都可驗。過期事件及未封存來源只能作歷史參考。
2. TDCC持股級距12–15在近期下降至少0.5百分點，或有20個有效交易日且配合合格已發行股數驗算的投信賣超達股數0.30%。此級距不等於經營者或機構法人身分。
3. 公司公開季度毛利率至少年減2個百分點且EPS年減20%以上，並通過公告時間與資料來源驗證。鈺齊2026Q3自結新聞稿不等同正式完整季報，標註待對帳。

三者相符只標記 THREE_WAY_ETF_CHIP_EARNINGS_REVIEW_ONLY，供原Quality Lane風險核查；不等於勝率已得到統計認證，不自動下單或Exit，不修改Base、EPS、合理PE、A+標準、13項證據簽核。

## 關鍵限制

- 指數公司成分股名單變動，不代表ETF基金真實成交，也不代表經理人獨立預測獲利。
- 同一00905在2025年4月曾納入9802，2025年7月又剔除；事件必須正反兩面都保存。
- 2025/07/17最近剔除距2026/10/21超過120天，目前不能當作新的賣出警示。
- 本批事件僅涵蓋9802、00733與00905。6206未建檔不等於沒ETF持有，也不代表所有2,000家企業已完成ETF事件整理。
- 13項正式品質門檻未增加、未放寬，沒有A+或A++自動升級；尚未完成全市場樣本外ETFs勝率回測。
- 既有GitHub研究排程會重新評估**已建檔**的ETF事件，但目前尚未建成自動發現、下載和校驗全部新增TIP技術通知的收集器。未來新資料必須先驗證官方原始通知、公布日期與雜湊，方可納入現時警示。

## 測試與檔案

- 模型來源：tw-market-data/evidence/v880/etf_index_constituent_events.json
- 執行程式：scripts/v8a6_etf_rotation_watch.py
- 回歸測試：tests/test_v8a6_etf_rotation_watch.py
- Top20接合：scripts/v8a5_quality_decision_lane.py
- 執行既有研究GitHub Workflow（tw_v877_research_rank.yml），未新增cron或交易行為。
