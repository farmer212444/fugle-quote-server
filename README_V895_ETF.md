# V8.9.5 ETF Accumulation（研究，非交易訊號）

這是與 V8.8.2 主估值、V8.9 Cycle Alpha 獨立的 **ETF 曝險需求觀察**；絕不改寫 EPS、PE、Base/Bear/Bull、A+/A++ 證據分級或實際法人買賣超。

## 真正資料與侷限

- 證交所解釋的「PCF」為基金申購買回清單；**單一申購籃子不是已成交股票指令，也未必是基金的真實持股比率**。
- 基金份額增加（申購大於贖回）代表基金級資產變化；仍可能透過實物申贖、庫存、其他交易方式完成，不保證等額交易所買盤。
- 成分股**持股權重變動**還包含股價變動和再平衡，不能直接用權重差推論買賣股數。程式只以 **前日 NAV × 當日ETF單位數變化 × 前日已揭露股票籃子權重** 作保守曝險代理。
- 需逐ETF建置相鄰有效交易日資料，5日需6個有效交易日、20日需21個；缺其中一日就不給該ETF該期數值。不同ETF覆蓋率不一致時，**不得稱為ETF全市場排名**。
- **基金單位數截至日（units_asof_date）**、PCF申購籃子生效日（basket_effective_date）與正式發布時間（published_at）是三項獨立欄位；不能拿前一日晚間的下一日PCF推算前一日單位數，更不得把盤後PCF當當日盤中資訊。
- PCF 含有強制現金替代時，相關股票不得假設隨申購直接交割；程式剔除現金替代。
- 同樣追蹤臺灣50的0050、006208等，並不是兩名獨立的主動經理人選股。輸入 \`index_family\` 記錄相同追蹤族群，不將重複持有解讀為相互獨立的選股判斷。
- 反向／槓桿／境外／債券 ETF、不確定產品類型與無法核對的來源，全部拒絕進入同一股票曝險研究母體。
- 目前資料夾**尚未有逐日核對的完整ETF-PCF歷史**；沒有提供時報告會顯示 \`BLOCKED_MISSING_VERIFIED_ETF_PCF\`，不會憑空產生Top20、假定0050等正買進誰。
- \`issuer_source_verified\` 只是上游擷取器輸入的查核旗標，**不是證交所認證，也不能取代來源原件與公告時間逐件查核**。後續必須使用正式發行人原件及HTTP原始位元組hash配對；不得拿新聞轉載當官方來源。

### 官方資料入口

- 臺灣證交所ETF介紹及PCF說明：https://www.twse.com.tw/downloads/zh/ETF/topic10.pdf
- 證交所ETF專區：https://www.twse.com.tw/zh/products/securities/etf/news.html
- 元大投信PCF示例：https://www.yuantaetf.com/tradeInfo/pcf/006203
- 台新投信PCF示例：https://www.tsit.com.tw/ETF/Home/Pcf/00947
- 其他基金必須分別確認投信官網當日日期、公告時間、PCF/實際持股口徑及前日ETF份額，**不可套用一個不具版本控制的網頁擷取器到全部ETF**。

## 輸入格式

在 \`tw-market-data/etf/pcf/YYYY-MM-DD/0050.json\` 存放原件核對後的正規化紀錄，例如下方**只是結構說明，不是真實0050數值**：

\`\`\`json
{
  "etf_code": "0050",
  "issuer": "ISSUER_NAME_FROM_SOURCE",
  "fund_type": "TAIWAN_EQUITY_UNLEVERAGED",
  "weight_basis": "ISSUER_PCF_BASKET",
  "index_family": "TAIWAN50",
  "source_url": "https://issuer.example.invalid/issuer-pcf-original",
  "raw_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "issuer_source_verified": false,
  "units_asof_date": "2026-10-20",
  "basket_effective_date": "2026-10-21",
  "published_at": "2026-10-20T16:10:50+08:00",
  "units_outstanding": 10000000,
  "nav_per_unit_twd": 50,
  "constituents": [
    {"code": "2330", "weight": 0.40, "cash_substitution": false},
    {"code": "2308", "weight": 0.05, "cash_substitution": true}
  ]
}
\`\`\`

**不可以直接使用此示例計算研究結果**，因為 \`issuer_source_verified=false\`，且網址是假示例。實際輸入的 \`weight\` 以0～1表示，必須對應 \`weight_basis\` 與原始 PCF。分數和份額一律數字，不把缺值補成零。

## 執行與輸出

\`\`\`bash
python -m unittest -v tests.test_v895_etf_accumulation
python scripts/v895_etf_accumulation.py --data-dir tw-market-data
\`\`\`

GitHub Actions \`v895-etf-accumulation.yml\` 會執行同樣的查核並保存：

- \`tw-market-data/rankings/v895_etf_accumulation.json\`
- \`tw-market-data/rankings/v895_etf_accumulation.md\`

輸出每檔ETF的1/5/20日有效覆蓋率及未納入原因，對股票只給保守推估曝險與當日成交額的比率。來源缺漏時顯示待補，**不自動認證A+、不修改正式排名、不下單**。

## 下一階段正式驗收條件

1. 至少取得0050／006208／0056／00878／00919的兩個相鄰有效交易日官方PCF及基金份額，用發行人原件及hash核對；公開可得性不同時逐檔標示。
2. 延伸到6／21個交易日後再計算5／20日；價格、股份及基金PCF以實際發布時間作PIT防線。
3. 對照ETF成分股變動公告與價格反應，檢查是否已有前置反映，並校正同指數產品重複性。
4. 做至少數年真實PIT樣本外測試、扣除交易成本，確認相對原估值模型是否有增益，**不能以合成單元測試當成超額報酬實證**。
