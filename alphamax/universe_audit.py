"""AlphaMax independent issuer-history coverage audit.

Counts available evidence, *not* a historical listed/delisted security master.
Never infer listing start/end from first/last observed price. All outputs
remain diagnostic until official PIT issuer membership and investor total
returns have independent proofs.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import json
from math import isfinite

from alphamax.core import parse_date, ContractError


def _positive_price(value):
    return type(value) in (float, int) and isfinite(value) and value > 0


def _validate_sessions(content, market, code, current_date):
    sessions = content.get("sessions")
    if not isinstance(sessions, list):
        raise ContractError("MISSING_HISTORICAL_SESSIONS")
    seen = set()
    verified = []
    for entry in sessions:
        if not isinstance(entry, dict):
            raise ContractError("NON_OBJECT_HISTORICAL_SESSION")
        stamp = parse_date(entry.get("date"))
        if stamp > current_date:
            raise ContractError("FUTURE_HISTORICAL_SESSION")
        if stamp in seen:
            raise ContractError("DUPLICATE_HISTORICAL_SESSION_DATE")
        seen.add(stamp)
        if entry.get("code") not in (None, code):
            raise ContractError("HISTORY_CODE_MISMATCH")
        if entry.get("market") not in (None, market):
            raise ContractError("HISTORY_MARKET_MISMATCH")
        if not _positive_price(entry.get("close")):
            raise ContractError("HISTORY_CLOSE_INVALID")
        turnover = entry.get("turnover_ntd")
        if type(turnover) not in (int, float) or not isfinite(turnover) or turnover < 0:
            raise ContractError("HISTORY_TURNOVER_INVALID")
        verified.append(stamp)
    if not verified:
        raise ContractError("EMPTY_HISTORICAL_SESSIONS")
    return len(verified), min(verified).isoformat(), max(verified).isoformat()


def audit_history(root, *, min_sessions=756, max_examples=25):
    """Audit local legacy price records without conferring certification.

    Params:
      root: repository checkout.
      min_sessions: 3 * 252 illustrative observation minimum, not 3 calendar years.
      max_examples: bounded issue samples for stable, small CI artifact.
    """
    if type(min_sessions) is not int or min_sessions < 1:
        raise ContractError("INVALID_MIN_HISTORY")
    if type(max_examples) is not int or max_examples < 0:
        raise ContractError("INVALID_MAX_EXAMPLES")
    root = Path(root)
    manifest_path = root / "tw-market-data/prices/latest_manifest.json"
    if not manifest_path.is_file():
        return {"status": "BLOCKED", "reason": "PRICE_MANIFEST_MISSING"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        asof = parse_date(manifest["date"])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {"status": "BLOCKED", "reason": "PRICE_MANIFEST_INVALID:" + str(exc)}
    snapshot = root / "tw-market-data/prices" / (asof.isoformat() + ".json")
    if not snapshot.is_file():
        return {"status": "BLOCKED", "reason": "MATCHING_PRICE_SNAPSHOT_MISSING"}
    try:
        current = json.loads(snapshot.read_text(encoding="utf-8"))
        if not isinstance(current, list):
            raise ContractError("PRICE_SNAPSHOT_NOT_ARRAY")
        current_keys = set()
        current_unpriced = []
        for row in current:
            if not isinstance(row, dict):
                raise ContractError("PRICE_SNAPSHOT_ROW_NOT_OBJECT")
            market, code = row.get("market"), row.get("code")
            if market not in ("TWSE", "TPEX") or not isinstance(code, str) or not code:
                raise ContractError("PRICE_SNAPSHOT_INVALID_SECURITY")
            if (market, code) in current_keys:
                raise ContractError("PRICE_SNAPSHOT_DUPLICATE_SECURITY")
            if row.get("date") != asof.isoformat():
                raise ContractError("PRICE_SNAPSHOT_INVALID_DATE")
            current_keys.add((market, code))
            # An official quote row may have no valid trade/close. Preserve the
            # observed identity but NEVER turn null/zero into an executable price.
            if not _positive_price(row.get("close")):
                current_unpriced.append(f"{market}:{code}")
    except (ValueError, TypeError, OSError) as exc:
        return {"status": "BLOCKED", "reason": "PRICE_SNAPSHOT_INVALID:" + str(exc)}

    history_dir = root / "tw-market-data/prices/issuer_history"
    files = sorted(history_dir.glob("*/*.json"))
    counts = {
        "history_files": 0, "well_formed_history_files": 0,
        "invalid_history_files": 0, "present_in_snapshot_with_history": 0,
        "history_files_not_in_snapshot": 0, "history_files_ge_252_sessions": 0,
        "history_files_ge_min_sessions": 0,
        "history_files_with_verified_corporate_actions": 0,
        "history_files_with_independent_issuer_pit": 0,
        "history_files_with_verified_tradability": 0,
        "history_files_with_durable_original_receipt": 0,
    }
    missing = set(current_keys)
    invalid = []
    short = []
    unlisted = []
    earliest, latest = None, None
    for path in files:
        counts["history_files"] += 1
        market = path.parent.name
        code = path.stem
        try:
            if market not in ("TWSE", "TPEX"):
                raise ContractError("UNKNOWN_HISTORY_MARKET")
            packet = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(packet, dict):
                raise ContractError("HISTORY_PACKET_NOT_OBJECT")
            if packet.get("issuer") != code or packet.get("market") != market:
                raise ContractError("HISTORY_SECURITY_IDENTITY_MISMATCH")
            n, first, last = _validate_sessions(packet, market, code, asof)
        except (ValueError, TypeError, OSError) as exc:
            counts["invalid_history_files"] += 1
            invalid.append({"security": f"{market}:{code}", "reason": str(exc)})
            continue
        counts["well_formed_history_files"] += 1
        earliest = min(first, earliest) if earliest else first
        latest = max(last, latest) if latest else last
        if n >= 252:
            counts["history_files_ge_252_sessions"] += 1
        if n >= min_sessions:
            counts["history_files_ge_min_sessions"] += 1
        else:
            short.append({"security": f"{market}:{code}", "sessions": n, "first": first, "last": last})
        if (market, code) in current_keys:
            counts["present_in_snapshot_with_history"] += 1
            missing.discard((market, code))
        else:
            counts["history_files_not_in_snapshot"] += 1
            unlisted.append(f"{market}:{code}")
        if packet.get("share_adjusted_history") is True and packet.get("dividend_total_return_verified") is True:
            counts["history_files_with_verified_corporate_actions"] += 1
        if packet.get("issuer_PIT_history_verified") is True and packet.get("official_dated_security_master_receipt"):
            counts["history_files_with_independent_issuer_pit"] += 1
        if packet.get("formal_tradability_gate") == "VERIFIED_EXECUTABLE":
            counts["history_files_with_verified_tradability"] += 1
        if packet.get("original_raw_responses_preserved_in_actions_artifact_not_repository") is False and packet.get("original_receipt_path"):
            receipt = root / packet["original_receipt_path"]
            if receipt.is_file():
                counts["history_files_with_durable_original_receipt"] += 1

    missing_codes = [f"{m}:{c}" for m, c in sorted(missing)]
    return {
        "status": "BLOCKED_NOT_A_PIT_SECURITY_MASTER",
        "asof": asof.isoformat(),
        "current_quote_snapshot_securities": len(current_keys),
        "current_quote_rows_without_positive_close": len(current_unpriced),
        "current_quote_unpriced_sample": sorted(current_unpriced)[:max_examples],
        "min_sessions_target": min_sessions,
        "counts": counts,
        "snapshot_without_well_formed_history": len(missing_codes),
        "snapshot_history_coverage_ratio": round(
            counts["present_in_snapshot_with_history"] / len(current_keys), 6
        ) if current_keys else None,
        "history_first_observation": earliest,
        "history_last_observation": latest,
        "missing_sample": missing_codes[:max_examples],
        "invalid_sample": invalid[:max_examples],
        "short_history_sample": sorted(short, key=lambda x: (x["sessions"], x["security"]))[:max_examples],
        "history_not_in_latest_quote_sample": sorted(unlisted)[:max_examples],
        "blocking_reasons": [
            "CURRENT_QUOTES_DO_NOT_PROVE_PAST_LISTING_OR_DELISTING_MEMBERSHIP",
            "SURVIVORSHIP_BIAS_NOT_EXCLUDED",
            "PRICE_RETURNS_NOT_CORPORATE_ACTION_OR_DIVIDEND_ADJUSTED",
            "FULL_PIT_FILING_VINTAGES_NOT_AUDITED",
            "ORIGINAL_RECEIPTS_AND_EXECUTION_NOT_FORMALLY_AUDITED",
            "TWELVE_MONTH_PREDICTIVE_VALIDATION_NOT_PERFORMED",
        ],
        "notice": (
            "History observations are evidence of observed prices only, never listing/delisting dates. "
            "Coverage counts are not issuer PIT or investor total-return certification. "
            "Snapshot presence is not a tradable fill guarantee; null closes remain non-executable."
        ),
    }
