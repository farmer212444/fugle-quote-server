# Dated TWD conversion-price correction

The 2026-10-24 official outstanding-bond feed contains 54391 face value
TWD 1,999,700,000 and its **issue** conversion price of TWD 300. The issuer's
anti-dilution notice, republished on 2026-07-07, adjusts that price to TWD 293.6
effective 2026-07-28:
https://news.cnyes.com/news/print/6525876

The static source refresh now makes one bounded capture of that identified
notice when no 5439 capital-terms book exists. The parser checks the announcement
title, measures paragraph, effective date and bond-code field together. The
unmodified response bytes are stored with a SHA-256 receipt and actual capture
clock. The normal dated loader applies the research term only at or after that
capture. Existing issuer books and first-capture receipts are preserved.

The announcement's zero-filled outstanding-balance fields are ignored. The
official bond feed supplies outstanding face value; the reset notice changes
only conversion price. This capture does not certify complete current legal
terms, original MOPS filing availability, fully diluted shares or formal A+.

Holding the 2026-10-25 00:48 Taipei model's other assumptions fixed gives:

|Input/output|Issue price used|Dated reset used|
|---|---:|---:|
|Conversion price (TWD)|300|293.6|
|Outstanding CB potential shares|6,665,666.67|6,810,967.30|
|Issued plus potential CB shares|99,641,418.67|99,786,719.30|
|2027 scenario EPS (TWD)|20.506864|20.477004|
|Scenario price at unchanged 24.215 PE (TWD)|496.573712|495.850645|
|Scenario upside from TWD 219.5|126.229482%|125.900066%|

These are mechanical sensitivities, not verified future returns. Official
publication after the fix must be checked separately against actual captured
bytes and newly generated model outputs.

Local validation:

```sh
PYTHONPATH=tests:. python -m unittest -v tests.test_twd_reset_capture \
  tests.test_footwear_review.ResetTermsTests tests.test_research_cache_refresh \
  test_v881.CapitalRegressionTests test_v881.GrowthHorizonRegressionTests
```

45 checks cover mismatched instruments/dates/prices, hidden and related news,
capture failures, immutable first capture, earlier-vintage rejection, preservation
of outstanding face value, cache invalidation and existing capital controls.
