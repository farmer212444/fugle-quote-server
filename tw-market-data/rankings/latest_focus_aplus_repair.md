# V8.10.8｜6206正式A+審查準備＋9802毛利率門檻（不核發PASS）

股價基準：2026-11-10；形成：2026-11-10T16:43:43.506857+08:00
**正式新增A+：0；正式新增PASS：0。** 資料勾稽與正式核閱不可混為一談。

## 6206 飛捷：先完成12項公司品質＋獨立第13項

2027 Base研究潛在漲幅：+57.62%；三份公司法說PDF已重新核對原檔SHA256：3份。
八季完整財報原件已重驗：8/8份；仍缺：無。
注意：法說PDF不是八季完整四表；即使取得完整財報，全文核閱、發行時間與具名簽認仍須另外完成。

|優先|原始品質關卡|來源觀察|下一步|
|---:|---|---|---|
|1|original_eight_quarter_statements|OBSERVED_PARTIAL|逐季核對官方原始四表、修訂紀錄及完整附註|
|2|cash_and_working_capital|OBSERVED_PARTIAL|以正式現金流量表對帳OCF、存貨、應收應付與實際PPE現金支出|
|3|fully_diluted_shares|OBSERVED_PARTIAL|核對登記股數、員工認股、可轉債及潛在稀釋|
|4|forecast_bridge|OBSERVED_PARTIAL|用訂單、ASP、良率及軟硬體組合確認2027營益橋接|
|5|auditor_scope|MISSING_OR_UNVERIFIED|核對會計師意見、核閱範圍及重要性|
|6|nonoperating_components|MISSING_OR_UNVERIFIED|由原始附註區分經常性及一次性業外|
|7|tradability|OBSERVED_PARTIAL|補驗價差、漲跌停及持倉退出成交可行性|
|8|point_in_time|MISSING_OR_UNVERIFIED|取得原始公告精確時點及當時可知資料版本|
|9|insider_claims|MISSING_OR_UNVERIFIED|比對內部人申報、交易日、股數及持股變化|
|10|matched_peers_and_cycle|MISSING_OR_UNVERIFIED|按產品結構比對同業Forward PE與景氣全週期|
|11|management_promises|OBSERVED_PARTIAL|逐頁抽取法說承諾並與後續實績核對|
|12|dividend_window|OBSERVED_PARTIAL|核對除息、實際發放日期與每股股利|
|13|out_of_sample_validation|MISSING_OR_UNVERIFIED|用當時股票母體與歷史模型凍結版本做樣本外回測|

這是審查準備清單；無人員署名、簽核時間或完整證據時，不建立review_packs，不能產生PASS。

## 9802 鈺齊-KY：反推2027毛利率，不調高正式預測

|敏感度|數值|
|---|---:|
|目前股價|62.50元|
|原模型2027毛利率|15.13%|
|原模型2027 EPS|4.39元|
|原模型2027 Base價|52.69元|
|A+價格30%所需2027 EPS|6.78元|
|A+價格30%所需2027毛利率|18.30%|
|較原模型必須增加毛利率|+3.17個百分點|

此毛利率僅固定2027營收、費用、業外、稅率、歸母、稀釋股數及PE的機械反推，不是2027財測。

### 公司披露的2025Q2→2026Q2成本橋接（四捨五入）

|成本項目|對毛利變化影響|
|---|---:|
|直接材料|-2.30pp|
|直接人工|-2.95pp|
|製造費用|+0.67pp|

**成本資料並無可在GitHub重驗的原始PDF**；本次只重新驗算已登錄的公司披露整數表，不能用來認證廠別稼動率或直接上修2027 Base。
新增A+所需：公司別正式財報、成本、產能及2027橋接證據；PIT+扣成本樣本外研究完成後另審第13關。

**本次修正不放寬13項門檻、不改EPS／估值、不下單。**
