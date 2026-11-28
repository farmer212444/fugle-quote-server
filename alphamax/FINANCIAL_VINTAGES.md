# Observed financial versions

This archive preserves the official TWSE general-industry income JSON response,
compressed without changing its original bytes. It records capture time, original
and archive SHA-256, issuer/quarter payloads and observation supersession links.
It imports no V8 forecasts or certification fields.

The first capture is NOT the company's first filing. A changed value is an
unclassified observed change, NOT proof of an official correction or its time.
Issuer publication time remains null. Availability is the actual capture time;
the fiscal period and daily ROC batch date cannot backdate it.

Run:
    python -m alphamax.financial_vintages --archive-root alphamax/research/financial-vintages --output alphamax-financial-vintages-report.json
    python -m unittest -v tests.test_alphamax_financial_vintages

The reader rechecks saved originals and their receipts, reparses the exact issuer
row, verifies version hashes and the chronology/supersession chain, then selects
only versions available at the requested aware timestamp. Daily batch-date
changes alone do not create new financial versions. Different fiscal quarters
have separate chains. All focus issuers must reconcile before a capture is added.

The dedicated workflow has read-only repository permissions. Its original-source
checkpoint can be inspected and committed to this same research branch, keeping
originals reproducible beyond the Actions artifact's 90-day retention. No
workflow automatically pushes, modifies main, or admits training observations.

A Git commit and SHA-256 receipts establish reproducibility against saved bytes;
they are not an exchange signature or independent historical source audit.
Historical PIT batch count and verified model OOS cohorts remain zero.

## Evidence still required for historical financial admission

For a bounded, predeclared issuer/period pilot, preserve original first filing and
each correction document, the source index or announcement binding the exact
document/version to its public release time, and a complete revision ledger.
Do not reconstruct a full prior statement from a correction summary. Verify
income, balance-sheet and cash-flow availability separately. Independently
reproduce old and new views before extending to the agreed historical universe.

If first-filing timestamps or superseded bytes are unavailable, keep the older
period BLOCKED; new observed captures can only support prospective research.

## Historical financial-notice pilot (2026-11-27)

The earlier probe posted only an index request and checked for amounts that exist
in a separate detail document. It also used date1/date2 instead of the actual
b_date/e_date fields. The repaired reader selects an exact company/date/time/title
index row, parses its five whitelisted detail assignments without evaluating
JavaScript, and preserves the parent form's year, month and other hidden inputs.
Both index and detail originals are saved before parsing, including rejected HTML.

The bounded 6967 2025Q2 pilot preserves its board financial-release notice
(2025-08-13 14:01:48 Taipei) and correction notice (2025-08-14 15:37:02 Taipei),
with four original index/detail responses, request receipts and SHA-256 hashes.
The correction states treasury-share counts before and after correction. Its
publication does not establish when the superseded iXBRL was originally filed
or when the corrected iXBRL upload completed. The earlier share value has no
assigned historical availability time.

Run the offline receipt audit:
    python -m alphamax.financial_notice_receipts --output-dir alphamax/research/financial-notice-pilot --verify-only

This is retrospective original-notice evidence, not a historical as-published
snapshot or a complete financial revision chain. Financial training admission,
formal model OOS, A+ and model winner status remain blocked.
