# 6206 Flytech eight PDF content page index — research-only

The prior source intake has eight complete archived quarterly PDFs, 2024Q3 to 2026Q2, each linked to an issuer or TWSE official source with a pinned SHA-256. Their existence alone cannot certify the 13 formal A+ gates.

`scripts/flytech_original_pdf_locator.py` creates `rankings/6206_original_pdf_page_locator_latest.json/.md`. For every quarter it independently recomputes the original PDF hash and byte count, validates manifest identity and period, confirms PDF page count and records **1-indexed physical PDF pages** where the following keywords appear:

- Accountant audit/review report, balance sheet, comprehensive income, equity changes and cash-flow statement headings
- Financial statement notes, inventories and potential write-downs, accounts receivable, payables, investing cash expenditure and operating cash flow

Keyword matches are **page leads for a human reviewer**, not actual balance values or accountant conclusions. Extraction failure means “manual visual check required”, never “no risk found”. No PDF content is edited and there are no live network downloads in this stage.

**What still needs real work**: review the original period labels, combined/group vs separate statements, YTD versus single-quarter and reported units; trace inventory and AR/AP opening/closing balance to cash flow with noncash/FX effects; match net profit to OCF and fixed-asset acquisitions; read accountant opinion and notes for inventory obsolescence, contingent obligations and related parties. Each numerical claim needs exact page, source SHA and independent double-entry reconciliation. The PDF first capture time is not proof of when its financial contents became publicly available.

No named reviewer or signoff is created by this script. `formal_gates_PASS_added=0` and `formal_Aplus=false`, even when all eight PDFs and all keywords are present. Quality and strategy certification are owned by the independent, unchanged model gate engine.

### Run
```bash
python -m unittest -v tests.test_flytech_original_pdf_locator
python scripts/flytech_original_pdf_locator.py --data-root tw-market-data
```
