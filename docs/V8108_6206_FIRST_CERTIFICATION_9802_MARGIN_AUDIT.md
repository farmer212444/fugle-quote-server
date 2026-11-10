# V8.10.8 A+ certification repair — 6206 first, 9802 margin test

## Purpose
The pipeline currently reports zero certified company gates on 1,410 evaluated companies, despite some data mirrors, company PDFs and multiple official price sessions. This is not evidence that all companies fail quality. It means the strict dated review packs and prospective PIT strategy evidence have not been completed. A fetched PDF, its SHA receipt, and a completed test cannot be converted into a named reviewer signoff.

## Implemented
- New `v8108_focus_aplus_repair.py` runs **after** existing company-quality and footwear research; the exact same model estimate vintage and closing date are mandatory across files.
- 6206 Flytech: rehash original bytes of each archived presentation and compare to the manifest's SHA256; then prepare a 13-gate reviewer handoff (all `PENDING`) inside `rankings/6206_gate_review_starter_latest.json`, **not** inside admitted `evidence/v880/review_packs`. No reviewer name, invented publication time, reviewed status or quality PASS is filled in.
- Sort human/workflow next actions by priority: eight complete financial statements and notes; cash/working capital; diluted shares; company-specific 2027 operating bridge; auditor opinion; nonoperating gains; exit liquidity and PIT. Strategy OOS remains the distinct 13th gate and cannot be solved by a cashflow arithmetic check.
- 9802 Fulgent Sun: recompute 2027 gross-margin level **needed to reach a 30% research price gap** under the unchanged main-model 2027 revenue, operating expenses, nonoperating items, tax, attribution, diluted shares and P/E. Verify exact EPS-to-PE target and percentage-point sensitivity math. Original 2026Q3 issuer self-report is unaudited; the separately entered 2025/2026Q2 cost structure has **no archived issuer presentation PDF in this repository**, so it is explicitly non-certifying.
- Use all sources only to generate `rankings/latest_focus_aplus_repair.json/.md`; no changes to model 2027 EPS, target, A+ policy, positions, orders or certification.

## What constitutes progress
Real progress means each original issuer-quarter PDF (with revisions, full four statements and notes) is saved and rehashed, each named reviewer documents a dated and method-specific decision with source identity and verified original publication chronology, and 2027 EPS/PE forecast contract is consistently traceable. An individual independently admissible gate can be reviewed without waiting for the other 12; the report must still say PENDING for missing gates. The 13th, strategy PIT and costed Walk Forward, requires genuinely historical vintage evidence and prospective outcomes that cannot be manufactured by reruns.

## Run
```bash
python -m unittest -v tests.test_v8108_focus_aplus_repair
python scripts/v8108_focus_aplus_repair.py --data-root tw-market-data
```

## Important
The 9802 margin hurdle is a numerical condition **not** a recommended gross margin, earnings estimate, A+ quality certificate or promised return. The Flytech reviewer starter is intentionally inadmissible by `v891_gate_certification.validate_review_pack` without genuinely authenticated original source bytes, reviewer identification and dated evidence review.
