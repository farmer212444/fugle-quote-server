# V8.9.1 A+ 證據認證修復

2026-10-20；狀態：實作已整合現有 V8.8.2 研究工作流。A+ 必須2027 Base漲幅≥30%，並且13項品質門檻全部PASS。A++另需≥35%與壓力測試。沒有修改門檻。

## 修復範圍

- 新增 scripts/v891_gate_certification.py：在研究模型之前讀取審閱完成的證據包，自動檢查個股及財報期間、原始文件SHA256、時序、審閱人的簽核方法與來源，合格後輸出供主模型消費的證書。
- 主模型 tw_model_v880/data.py 再次核對證書中引用的原始位元組；單憑宣稱PASS的檔案無法通過資料入庫。
- 研究模型後產出 v891_gate_progress.md 和 v891_gate_progress.json，對所有漲幅達30%的研究候選及重點持股列出13項的SOURCE_MISSING、MIRROR_CAPTURED、SOURCE_CAPTURED、REVIEW_PENDING、FORMAL_PASS、FORMAL_FAIL，不能混用。
- 沿用原本 .github/workflows/tw_v877_research_rank.yml 排程，不新增同名掃描排程。個股證據包不符合要求時單檔隔離，不影響其他股票處理。

## 實際可用的證據包格式

個股的受審閱來源包存放在 tw-market-data/evidence/v880/review_packs/{code}.json；實際原始公告位元組存放 tw-market-data/evidence/v880/originals/ 下（使用檔案真正SHA256，不是網頁URL雜湊）。

來源包根欄位：code、financial_period、gates。gates 是13個正式門檻名稱的子集合，每個門檻要求：

- status 必須PASS或FAIL，不接受PENDING假冒合格。
- issuer、financial_period、available_at、checked_at、expires_at 必須與當期公司及公告時間相符。
- review_completed=true、source_identity_reviewed=true、具名 reviewer_id、可稽核的 method 與 review_note。
- sources 非空，每件需有https URL、官方身份經審閱的 origin_authenticated=true、available_at、SHA256與 archive_path；檔案須在資料根目錄且雜湊吻合。
- 實際適用的CB、毛利率恢復、核閱保留結論、交易可行性等其他特殊子門檻仍依主模型審驗，不得只簽一般PASS來跳過。

一份合法的來源包可以只有一項已完成核閱的門檻，不需要一次補滿13項。自動系統會接納這一項，將其餘12項保留PENDING；當13項全部有效，原模型才會依現有30%／35%政策判斷正式A+／A++。

## 重要限制

雜湊確認的是已存檔資料的位元組完整性，不等於官方獨立數位簽章；具名審閱是可稽核的審閱紀錄，不等於經密碼學驗證的審閱者身份。純數字鏡像、20日收盤成交、現有CB股數的概估，不會自動提升為原始財報附註、法律條款或經紀商報價的正式PASS。

2026/10/20首次報告：研究可估值786檔，其中2027 Base潛在漲幅≥30%的有115檔；真正完成13項證據認證的正式A+為0。這115檔只是研究估值候選，不是歷史PIT回測命中。

## 相關檔案

- scripts/v891_gate_certification.py
- tests/test_v891_gate_certification.py
- tw_model_v880/evidence.py
- tw_model_v880/data.py
- tw-market-data/rankings/v891_gate_progress.md

後續應依序補齊獲利橋接及原始八季附註、CB流通餘額與法律條款、原始公告PIT、報價/價差及可成交性、真正樣本外報酬率驗證。若沒有這些證據，繼續重跑模型不能被宣稱已完成正式認證。
