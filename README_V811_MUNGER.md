# V8.11 (candidate): Munger Quality & Inversion — evidence-only review lane

**Status:** proposed research extension. This branch keeps the active executable and official valuation version at V8.10.8. Do **not** label this as a new certified model or demonstrated excess return.

## What changed

- Added a read-only inversion audit over **all issuer diagnostic rows actually published** in the existing 13-gate report. The model-evaluated count, published diagnostic count, evaluated-but-not-expanded count and not-evaluated count are always shown separately.
- Cross-check the official 13 gate names, individual decisions, evaluated count, model version, price date, estimate vintage and existing A+ count. Mismatched or forged decisions fail closed.
- Focused institutional detail identifies double 20% EPS/PE downside, missing forward bridge, missing peer PE evidence, exit capacity, common-risk profile and recorded governance blocks.
- For each company list the next three **questions that could falsify** its Base thesis. Questions are **not** findings that a company failed.
- Generate a separate due-diligence view ordered primarily by already identified blocking and negative-stress concerns, **not** biggest supposed return.
- Preserve original Base/Bear/Bull, EPS/PE, governance ledger, 13 quality gates, A+>=30%/A++>=35% rules. No new formal gate, trade signal, algorithmic recommendation or probability.
- Current model does not upgrade from V8.10.8 until a separate version release.

## Run

After ordinary institutional observation, run:

    python scripts/munger_quality_review.py
    python -m unittest -v tests.test_munger_review

Reports:
- tw-market-data/rankings/latest_munger_review.json
- tw-market-data/rankings/latest_munger_review.md

Reports include SHA256 of both sourced input reports. No claim of historical completeness.

## Current limits

- Questions are verification tasks, not completed unit-economics or durable-moat analyses.
- Governance flags only cover previously archived events; missing flags do not prove clearance.
- Focused tables cover existing institutional-reviewed issuers, not all 2,000 at comparable depth.
- PENDING must not become PASS or FAIL through this overlay.
- PIT filing dates, missing notes, CB dilution and benchmark return periods remain incomplete; original gates must remain enforced.
- New unit tests must pass, as must prior 13-gate and pipeline tests, and PR must run in nonpublishing mode before merging.

## Maintainer release checklist

1. Test new provenance, false certification, governance and stress cases.
2. Verify original research ranks, policy and model VERSION unchanged.
3. Run the existing PR pipeline without main publication.
4. Promote a future V8.11 runtime only after separate reviewed release and valid sample-out results.
