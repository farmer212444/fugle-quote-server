# V8.10.8 - missing price gaps and stale PR research chronology

## Root causes observed 2026-11-12

1. The scheduled research refresh finished the 2026-11-12 official quote fetch and early source cache safety checks, but `research_work_queue.render` tried to format a missing 2330 price upside as `{None:+.1f}%`. This crashed the independent evidence work queue before a dated update could publish. An unknown market/financial source must stay unknown, not become a zero upside, price certification, or system-wide exception.
2. The prospective drawdown **pull-request-only smoke test** was invoked against a stale risk report dated 2026-11-10 after the repository's latest official market price manifest advanced to 2026-11-12. `make` correctly failed the mixed-date SHA verification, but that does not mean the previously frozen risk cohort was corrupt. The smoke test was inappropriate for the stale source context.

## Changes

- Format only finite non-boolean, numeric 2027 research price gaps as percentages. Explicitly print `待核（缺少可比較估值）` for `None`, infinity, NaN or boolean. If a stale classification claims A+ price candidate with a missing or below-30% numeric gap, do not represent it as a current A+ price candidate; the engine's original decision is **not** changed.
- New prospective PR source freshness helper checks both reference market date and report date. When a **newer dated official market manifest** has arrived, the PR smoke test explicitly skips trying to register the prior-day risk cohort. When the manifest is on the same date, it still invokes `make` and requires exact source hash match. An older/invalid price manifest fails and may not be silently skipped.
- Test the missing gap cases, genuine candidate calculation, inconsistency, same-date and newer-date risk cohort source behavior. Rerun the actual `research_work_queue.py` from archived GitHub inputs.

## Strict guarantees

- The official 13 gates, price hurdle, market price receipt SHA, source chronology, prospective cohort first-registration and A+ determination are **unchanged**.
- No price or probability imputation. No retroactive PIT issuance, new trading signals or automatic quality PASS.
