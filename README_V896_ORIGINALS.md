# V8.9.6 — 13-gate original-evidence intake, not automatic signoff

## What was actually automated

- Read **issuer-published 9802 audited/reviewed financial-report PDFs** and early
  2026-Q3 results from the existing issuer-source discovery manifest.
- Read **issuer-published 6206 investor-briefing PDFs** from the existing official
  publisher manifest.
- Download only from exact allowlisted HTTPS publisher hosts, reject the known
  malformed 2025-Q3 \`/img/Finance/.pdf\` link, reject bad/oversized PDF bytes,
  keep old and changed versions distinct by immutable content SHA, and preserve
  the time the bytes were **first captured** rather than backdating them to the
  company's displayed publication date.
- Permanently commit original PDF bytes and deterministic receipts at:
  \`tw-market-data/evidence/v880/originals/9802/\` and
  \`tw-market-data/evidence/v880/originals/6206/\`.
  This corrects the previous **90-day Actions artifact-only** durability gap.
- Verify bytes and their hashes afresh in V8.9.1's gate progress code; differentiate
  \`SOURCE_CAPTURED\` (file exists, partial source ready) from formal
  \`FORMAL_PASS\` (reviewed signed source, issuer notes and PIT verified).
- Reuse the **existing** 9802 and 6206 IR collector schedules. No additional
  cron or ChatGPT notification is created.

CLI:

\`\`\`bash
python -m unittest -v tests.test_v896_original_archive
python scripts/v896_original_archive.py --issuer 9802 --max-documents 10
python scripts/v896_original_archive.py --issuer 9802 --verify-only
python scripts/v896_original_archive.py --issuer 6206 --max-documents 3
python scripts/v896_original_archive.py --issuer 6206 --verify-only
\`\`\`

## Formal certification does not follow from file capture

The original 13 issuer gates, 2027 Base uplift thresholds, model's VERSION,
EPS/PE estimates, stock rankings, or Exit decisions **have not changed**.

- \`original_eight_quarter_statements\`: eight distinct required periods must
  be present, actual issuer and all statements/notes checked, restatements
  reconciled and dated. One PDF, or eight numerical mirrors, do not pass.
- \`cash_and_working_capital\`: original AR/inventory/AP/PPE/cash flow details
  and noncash movements must be reconciled, not mechanically scored.
- \`nonoperating_components\`: issuer-specific recurring vs volatile accounting
  needs an explicit earnings bridge.
- \`fully_diluted_shares\`: 2026 stock master, current CB conversion/reset
  terms, share-based compensation and matching diluted denominators need proof.
- \`matched_peers_and_cycle\`: peer business comparability and stress-tested
  own-cycle valuation need a documented review.
- \`management_promises\`: original briefing text alone cannot establish that
  orders/AI/ASP/utilization promises were subsequently met.
- \`auditor_scope\`: original full audit/review opinion and significant
  qualifications require materiality assessment.
- \`tradability\`: median turnover is not executable exit capacity; trading
  spread and order book or bounded execution evidence is still needed.
- \`forecast_bridge\`: verify 2027 margins/capacity/units/ASP/costs and
  model-code and share denominator against dated issuer information.
- \`insider_claims\`: match original disclosure events, distinct legal/person
  account identities and published PIT, not third-party monthly summaries.
- \`dividend_window\`: original corporate action dates, payment and relevant
  forecast horizon must be checked.
- \`point_in_time\`: the issuer's current website display date is NOT proof a
  specific statement or revision was public when a historical trade occurred.
- \`out_of_sample_validation\`: a retained-quarter accounting prediction
  is NOT a point-in-time portfolio, price or after-cost return backtest.

**Do not create synthetic or AI-impersonated human reviewer identities, approve
origin_authenticated=true merely from a URL, or copy a source hash into a formal
signed \`review_packs/\` file without independent documentary review.**

If 9802's original publisher links are missing/changed, a company release is
not yet a reviewed quarter or Q3 is self-reported, or 6206 materials omit
formal legal filing dates, the correct gate result is PENDING with that blocker.

## CI and limitations

- Bounded to issuer-originals most useful for 9802 and 6206; other ranked
  issuers need their own original-source verification path.
- The initial selected 9802 periods include 2024 Q3–2026 Q2 and 2026-Q3
  *self-reported* news. The publisher's malformed 2025-Q3 full-report link
  prevents treating this as a completed eight-quarter original packet.
- A publisher may revise a same URL. New bytes are stored as a new version
  and mismatching prior receipts are flagged. If the same source URL has not
  been recaptured since an older manifest version, do not infer absence of
  future revisions.
- All formal review packs remain subject to the existing validated signer/
  original-archive and timestamp requirements. The original snapshot's date,
  first observed date, and independently verified PIT date remain different.
