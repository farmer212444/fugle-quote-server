# KEM 超級預測 V1：事前登錄、到期驗證、機率校準

**研究功能，並非交易建議。** 2026-10-29 首次加入。
與既有 V8.10 會計估值、PIT、Walk-Forward、13項正式認證及 A+ / A++ 門檻分離，不改 EPS、PE、候選名單、成本規則或正式認證。

## 功能與限制

舊 tw_model_v880/experiments.py::calibration_summary 已有 Brier、五組可靠度分組與不足100題不得公布分數的限制；此模組補齊「事前登錄→不可覆寫→有據核對→同題基準比較」紀錄流程，而不是自動編造勝率。

- 二元事件必須定義可核對的條件與到期日，並記錄模型方法 SHA256。
- 發行時間由程式時鐘登錄。每個 ID 只能建一次；重跑或結果出現後不得修改原先機率。
- 依據檔及結果證據以倉庫內相對路徑及 SHA256 核對。若缺漏或變更，整份報告拒收。
- 到期且資料確實可用後才可寫入 true / false 結果，結果檔同樣不得覆寫。
- 滿100筆有效結果後可呈現 Brier、5組可靠度；只有所有題目都存在相同題目的事前基準時，才能計算配對基準Brier與skill。
- Brier skill = 1 - 模型Brier / 基準Brier。基準為0時skill保留空值。
- 不代表 GitHub 時間或來源公開時間已由獨立機構公證；也不能用檔案 SHA256 假裝已完成官方公告 PIT 核對或獨立審定。
- 原 institutional_review 的 probability_validation 不動，另增加 preissued_probability_validation；沒有資料時必須顯示樣本不足。
- 不自動產生個股概率，也不自動升級A+、A++或下單。

## 操作

事前依據檔及基準依據檔必須先在 tw-market-data 內真正保存並驗證 SHA256。機率應有可重現方法；不能把 Base/Bear/Bull 情境或主觀信心直接換成統計機率。

issue.json 示意（非9802實際預測）：

~~~json
{
  "forecast_id": "DEMO_2027_001",
  "market": "TWSE",
  "code": "9802",
  "event_definition": "2027 audited annual revenue YoY exceeds 10 percent",
  "event_due_date": "2027-12-31",
  "probability": 0.70,
  "model_method_sha256": "<actual 64-character lowercase SHA256>",
  "evidence": {"path": "evidence/v880/example/source.json", "sha256": "<actual SHA256>"},
  "baseline_probability": 0.50,
  "baseline_evidence": {"path": "evidence/v880/example/baseline.json", "sha256": "<actual SHA256>"}
}
~~~

沒有真正事前基準時，baseline_probability 與 baseline_evidence 皆設 null，不產出基準優勢。
event_due_date 是最早可結算日，實際原始年報尚未發布時不應據此提前宣告結果。

~~~bash
python scripts/superforecast_ledger.py issue issue.json
~~~

到期且有原始來源可核對之後：

~~~json
{
  "forecast_id": "DEMO_2027_001",
  "outcome": true,
  "verification_evidence": {
    "path": "evidence/v880/example/annual_report.pdf",
    "sha256": "<actual SHA256>"
  }
}
~~~

~~~bash
python scripts/superforecast_ledger.py resolve outcome.json
python scripts/superforecast_ledger.py report
python -m unittest -v tests.test_superforecast_ledger
~~~

資料位於 tw-market-data/experiments/superforecast_v1/issued/ 與 resolved/；獨立報告位於 rankings/latest_superforecast.json 及 .md；existing scripts/institutional_review.py 每次執行時也會呈現此模組的結果。

## 實證門檻和待辦

1. 需要真正事前發出的事件機率、來源、可稽核期限、模型版本。
2. 到期後官方原件及可辨識公開時點；原件若修訂，應保留版本，不得覆蓋舊證據。
3. 至少100個有效已結算事件才展示 Brier；相關發行人或重複月份不應直接視為獨立樣本，另需分群穩健性檢驗。
4. 可靠度、基準Brier、Brier skill僅評估二元事件預測；不能當作股票報酬率或優於0050的證明。
5. 費用、完整公司行動、可成交性、獨立日期及市況覆蓋仍須按原有樣本外回測規格驗證。缺件維持原品質門檻。

**沒有事前資料就保留空值；不得用今天已知的結果回填成歷史預測。**
