# V8.10.8 報酬選股輸入修復

當上櫃個股已保存 `V893_OFFICIAL_TPEX_DAILY.by_day` 歷史，研究流動性函式仍只讀 `by_month`，因此報酬選參把上櫃個股當成缺少20日成交額。2026-10-24既有報告有796家研究公司、僅60家有效成交額；6494已有85日歷史，仍被此格式缺口漏讀。

修復讓研究流動性與報酬特徵消費既有上櫃逐日資料。每筆重新驗原始壓縮檔、收據、雜湊、公司、日期與原始解析結果；不同公司共用同一報告內的全市場原件解析，下一份報告重新檢查。未來交易日或尚未取得的資料不進較早估計，金額衝突與損壞來源明確拒收。這只恢復研究成交額，不代表價差、清倉能力或13項認證已通過。

報酬選參現在也輸出每個模型組的實際研究股票、Base／Bear價差、EPS及PE各減20%的敏感度、成交額與JSON中的原有風險旗標。展示組合使用既有預先登錄參數的最小持股數、成交額門檻、產業上限及持有期，沒有利用後來報酬挑權重或贏家。缺動能時不改綜合組權重，也不把資料不足的部分組合當成完整候選。

`rankings/latest_return_model_search.json` 新增 `input_coverage_by_market` 和 `current_research_screens`，同名Markdown列出各組股票。當期研究名單與已封存實驗名單分開，舊試驗及其公司蒐集義務保留。

目標年度情境價差不等於21／63／126日報酬；尚無合格樣本外績效時，預期淨報酬與勝率維持空值。正式A+／A++、EPS、PE及主估值排序不因本修復放寬。

驗證：

```bash
python -m unittest -v tests.test_tpex_research_liquidity tests.test_current_research_screens tests.test_research_pipeline tests.test_return_model_search tests.test_history_archive tests.test_v893_tpex_daily_backfill
```

新測試使用明示的合成原件，覆蓋上櫃20日中位數、原件共用、未來資料、公司／日期／金額衝突、原件損壞、報酬特徵接入與治理排除；它們是工程回歸檢查，不是投資績效。
