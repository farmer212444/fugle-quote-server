# V8.10.8 近期大跌漏判修補：Research Shadow

## 本次變更

- 新增 `scripts/recent_drawdown_guard.py`，以研究報告相同的估值形成時間及價格日，逐股讀取已封存的官方收盤快照。
- 先計算最近 **5／10 筆已保存價格觀測** 的未還原變化；最近觀測窗最高價至現價的跌幅作補充。
- 另外報告 **已觀測最大收盤回撤**：按時間順序由先前高價至其後低價的最大跌幅。若谷底後反彈，高點至現價跌幅可能低估歷經風險；兩個指標分開呈現。不宣稱是連續的 5／10 個交易日，20／60 個完整交易日窗口目前仍未核定。
- 若 5 筆跌幅 <= -15%、10 筆跌幅 <= -20%，或至少 6 筆觀測且觀測高點至現價 <= -20%，狀態為 `PAUSE_RECENT_SELL_OFF_REVIEW`。如果 10 筆跌幅 <= -10% 且相對基準 <= -5 個百分點，狀態為 `WATCH_MARKET_RELATIVE_WEAKNESS`。這些是**暫定未校準研究門檻**，不是由歷史回測優化。
- 相對基準採同期有正式原始來源收據的 **TAIEX TR 含息指數**；個股使用未還原價，**兩者不能當作真正超額總報酬**。
- 來源採取日期與 SHA-256 收據，模型估值形成時間之前尚未取得的基準資料不能回填。缺少有效價格、基準或完整觀測期一律保留待查，**不當作風險零**。
- 由 `scripts/run_research_pipeline.py` 先產出 `latest_recent_drawdown_shadow.json/.md`，`v8b8_buy_decision_shadow.py` 再以相同股價日期、相同模型 vintage、完全相同公司集合嚴格核對。警戒只改 **research action_review_state**，原估值、EPS、PE、股價排名、13 項正式門檻與任何持倉不動。

## 適用限制

1. 本次是近期急跌風險研究，不是個股跌勢預測器；任何 2026 年下跌後才建立的規則，不能拿回 2026 年 10 月冒充當時存在的訊號。
2. 「已觀測最大回撤」只涵蓋現存快照，不代表完整連續交易日、盤中高低價或以當年推薦日作起點的真實最大回撤。沒有帶時間戳且可覆核的推薦紀錄時，不能宣稱是推薦績效。
3. 歷史 PIT、價格除權息還原、股利、停牌完整交易日曆、滑價與真實成交尚未核實；沒有 20／60 日完整樣本，也沒有充分獨立市場情境，**不得**聲稱已改善未來績效。
3. 本修補不採用當日已知以外的價格或原始指數來源；若來源缺漏、檔案資料日期不符或不同報告版本互相衝突，按 fail-closed 方式拒絕拼接。
4. 已有的營運現金流、業外比重及 EPS/PE 各降 20% 壓測繼續獨立顯示；尚未完成的公司行動與產業共同曝險不能默認通過。
5. 研究指標只是「待人工查核」的影子警報，不會發出買進、持有、減碼、賣出訊號，不調整帳戶部位，不核發新的正式 A+。

## 測試

```bash
python -m unittest discover -s tests -p 'test_recent_drawdown_guard.py' -v
python -m unittest discover -s tests -p 'test_v8b8_buy_decision_shadow.py' -v
python -m py_compile scripts/recent_drawdown_guard.py scripts/v8b8_buy_decision_shadow.py
python scripts/recent_drawdown_guard.py --data-root tw-market-data
```

驗收應先證明：未來價不參與歷史估值、基準原件時點晚於 vintage 會被拒絕、缺行情保持 pending、版本不一致拒收、無論跌多少都不會生成下單或 A+。單元測試通過 **不等於** 投資策略 OOS 或改善績效得到驗證。
