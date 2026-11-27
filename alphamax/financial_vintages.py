"""Preserve observed official income versions; never invent filing clocks."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from alphamax.core import ContractError
from alphamax.reported_income import UNITS, reconcile_income

SOURCE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
SCHEMA = "ALPHAMAX_OBSERVED_FINANCIAL_VINTAGES_V1"
FOCUS_CODES = ("2330", "2317", "6206", "9802")
MAX_BYTES = 10_000_000
TZ = timezone(timedelta(hours=8))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def clock(value):
    if not isinstance(value, str):
        raise ContractError("AWARE_OBSERVATION_TIME_REQUIRED")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("INVALID_OBSERVATION_TIME") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ContractError("AWARE_OBSERVATION_TIME_REQUIRED")
    return result.astimezone(timezone.utc)


def codes_checked(codes):
    if (not isinstance(codes, (list, tuple)) or not codes
            or any(not isinstance(c, str) or not re.fullmatch(r"[0-9]{4}", c) for c in codes)
            or len(codes) != len(set(codes))):
        raise ContractError("UNIQUE_FOUR_DIGIT_CODES_REQUIRED")
    return tuple(codes)


def source_rows(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ContractError("INVALID_FINANCIAL_ORIGINAL_SIZE")
    rows = json.loads(raw)
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) for r in rows):
        raise ContractError("FINANCIAL_SOURCE_ROWS_REQUIRED")
    return rows


def payload_for(rows, code, observed_at):
    matches = [r for r in rows if r.get("公司代號") == code]
    if len(matches) != 1:
        raise ContractError("MISSING_OR_DUPLICATE_ISSUER:" + code)
    row = matches[0]
    result = reconcile_income(row, units=UNITS)
    if result["status"] != "RECONCILED_REPORTED_FACTS_ONLY":
        raise ContractError("FINANCIAL_EQUATIONS_DO_NOT_RECONCILE:" + code)
    year, quarter = int(row["年度"]) + 1911, int(row["季別"])
    next_quarter = datetime(year + (quarter == 4), 1 if quarter == 4 else quarter * 3 + 1, 1)
    period_end = (next_quarter - timedelta(days=1)).date()
    if period_end > clock(observed_at).astimezone(TZ).date():
        raise ContractError("FINANCIAL_PERIOD_HAS_NOT_ENDED")
    batch = str(row.get("出表日期", ""))
    if not re.fullmatch(r"[0-9]{7}", batch):
        raise ContractError("INVALID_SOURCE_BATCH_DATE")
    batch_day = datetime(int(batch[:3]) + 1911, int(batch[3:5]), int(batch[5:7])).date()
    if batch_day > clock(observed_at).astimezone(TZ).date():
        raise ContractError("SOURCE_BATCH_AFTER_OBSERVATION")
    payload = {"row": {k: v for k, v in row.items() if k != "出表日期"},
               "units": dict(UNITS)}
    return result["fiscal_period"], payload


def safe_file(root, relative):
    if not isinstance(relative, str) or not re.fullmatch(r"originals/[0-9a-f]{64}\.json\.gz", relative):
        raise ContractError("UNSAFE_FINANCIAL_ORIGINAL_PATH")
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ContractError("FINANCIAL_ORIGINAL_ESCAPES_ROOT")
    return path


def verify_archive(root):
    """Reparse originals and validate every content/clock/supersession link."""
    root = Path(root)
    path = root / "ledger.json"
    if not path.exists():
        return {"schema": SCHEMA, "snapshots": [], "versions": []}
    ledger = json.loads(path.read_bytes())
    if (not isinstance(ledger, dict) or set(ledger) != {"schema", "snapshots", "versions"}
            or ledger["schema"] != SCHEMA
            or not isinstance(ledger["snapshots"], list)
            or not isinstance(ledger["versions"], list)):
        raise ContractError("INVALID_FINANCIAL_VERSION_LEDGER")
    snapshots, parsed = {}, {}
    previous_clock = None
    for snapshot in ledger["snapshots"]:
        required = {"snapshot_id", "source_url", "observed_at", "original_sha256",
                    "original_bytes", "archive_path", "archive_sha256"}
        if not isinstance(snapshot, dict) or set(snapshot) != required:
            raise ContractError("INVALID_FINANCIAL_SNAPSHOT_RECEIPT")
        sid = snapshot["snapshot_id"]
        if sid != digest({k: v for k, v in snapshot.items() if k != "snapshot_id"}) or sid in snapshots:
            raise ContractError("FINANCIAL_SNAPSHOT_RECEIPT_HASH_OR_DUPLICATE")
        observed = clock(snapshot["observed_at"])
        if observed > datetime.now(timezone.utc) or (previous_clock and observed <= previous_clock):
            raise ContractError("INVALID_FINANCIAL_SNAPSHOT_CLOCK_ORDER")
        if snapshot["source_url"] != SOURCE_URL:
            raise ContractError("UNEXPECTED_FINANCIAL_SOURCE")
        relative = "originals/" + snapshot["original_sha256"] + ".json.gz"
        if snapshot["archive_path"] != relative:
            raise ContractError("FINANCIAL_ORIGINAL_PATH_HASH_MISMATCH")
        packed = safe_file(root, relative).read_bytes()
        if sha256(packed).hexdigest() != snapshot["archive_sha256"]:
            raise ContractError("FINANCIAL_ARCHIVE_HASH_MISMATCH")
        raw = gzip.decompress(packed)
        if (len(raw) != snapshot["original_bytes"] or len(raw) > MAX_BYTES
                or sha256(raw).hexdigest() != snapshot["original_sha256"]):
            raise ContractError("FINANCIAL_ORIGINAL_HASH_MISMATCH")
        parsed[sid] = source_rows(raw)
        snapshots[sid] = snapshot
        previous_clock = observed
    latest = {}
    previous_version_clock = None
    required = {"version_id", "snapshot_id", "market", "code", "fiscal_period",
                "statement", "available_at", "issuer_published_at", "previous_version_id",
                "change_class", "payload", "payload_sha256"}
    for version in ledger["versions"]:
        if not isinstance(version, dict) or set(version) != required:
            raise ContractError("INVALID_FINANCIAL_VERSION_RECORD")
        if version["version_id"] != digest({k: v for k, v in version.items() if k != "version_id"}):
            raise ContractError("FINANCIAL_VERSION_HASH_MISMATCH")
        snapshot = snapshots.get(version["snapshot_id"])
        if snapshot is None:
            raise ContractError("FINANCIAL_VERSION_SOURCE_MISSING")
        if (version["market"] != "TWSE" or version["statement"] != "income"
                or version["issuer_published_at"] is not None
                or version["available_at"] != snapshot["observed_at"]):
            raise ContractError("UNPROVEN_PUBLICATION_OR_BACKDATED_AVAILABILITY")
        codes_checked([version["code"]])
        when = clock(version["available_at"])
        if previous_version_clock and when < previous_version_clock:
            raise ContractError("FINANCIAL_VERSION_CLOCK_ORDER")
        period, payload = payload_for(parsed[version["snapshot_id"]], version["code"], version["available_at"])
        if (period != version["fiscal_period"] or payload != version["payload"]
                or digest(payload) != version["payload_sha256"]):
            raise ContractError("FINANCIAL_VERSION_DIFFERS_FROM_ORIGINAL")
        key = (version["market"], version["code"], period, version["statement"])
        prior = latest.get(key)
        expected_previous = prior["version_id"] if prior else None
        change = "OBSERVED_VALUES_CHANGED_UNCLASSIFIED" if prior else "FIRST_OBSERVED_SNAPSHOT"
        if version["previous_version_id"] != expected_previous or version["change_class"] != change:
            raise ContractError("BROKEN_FINANCIAL_VERSION_CHAIN")
        if prior and (prior["payload_sha256"] == version["payload_sha256"]
                      or clock(prior["available_at"]) >= when):
            raise ContractError("UNCHANGED_OR_NONCHRONOLOGICAL_FINANCIAL_VERSION")
        latest[key] = version
        previous_version_clock = when
    return ledger


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical(value) + b"\n")
    temporary.replace(path)


def append_snapshot(root, raw, *, codes=FOCUS_CODES, observed_at=None):
    """Append capture-time versions; a batch date never becomes publication time."""
    root = Path(root)
    codes = codes_checked(codes)
    observed = datetime.now(timezone.utc) if observed_at is None else clock(observed_at)
    if observed > datetime.now(timezone.utc):
        raise ContractError("FUTURE_FINANCIAL_OBSERVATION")
    stamp = observed.isoformat()
    ledger = verify_archive(root)
    rows = source_rows(raw)
    prepared = [(code, *payload_for(rows, code, stamp)) for code in codes]
    packed = gzip.compress(raw, mtime=0)
    raw_sha = sha256(raw).hexdigest()
    snapshot = {"source_url": SOURCE_URL, "observed_at": stamp,
                "original_sha256": raw_sha, "original_bytes": len(raw),
                "archive_path": "originals/" + raw_sha + ".json.gz",
                "archive_sha256": sha256(packed).hexdigest()}
    snapshot["snapshot_id"] = digest(snapshot)
    ids = {s["snapshot_id"] for s in ledger["snapshots"]}
    if snapshot["snapshot_id"] in ids:
        raise ContractError("DUPLICATE_FINANCIAL_CAPTURE")
    if ledger["snapshots"] and observed <= clock(ledger["snapshots"][-1]["observed_at"]):
        raise ContractError("FINANCIAL_CAPTURE_CANNOT_BE_BACKDATED")
    latest = {(v["market"], v["code"], v["fiscal_period"], v["statement"]): v
              for v in ledger["versions"]}
    added = []
    for code, period, payload in prepared:
        prior = latest.get(("TWSE", code, period, "income"))
        payload_sha = digest(payload)
        if prior and prior["payload_sha256"] == payload_sha:
            continue
        version = {"snapshot_id": snapshot["snapshot_id"], "market": "TWSE",
                   "code": code, "fiscal_period": period, "statement": "income",
                   "available_at": stamp, "issuer_published_at": None,
                   "previous_version_id": prior["version_id"] if prior else None,
                   "change_class": "OBSERVED_VALUES_CHANGED_UNCLASSIFIED" if prior else "FIRST_OBSERVED_SNAPSHOT",
                   "payload": payload, "payload_sha256": payload_sha}
        version["version_id"] = digest(version)
        added.append(version)
    dest = safe_file(root, snapshot["archive_path"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.read_bytes() != packed:
        raise ContractError("FINANCIAL_ORIGINAL_IMMUTABILITY_CONFLICT")
    if not dest.exists():
        dest.write_bytes(packed)
    ledger["snapshots"].append(snapshot)
    ledger["versions"].extend(added)
    write_json(root / "ledger.json", ledger)
    verify_archive(root)
    return {"schema": SCHEMA, "status": "OBSERVED_FINANCIAL_VERSIONS_CAPTURED_NOT_HISTORICAL_PIT",
            "snapshot_id": snapshot["snapshot_id"], "observed_at": stamp,
            "source_url": SOURCE_URL, "original_sha256": raw_sha,
            "source_row_count": len(rows), "focus_issuers": list(codes),
            "new_versions": len(added), "total_versions": len(ledger["versions"]),
            "snapshot_count": len(ledger["snapshots"]),
            "issuer_publication_timestamps_verified": False,
            "admitted_historical_PIT_batches": 0, "verified_model_oos_cohorts": 0,
            "formal_a_plus": False, "buy_signal": False,
            "note": "Capture time is conservative observed availability, not first filing time. Changed values are not a verified issuer correction."}


def select_asof(root, asof):
    """Research-only observed values, verified against exact saved originals."""
    cutoff = clock(asof)
    if cutoff > datetime.now(timezone.utc):
        raise ContractError("FUTURE_FINANCIAL_ASOF")
    selected = {}
    for version in verify_archive(root)["versions"]:
        if clock(version["available_at"]) <= cutoff:
            key = (version["market"], version["code"], version["fiscal_period"], version["statement"])
            selected[key] = version
    return list(selected.values())


def fetch_original():
    request = Request(SOURCE_URL, headers={"User-Agent": "AlphaMax original financial research",
                                          "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        if response.status != 200 or response.geturl() != SOURCE_URL:
            raise ContractError("UNEXPECTED_FINANCIAL_SOURCE_RESPONSE")
        raw = response.read(MAX_BYTES + 1)
    if len(source_rows(raw)) < 100:
        raise ContractError("FINANCIAL_SOURCE_UNEXPECTEDLY_SPARSE")
    return raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = append_snapshot(args.archive_root, fetch_original())
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        report = {"schema": SCHEMA, "status": "BLOCKED_FINANCIAL_VERSION_CAPTURE",
                  "reason": type(exc).__name__ + ":" + str(exc),
                  "admitted_historical_PIT_batches": 0, "formal_a_plus": False,
                  "buy_signal": False}
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
