# V8.9.7 Prospective full-universe research vintage archive

The 13th formal quality gate requires a historically frozen, exactly dated
model and an honest price/total-return backtest. The previous workflow
replaced latest ranking data and retained no systematic per-vintage complete
archive. This change **stops losing future model vintages**, but cannot
conjure historically unpublished records or certify a prior trading result.

## Source contract

On the existing nightly **research** workflow's main publication step,
after the model outputs are successfully recomputed from the latest source:

\`\`\`bash
python scripts/v897_freeze_model_vintage.py --git-source-sha "$(git rev-parse HEAD)"
\`\`\`

This creates an immutable, content-addressed directory under
\`tw-market-data/pit_vintages/<Taipei estimate day>/<digest>/\`:

- \`latest_research.json\` — exact normalized research publication bytes.
- \`full_results.json.gz\` — actual 1,997+/year issuer model rows and excluded
  issuers from this run, not only the Top10 shortlist.
- \`reference_prices.json\` — the exact unadjusted official market reference
  snapshot used in the model, with hash cross-checked to price manifest.
- \`receipt.json\` — model/version/timestamp, reference price date, the current
  financial quarter and revenue month, reproducible source-manifest SHA,
  model Git commit SHA, hash/size of every above archive file, and explicit
  \`false\` values for historical PIT and sample-outcome certification.

The archived market-universe count is recomputed from all model rows and
must match the compact model \`data_scope.model_rows\`. Both compressed and
decompressed full-result hashes must match the model publication. A file
whose bytes or source period do not match causes a **hard failure**, not a
missing-as-zero or a fabricated certified investment return.

A repeated identical estimate is kept at one content-addressed path; a
changed estimate/source is archived as a distinct vintage. An existing
vintage file is immutable, and its hashes are rechecked on reuse.

## Boundaries

**What this closes now:** durability of prospective model vintages,
explicit market-reference dates, exact research source hashes and full
tracked-issuer universe for later walk-forward evaluation.

**What this does not close now:** the 12th gate's original issuer publication
and revision PIT; 13th gate's independently validated total-return
investment backtest with delistings, dividends, capital changes, borrow,
fees, spreads, or executable trades; historical 2020/2025 vintages that
were never captured when they existed. The initial 2026-10-21 archive is a
forward-starting research observation, not 2020 hindsight.

No additional cron, automated trading, false A+ certificate, forced Exit,
revaluation, or weakened 13-gate quality rule is introduced. The main
VERSION remains authoritative.
