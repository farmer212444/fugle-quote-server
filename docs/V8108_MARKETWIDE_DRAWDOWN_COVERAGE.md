# V8.10.8 全市場 20／60 個基準交易日覆蓋率延伸

## 目標與操作

既有 `latest_recent_drawdown_shadow` 僅以估值 TOP20 觀察近期急跌。本變更新增獨立的 **上市櫃收盤快照全母體** 研究檢查，不再將研究榜單當全市場。輸出 `latest_marketwide_drawdown_coverage.json/.md`，並由日常研究 pipeline 產出，不改原始 `latest_research`、EPS、PE、A+、退出規則及持倉。

- 以估值報告相同 `asof_price_date` 的上市櫃原始收盤快照建立母體，並記錄逐日期 SHA-256。
- 以已保存的發行人官方歷史日價合併日價快照；同日期衝突不得擅自覆蓋，報告 `PENDING_CONFLICTING_HISTORY_VERSUS_DAILY`。
- 以已保存、附原始檔 SHA-256 與 capture timestamp 的 **TAIEX TR** 日序列建立參考交易日。只允許 capture timestamp 不晚於估值形成時間，未到當日收盤亦不容許計算。需有 **n+1** 筆**同日期**的價格及指數，才計算 n 日價格變化／相對基準／高點至當日回撤，n=5、10、20、60。
- 缺件、非連續參考交易日、未取得的個股歷史直接標示 pending；所有有價交易標的完整保留，以供日後補件。個股停牌未核實，不可將「缺價」當作「下跌0%」。
- 原風險門檻 -15%（5日）、-20%（10日）、相對大盤落後5pp且10日跌10%，在此使用 **參考交易日** 算法。20／60 日只採 **觀察**，目前不加新買賣閥值，避免事後最佳化。

## 已知重要限制

1. benchmark 為加權 **含息** 指數，股票個別為**未還原價格**；相對差值只供風險觀察，不能稱已校正的超額總報酬率。
2. TAIEX TR 日期是上市市場參考交易日，不是逐股票實際可交易日與上櫃特定停牌紀錄；**不可宣稱完整個股交易日曆已正式認證**。
3. `issuer_history` 目前不是全市場完整母體。資料封存時間不能回填成事件發生時已得知：**不准把此次補回的歷史檔視為 2026 年 10 月的 PIT 投資訊號**。
4. 本次未獲得除權息、減資、分割、配股、停牌、交易價差及實際成交的逐股完整核實；結果 `company_actions_and_total_returns_verified=false`。
5. 各警報門檻仍未完成足夠獨立 OOS 實驗；CI 通過只代表程式完整性，**不代表策略更能避跌、更適合重押**。

## 下一項獨立驗證

在同一統計期間的上市櫃個股歷史完整率、官方公司行動、風險報酬與校準樣本滿足前，保持 `calibrated_oos_strategy_improvement=false`。未來要用日期凍結的訊號，對照被警報與未被警報的樣本後續21／63交易日的總報酬、最大回撤、標準差與成交成本，並按產業、流動性、行情 regime 分層。必須包含未篩出股票和上櫃完整母體，避免幸存者偏差。

## 執行與單元驗證

```bash
python -m unittest discover -s tests -p 'test_marketwide_drawdown_coverage.py' -v
python scripts/marketwide_drawdown_coverage.py --data-root tw-market-data
```

驗收：現有 1,994 筆快照皆被納入，只在資料完整時產出5／10／20／60日計算，缺件顯示 pending，保持正式 A+ 新增 0、交易 0。
