#!/usr/bin/env python3
"""Stage isolated 0050 official-price research cache from verified archive receipts.

This copies only one ETF's historical RAW exchange responses and quote metadata
into a CI scratch directory. It never changes the legacy V8 repository files,
never claims 0050 total returns or PIT eligibility, and never ranks securities.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from scripts.history_archive import quote_source_ready, digest, canonical
from scripts.tw_history_backfill import combine

MONTH = re.compile(r"0050-20\d{2}-(0[1-9]|1[0-2])\Z")
ARCHIVE_EXT = re.compile(r"[0-9a-f]{64}\.json(?:\.gz)?\Z")
RELATIVE_PACKET = Path("prices/issuer_history/TWSE/0050.json")
RELATIVE_ORIGINAL = Path("prices/originals/history/TWSE")


def _packet(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(doc, dict) or doc.get("issuer") != "0050"
            or doc.get("market") != "TWSE" or not isinstance(doc.get("by_month"), dict)):
        raise ValueError("0050_RESTORED_PACKET_IDENTITY_OR_SCHEMA_INVALID")
    if any(not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", m)
           or not isinstance(item, dict) for m, item in doc["by_month"].items()):
        raise ValueError("0050_RESTORED_PACKET_MONTH_SCHEMA_INVALID")
    return doc


def _copy_originals(source_root, target_root):
    source = Path(source_root) / RELATIVE_ORIGINAL
    target = Path(target_root) / RELATIVE_ORIGINAL
    copied = 0
    if not source.exists():
        return 0
    for folder in sorted(source.iterdir()):
        if not MONTH.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
            continue
        for file in sorted(folder.iterdir()):
            if (file.is_symlink() or not file.is_file()
                    or not ARCHIVE_EXT.fullmatch(file.name)
                    or file.stat().st_size > 1024 * 1024):
                raise ValueError("0050_UNSAFE_OR_OVERSIZED_ORIGINAL_ARCHIVE")
            dest = target / folder.name / file.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                if dest.read_bytes() != file.read_bytes():
                    raise ValueError("0050_ORIGINAL_ARCHIVE_BYTE_CONFLICT")
            else:
                shutil.copyfile(file, dest)
                copied += 1
    return copied



def _validate_cached_source(root, packet, asof):
    # The original receipt alone does not authenticate the saved normalized
    # rows. Match the completed-month parsed SHA and derived session panel too.
    months = packet["by_month"]
    for month, item in months.items():
        rows = item.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("0050_CACHED_ROWS_MISSING:" + month)
        for row in rows:
            if (not isinstance(row, dict) or row.get("market") != "TWSE"
                    or row.get("code") != "0050"
                    or not isinstance(row.get("date"), str)
                    or row["date"][:7] != month
                    or date.fromisoformat(row["date"]).isoformat() != row["date"]
                    or row["date"] > asof):
                raise ValueError("0050_CACHED_ROW_DATE_OR_IDENTITY_INVALID:" + month)
        if not quote_source_ready(root, item):
            raise ValueError("0050_PREVIOUS_ARTIFACT_RAW_RECEIPT_INVALID:" + month)
        if month < asof[:7] and digest(canonical(rows)) != item["original_archive"].get("parsed_rows_sha256"):
            raise ValueError("0050_CACHED_PARSED_ROWS_SHA256_MISMATCH:" + month)
    recombined = combine({m: x["rows"] for m, x in months.items()}, asof, "0050")
    if packet.get("sessions") != recombined:
        raise ValueError("0050_CACHED_DERIVED_SESSIONS_MISMATCH")



def prepare_workspace(repo_root, workspace, prior_artifact=None):
    repo_root, workspace = Path(repo_root).resolve(), Path(workspace).resolve()
    source = repo_root / "tw-market-data"
    if workspace == source or source in workspace.parents or workspace == repo_root:
        raise ValueError("0050_SCRATCH_MUST_NOT_OVERWRITE_LEGACY_V8")
    manifest = json.loads((source / "prices/latest_manifest.json").read_text(encoding="utf-8"))
    asof = date.fromisoformat(manifest["date"]).isoformat()
    if manifest.get("path") != "tw-market-data/prices/" + asof + ".json":
        raise ValueError("0050_REFERENCE_MANIFEST_PATH_MISMATCH")
    snapshot = (source / "prices" / (asof + ".json")).read_bytes()
    if sha256(snapshot).hexdigest() != manifest.get("normalized_sha256"):
        raise ValueError("0050_REFERENCE_SOURCE_SHA256_MISMATCH")
    dest_prices = workspace / "prices"
    dest_prices.mkdir(parents=True, exist_ok=True)
    (dest_prices / "latest_manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    (dest_prices / (asof + ".json")).write_bytes(snapshot)
    base_file = source / RELATIVE_PACKET
    baseline = _packet(base_file) if base_file.is_file() else None
    copied = _copy_originals(source, workspace)
    restored_months = 0
    prior_run_archive = False
    if prior_artifact is not None:
        artifact = Path(prior_artifact)
        options = [artifact / "alphamax-0050-data", artifact / "tw-market-data"]
        source_cache = next((item for item in options if (item / RELATIVE_PACKET).is_file()), None)
        if source_cache is None:
            raise ValueError("0050_PRIOR_SUCCESS_ARTIFACT_MISSING_PACKET")
        cached = _packet(source_cache / RELATIVE_PACKET)
        if baseline:
            for month, item in baseline["by_month"].items():
                earlier = cached["by_month"].get(month)
                if earlier is None or earlier.get("original_response_sha256") != item.get("original_response_sha256") or earlier.get("rows") != item.get("rows"):
                    raise ValueError("0050_PREVIOUS_ARTIFACT_CONFLICTS_WITH_BRANCH")
        copied += _copy_originals(source_cache, workspace)
        _validate_cached_source(workspace, cached, asof)
        (workspace / RELATIVE_PACKET).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_cache / RELATIVE_PACKET, workspace / RELATIVE_PACKET)
        restored_months = len(cached["by_month"])
        prior_run_archive = True
    elif baseline:
        (workspace / RELATIVE_PACKET).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base_file, workspace / RELATIVE_PACKET)
    return {
        "status": "ISOLATED_RAW_0050_RESEARCH_CACHE_NOT_TOTAL_RETURN",
        "price_reference_date": asof,
        "previous_success_artifact_restored": prior_run_archive,
        "months_restored": restored_months,
        "original_receipt_files_copied": copied,
        "legacy_v8_files_modified": False,
        "historical_PIT_certified": False,
        "dividend_split_adjusted": False,
        "investor_total_return_certified": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path("."))
    p.add_argument("--data-root", type=Path, default=Path("alphamax-0050-data"))
    p.add_argument("--prior-artifact", type=Path)
    p.add_argument("--output", type=Path, default=Path("alphamax-0050-restore-progress.json"))
    args = p.parse_args()
    result = prepare_workspace(args.repo_root, args.data_root, args.prior_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
