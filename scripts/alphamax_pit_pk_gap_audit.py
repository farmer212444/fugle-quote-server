#!/usr/bin/env python3
"""Verify *absence/presence* of 12m AlphaMax training evidence at one main commit."""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
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
from scripts.alphamax_0050_restore import _packet, _validate_cached_source

OFFICIAL_REF = "origin/main"
PRICE_MANIFEST_PATH = "tw-market-data/prices/latest_manifest.json"
FINANCIAL_MANIFEST_PATH = "tw-market-data/financial/latest_manifest.json"
HIST_FINANCIAL_PATH = "tw-market-data/fundamentals/historical_readiness/2025-12-31.json"


def _git(repo, *parts, allow_missing=False):
    result = subprocess.run(["git", "-C", str(repo), *parts], capture_output=True, check=False)
    if result.returncode and not allow_missing:
        raise ValueError("GIT_MAIN_SOURCE_READ_FAILED:" + " ".join(parts))
    return result.stdout if result.returncode == 0 else None


def stage_verified_0050_quote_cache(cache_root, history_work, main_price_asof):
    """Re-use separately archived 0050 raw prices ONLY after receipt integrity checks.

    This stages an observation for the gap audit, not a PIT return label,
    dividend-adjusted benchmark, external authentication or investable signal.
    """
    root = Path(cache_root)
    source = root / "prices/issuer_history/TWSE/0050.json"
    if not source.is_file():
        raise ValueError("0050_ISOLATED_RECEIPT_PACKET_MISSING")
    packet = _packet(source)
    packet_asof = date.fromisoformat(packet.get("price_reference_asof", ""))
    cutoff = date.fromisoformat(main_price_asof)
    if packet_asof > cutoff:
        raise ValueError("0050_CACHE_AFTER_PINNED_MAIN_QUOTE_CUTOFF")
    # Check the normalized rows, derived sessions, and archived original bytes
    # before allowing the isolated data to inform raw-history coverage.
    _validate_cached_source(root, packet, packet_asof.isoformat())
    raw = source.read_bytes()
    dest = Path(history_work) / "TWSE/0050.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return {
        "status": "ISOLATED_ORIGINAL_RECEIPT_INTEGRITY_CHECKED_PRICE_ONLY",
        "packet_sha256": sha256(raw).hexdigest(),
        "cache_reference_date": packet_asof.isoformat(),
        "monthly_receipts": len(packet["by_month"]),
        "price_only_not_total_return": True,
        "historical_pit_membership_certified": False,
        "external_source_authentication_certified": False,
    }


def audit_main(freeze, repo_root, work, git_ref=OFFICIAL_REF, benchmark_cache_root=None):
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

    benchmark_origin = {"status": "MAIN_BRANCH_RAW_HISTORY_ONLY", "price_only_not_total_return": True}
    if benchmark_cache_root is not None:
        benchmark_origin = stage_verified_0050_quote_cache(
            benchmark_cache_root, work, pmanifest["date"])
    report = audit_frozen_pit_gaps(freeze, work, pmanifest, fmanifest, hstatus)
    report["benchmark_0050_quote_source"] = benchmark_origin
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
    p.add_argument("--benchmark-cache-root", type=Path, default=None)
    p.add_argument("--output", type=Path, default=Path("alphamax-pk-training-gap-audit.json"))
    a = p.parse_args()
    freeze = json.loads(a.freeze.read_text(encoding="utf-8"))
    result = audit_main(freeze, a.repo, a.history_cache, a.source_ref,
                        benchmark_cache_root=a.benchmark_cache_root)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "source_main_commit": result["main_source_commit"],
        "asof": result["asof_price_date"],
        "0050_session_count": result["benchmark_0050"]["priced_sessions"],
        "0050_quote_source": result["benchmark_0050_quote_source"]["status"],
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
