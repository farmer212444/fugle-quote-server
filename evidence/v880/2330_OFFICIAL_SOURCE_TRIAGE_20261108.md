# 2330 官方財報缺件來源定位（2026-11-08）

**狀態：SOURCE_LOCATED_ONLY；NOT_ARCHIVED；NOT_REVIEWED；NOT_CERTIFIED。**
本文件僅記錄官方來源及下一步，沒有下載原件、沒有產生SHA256、沒有人工核閱或簽發PASS。

主分支當次工作佇列記錄：完整財報4/8季，缺2024-Q3、2025-Q4、2026-Q1、2026-Q2；SEC英譯0/7期SHA封存；公司品質0/12、策略0/1、正式A+ 0。不得以本來源定位覆寫這些數字。

| 模型缺件季度 | 官方來源定位 | 尚需驗收 |
|---|---|---|
| 2024-Q3 | https://investor.tsmc.com/chinese/financial-reports （2024年度前三季） | 下載對應完整合併財報，原始位元組、來源URL、首次取得時鐘、SHA256、季度與核閱範圍 |
| 2025-Q4 | https://investor.tsmc.com/chinese/financial-reports （2025年全年） | 注意全年報表涵蓋Q4，但不得誤標成單季完整財報；核對年度／單季推導及附註 |
| 2026-Q1 | https://investor.tsmc.com/chinese/financial-reports （2026年度第一季） | 同上原件與身份核對 |
| 2026-Q2 | https://investor.tsmc.com/chinese/financial-reports （2026年度上半年度） | 同上；可交叉核對 SEC 英譯 https://www.sec.gov/Archives/edgar/data/1046179/000104617926000541/a2026q2consolidatedreport-.htm |

2026Q2 SEC 英譯有會計師核閱報告及財報附註，但不等於中文完整原件，也不能取代具名核閱。

## 安全驗收步驟
1. 先重用 `evidence/v880/originals/2330/` 已保存的原件，逐檔核對實際SHA，避免重抓。
2. 對缺件季度只從公司官方完整合併財報下載；保留原始位元組、URL、擷取時間、檔案大小、SHA256與文件標題/期間；PDF與HTML不可冒充彼此。
3. 驗證8季覆蓋、各期修訂、附註、稀釋股數、會計師核閱/查核範圍，失敗逐季隔離；SEC英譯僅輔助勾稽。
4. 重新執行原研究工作流程、必要CI及發布後main報告核對，分別列12項公司品質與第13項樣本外策略門檻。
5. 在原件未真實封存、CI未通過、main未發布前，保持原有PENDING；不調整13項、30%/35%門檻或交易禁令。

此為來源定位研究文件，不代表程式錯誤已修復，不觸發額外排程。
