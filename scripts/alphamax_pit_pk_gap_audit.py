#!/usr/bin/env python3
"""Verify *absence/presence* of 12m AlphaMax training evidence at one main commit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax.pk_exhibition import validate_freeze
from alphamax.pit_pk_gap_audit import audit_frozen_pit_gaps

OFFICIAL_REF = "origin/main"
PRICE_MANIFEST_PATH = "tw-market-data/prices/latest_manifest.json"
FINANCIAL_MANIFEST_PATH = "tw-market-data/financial/latest_manifest.json"
HIST_FINANCIAL_PATH = "tw-market-data/fundamentals/historical_readiness/2025-12-31.json"


def _git(repo, *parts, allow_missing=False):
    result = subprocess.run(["git", "-C", str(repo), *parts], capture_output=True, check=False)
    if result.returncode and not allow_missing:
        raise ValueError("GIT_MAIN_SOURCE_READ_FAILED:" + " ".join(parts))
    return result.stdout if result.returncode == 0 else None


def audit_main(freeze, repo_root, work, git_ref=OFFICIAL_REF):
    if git_ref != OFFICIAL_REF and not re.fullmatch(r"[a-f0-9]{40}", git_ref):
        raise ValueError("UNPINNED_SOURCE_REF_NOT_ALLOWED")
    repo_root = Path(repo_root)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    commit = _git(repo_root, "rev-parse", git_ref).decode().strip()
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("NO_VERIFIED_SOURCE_COMMIT")
    def object_from_commit(path):
        raw = _git(repo_root, "show", commit + ":" + path)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("INVALID_SOURCE_JSON:" + path) from exc

    pmanifest = object_from_commit(PRICE_MANIFEST_PATH)
    fmanifest = object_from_commit(FINANCIAL_MANIFEST_PATH)
    hstatus = object_from_commit(HIST_FINANCIAL_PATH)
    ids = validate_freeze(freeze)
    identities = ids["alpha_lane"] | ids["v8_lane"] | {("TWSE", "0050")}
    for market, code in sorted(identities):
        dest = work / market / (code + ".json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        original = _git(repo_root, "show", commit +
                        f":tw-market-data/prices/issuer_history/{market}/{code}.json",
                        allow_missing=True)
        if original is not None:
            dest.write_bytes(original)
        elif dest.exists():
            # Reused workspace must never serve an old file as fresh main evidence.
            dest.unlink()

    report = audit_frozen_pit_gaps(freeze, work, pmanifest, fmanifest, hstatus)
    report["main_source_commit"] = commit
    report["source_file_paths"] = {
        "price_manifest": PRICE_MANIFEST_PATH,
        "financial_manifest": FINANCIAL_MANIFEST_PATH,
        "historical_financial_status": HIST_FINANCIAL_PATH,
        "issuer_quote_packets": "tw-market-data/prices/issuer_history/{market}/{code}.json",
    }
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--freeze", type=Path, default=ROOT / "alphamax/research/2026-11-11-v8-alphamax-pk-frozen.json")
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--source-ref", default=OFFICIAL_REF)
    p.add_argument("--history-cache", type=Path, default=Path("alphamax-pk-source/issuer-history"))
    p.add_argument("--output", type=Path, default=Path("alphamax-pk-training-gap-audit.json"))
    a = p.parse_args()
    freeze = json.loads(a.freeze.read_text(encoding="utf-8"))
    result = audit_main(freeze, a.repo, a.history_cache, a.source_ref)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "source_main_commit": result["main_source_commit"],
        "asof": result["asof_price_date"],
        "0050_session_count": result["benchmark_0050"]["priced_sessions"],
        "0050_raw_history_days": result["benchmark_0050"]["calendar_span_days"],
        "alpha_potential_raw_12m_spans": result["lanes"]["alpha_lane"]["raw_quote_spans_at_least_12m"],
        "v8_potential_raw_12m_spans": result["lanes"]["v8_lane"]["raw_quote_spans_at_least_12m"],
        "issuer_pit_admitted": result["issuer_publication_pit_admitted"],
        "verified_oos_12m": result["verified_12m_after_cost_walk_forward_cohorts"],
        "official_winner": result["winner"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print("ALPHAMAX_PIT_DATA_GAP_AUDIT_BLOCKED: " + str(exc), file=sys.stderr)
        sys.exit(2)
