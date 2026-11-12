# 逆向低估與提前反轉研究｜B lane v1

## 研究問題

好財報、毛利率全面好轉時股價可能已提前上漲；不宜用「當前毛利率高、股價近期上漲」作為所有股票的唯一買進前提。相反地，**有疑慮也不等於便宜**。此獨立研究層應比較：

1. 市場實際擔憂的內容與來源日期（未查證的擔憂維持待核）。
2. 目前價格對公司 **悲觀／基準／樂觀** 可辯護結果的折價或溢價。
3. 是否有先行、當時可知的改善證據（營收、產能、成本、毛利、現金轉換、同業）。
4. 反轉不發生時的持續損失、競爭力永久受損及股權稀釋。

**買後股價下跌不代表選股邏輯錯誤**；應以當初資訊集、假設與事後基本面誤差獨立檢驗，不能事後擇優。

## 第一階段的實際範圍

獨立的 `scripts/contrarian_reversal_watch.py` 使用現有可重算的 6206 情境與五家製鞋公司情境，維持來源的股票／價格日期 2026-11-10 與原來 EPS、PE、公司行動限制；不調整主 V8 或 AlphaMax，也不自動下單。

指令：

```bash
python -m unittest discover -s tests -p 'test_contrarian_reversal_watch.py' -v
python scripts/contrarian_reversal_watch.py
```

輸出 `tw-market-data/rankings/latest_contrarian_reversal_watch.json` 與同名 `.md`，含共同參考價、三情境價、基準折價、下行情境、證據缺件與可追溯來源報告。11/10 報價與最新交易日不同時會標註過期，不假裝即時委託價。

初始研究觀察：

| 案例 | 2026/11/10 價 | Bear | Base | Bull | Base 價差 | 研究含意 |
|---|---:|---:|---:|---:|---:|---|
| 6206 飛捷 | 114.0 | 101.7 | 185.9 | 253.3 | +63.0% | 基準折價較大，須追蹤存貨轉現、回款與成長持續 |
| 9904 寶成 | 26.0 | 23.3 | 33.2 | 43.1 | +27.9% | 淨值拆分折價研究，並非已驗證 NAV |
| 6768 志強-KY | 59.9 | 21.5 | 58.6 | 110.9 | -2.1% | 基準接近市價，依賴獲利改善 |
| 9802 鈺齊-KY | 62.5 | 19.5 | 58.3 | 115.4 | -6.7% | 反轉具期權性，但基準尚非折價；毛利回升尚未證明 |
| 6890 來億-KY | 140.0 | 56.1 | 124.1 | 214.8 | -11.3% | 成長假設、CB 分母和研究估值風險需核對 |
| 9910 豐泰 | 67.8 | 22.9 | 47.9 | 91.7 | -29.4% | 現有基準假設不支持低估結論 |

本表由現有兩份估值 JSON 及初步四捨五入彙整，**不是全市場篩選、統計勝率、正式 TOP10、2027 期望總報酬或投資建議**。所有情境均無校準機率，未包含股利、稅費、成交價差。欠缺市場事前預期 EPS，所以「市場預期差」還不能聲稱已確認。

## 實作安全規格

- 拒絕不同日期報價、未來版估值、未來才公布的負面資訊、缺情境或 Bear>Base>Bull。
- 報表分開顯示 `BASE_DISCOUNT_WITH_LIMITED_SCENARIO_DOWNSIDE`、`UNCONFIRMED_RECOVERY_OPTION`、`REQUIRES_REVALUATION`，只是排序佇列，不是買賣訊號。
- 若將市價除以基準 PE，只標示 *敏感度代理 EPS*，**不是** 市場共識或真正預期差。
- 9802、6206 的市場疑慮列在 `tw-market-data/config/contrarian_overhang_v1.json`，屬當前研究摘要，**不能回填歷史 PIT 樣本**。
- `expected_return_pct`、`scenario_probabilities`、`recommendation` 必須維持 `null`；`formal_Aplus=false`，不繞開原風險品質審查。

## 下一階段缺件（Issue #187）

1. 官方市場母體與**同日**有效價格、股數與流動性，才能從 6 家擴至全市場。
2. 逐家公司原始財報及歷史公告版本，建構毛利率／成本改善 **PIT 領先訊號**。
3. 保留同業中沒有反轉的負樣本、退出市場的公司與嚴格樣本外 walk-forward。
4. 取得具日期的市場 EPS 預期（或建立**明示不是市場共識**的隱含 EPS），驗證預期差；校準前不能宣稱有可靠機率加權 2027 TOP10。

相關來源：
- `tw-market-data/rankings/v888_6206_independent_valuation.json`
- `tw-market-data/rankings/latest_footwear_review.json`
- `README_9802_CASH_REVIEW.md`、`README_FOOTWEAR_REVIEW.md`
- `README_EXPECTED_RETURNS.md`
