# V8.10.8：四層買進決策影子模型（V8.B8）

**目標：改善估值可信度、買進時機、部位風險的可稽核判斷，而不是增加第14項正式A+關卡。**

## 架構與資料契約

來源：`v8a5_quality_decision_lane.json`、`latest_expected_return_readiness.json`、`latest_research_work_queue.json`、`config/institutional_research.json`。四份輸入版本需對上收盤價日與估值版本。輸出：

- `tw-market-data/rankings/latest_buy_decision_shadow.json`
- `tw-market-data/rankings/latest_buy_decision_shadow.md`

新報告保存四份原始輸入SHA256、原始TOP20順位、2330／2317公司別關注清單和所有仍缺的證據，不生成個別買賣命令。既有 `13` 項正式證據認證、A+ 30%、A++ 35%、Base EPS/PE、Top10及既有Exit PIT流程全部保持不變。

### 第一層：企業品質（保留原證據門檻）

完整原件、現金流、股本稀釋、業外來源、同業循環、核閱範圍、公司治理與歷史PIT均維持既有PASS／FAIL／PENDING；PENDING≠FAIL、也不自動當PASS。有明確治理事件、已確認正式FAIL時先標示暫緩增加曝險，不能因高研究漲幅越過風控。

### 第二層：估值可信度及風險報酬

僅顯示已封存的2027 Base EPS、PE與模型價差、EPS及PE各下降20%的機械壓測；雙降壓測**不是**已校準悲觀報酬或損失機率。正式風險報酬比需要獨立、有歷史PIT可重現的下行情境及回報分布，不能直接使用 `Base漲幅 / |雙降漲幅|` 偽造風險比。驗證前 `expected_net_return`、`downside_loss_bound` 與 `calibrated_probabilities` 必須為 `null`。

需補證據：多次有公告時點的EPS預測版本、分季毛利與營運費用、同業PE及去景氣化合理區間、實際投資回報含費稅成本、獨立歷史Walk-Forward校準。

### 第三層：買進時機與內部人買賣

需分開確認歷史可得的量價相對強度、突破或跌深轉折、消息公告時點、價差滑價；內部人買進與賣出需身分、申報／交易日期、集中市場交易類型與正負淨買入官方原件。**未觀察到買進、尚未核對及正式零買進是三種不同狀態**。不足時標記PENDING，不以籌碼訊號推導主觀獲利機率。

### 第四層：實際持股與部位容量

現有 `max_stock_weight=.10`、`max_sector_weight=.25`、`max_common_risk_weight=.35`、`max_portfolio_bear_loss=.10`、`max_daily_participation=.05`、`max_exit_sessions=5` 均為研究政策假設，**非已驗證的個人持股、券商費率或保證最適比例**。取得當前真實部位、成本及連續成交價差資料前不推算買進張數、不發持有／減碼／賣出指令。

## 研究輸出定義

- `WAIT_FOR_VERIFIED_ENTRY_AND_RISK_RETURN`：缺足以形成買點、下跌分布或真實持股的證據。
- `REVIEW_OPERATING_VALUATION_OR_CAPITAL_RISKS`：EPS、PE、營運、稀釋股本或ETF風險有未解的來源旗標。
- `PAUSE_GOVERNANCE_REVIEW`／`PAUSE_FORMAL_QUALITY_FAIL_REVIEW`：治理事件或正式品質FAIL須先釐清。

以上是**查核優先狀態，不是交易訊號**。目前輸出 `buy_decision=NOT_AUTHORIZED_UNVERIFIED`，`buy_ready_count=0` 是證據不足的嚴格結論，不是判斷公司一定不能買，更不是市場上不存在買點。

## 待辦與驗收

1. 針對EPS/PE追蹤至少兩個已封存且可還原的預測版本；驗證公司獲利上修與價格變動的時序。
2. 建立含交易成本、悲觀情境與流動性上限的樣本外風險報酬評估，不用主觀情境機率。
3. 以官方原件核對內部人買／賣身分與實際集中市場交易；未核對保持UNKNOWN。
4. 接入經使用者核准且可核實的實際持股與費率，完成整體曝險及退出容量分析；無資料不自動猜。
5. 待歷史PIT、Walk-Forward與實際交易成本驗證完成，另案審查是否能升級為**人工覆核的條件式買進決策**；不改13關及A+門檻。

任何後續交易都仍需使用者明確授權；本次程式不具下單能力。