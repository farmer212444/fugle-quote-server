# V8.9.8 — Eight-quarter source coverage is by **period**, not file count

For 9802 the actual required period window ending 2026Q2 is:

\`2024-Q3, 2024-Q4, 2025-Q1, 2025-Q2, 2025-Q3, 2025-Q4, 2026-Q1, 2026-Q2\`.

The issuer original archive also happens to include **2024Q2**, outside this
eight-quarter window, and a separate **2026Q3 self-reported press release**.
Neither document may replace the 2025Q3 full financial report.

\`scripts/v896_original_archive.py:original_quarter_coverage()\` first
validates the original PDF file SHA256 against the permanent manifest, then
extracts the quarterly periods from distinct official Chinese or English
document titles. It returns the exact period list, any missing quarter,
duplicate-period source versions and explicit \`formal_gate_pass=false\`.

The gate report records \`8/8 SOURCE_CAPTURED\` when all eight title-identified
official original PDFs exist, but **never** upgrades the actual formal
\`original_eight_quarter_statements\` gate without examining the PDF internal
periods, four financial statements, full footnotes, auditor review scope,
restatements and historical issuer/MOPS publication dates.

The 2025Q3 English statement was first shown by the publisher's English index
on 2025-12-05. The audit report within it was dated 2025-11-06. The latter is
not an earlier certified online publication PIT date. The Chinese original,
which the company's English statement states takes precedence on translation
differences, should still be obtained for any contested review conclusion.

This is source-coverage accounting, not a signed issuer audit or portfolio
out-of-sample test. It does not change EPS, Base, PE, A+/A++, Exit, or schedules.
