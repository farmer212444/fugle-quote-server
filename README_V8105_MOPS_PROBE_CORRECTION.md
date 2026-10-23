# MOPS query6_1 original probe provenance and correction

**Research branch only, no formal A+/A++ insider PASS or PIT trade signal.**

Original raw HTTP bytes from six issuer-months, July–September 2026 for
9802 鈺齊-KY and 6965 中傑-KY, are preserved under two immutable captures:

- `run_39946736657_1`: genuine raw response bytes and SHA receipts. Its
  **generated** unverified_position_rollup.json has a **known parsing bug**:
  it failed to remove Unicode/ASCII whitespace when normalizing shareholder
  names. In particular 9802 Aug appears as **1,529 lots — WRONG**. Never use
  this first run's computed rollups as trading evidence.
- `run_39947008213_1`: fixed whitespace normalization, validated by 12
  parser tests plus the six archived-original SHA/market trade checks.
  Raw responses and receipts have newly captured timestamps. Corrected
  **provisional** net market lots are:

| Issuer | 2026-07 | 2026-08 | 2026-09 | Jul-Sep |
|---|---:|---:|---:|---:|
| 9802 鈺齊-KY | +464 | +1,101 | +231 | +1,796 |
| 6965 中傑-KY | +63 | +20.052 | +228 | +311.052 |

Market buys and sells are expressed in **individual shares** in the raw
MOPS report and divided by 1000 only to display lots. 9802 August is
428,000 + 503,000 + 170,000 unique-position shares; all repeated
director/general manager/10%-owner roles of the same named legal entities
must not be added again.

The de-duplication is deliberately **provisional**: a position signature
(normalized name, security class, opening/closing holding and market/other
flows) is not a unique beneficial holder/account identifier. Unnamed
spouses/minors can collide; the same entity may have multiple reporting
capacities. Source historical publication/first available timestamps, issuer
IRB110 balances, official share count, legal role, revisions, quarterly GM
release evidence and all corporate actions are not certified by this capture.

Even though **official original response bytes now exist**, the original
MOPS post-trade data quality gate remains **PENDING**. These captures occurred
in October 2026 and cannot be automatically used to create artificially
early July/August 2026 PIT trading signals.

Primary query: https://mops.twse.com.tw/mops/api/query6_1
Original captures: 
https://github.com/farmer212444/fugle-quote-server/tree/research/insider-pit-shadow-20261023/tw-market-data/evidence/v880/insider_reviews/original_probe_archive

No real 365-day return observations are available from a freshly registered
October 2026 forward study; 0050 adjusted net returns remain unverified.
