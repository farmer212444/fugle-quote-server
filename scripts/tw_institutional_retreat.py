"""Fail-closed institutional retreat research alert.

Only dated, hash-receipted 20-session exchange trust flows and an eligible
official issued-share master can trigger an OBSERVED_REVIEW signal.
Not a forecast, insider-information inference, certified A+ gate, or Exit.
"""
import datetime as dt
import gzip
import hashlib
import json
import re
from pathlib import Path

SELL_FRACTION_NUMERATOR = 3
SELL_FRACTION_DENOMINATOR = 1000  # 0.30% of issued ordinary shares


def _date(text):
    digits = re.sub(r"\D", "", str(text))
    if len(digits) == 7:
        digits = str(1911 + int(digits[:3])) + digits[3:]
    if len(digits) != 8:
        raise ValueError("INVALID_SHARE_MASTER_DATE")
    return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()


def _timestamp(text):
    d = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("UNDATED_OR_NAIVE_EVIDENCE_TIMESTAMP")
    return d.astimezone(dt.timezone.utc)


def load_issued_shares(data_root, asof):
    """Load validated *snapshot* denominators without time-travel or guesswork.

    Receipt/hash checks establish reproducibility only, NOT official origin/PIT
    certification. Absence or corruption returns a source error, never zeros.
    """
    root = Path(data_root).resolve()
    manifest_path = root / "evidence/v880/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = Path(manifest["path"])
    snapshot_path = (root / relative).resolve()
    if not snapshot_path.is_relative_to(root) or not snapshot_path.is_file():
        raise ValueError("INVALID_EVIDENCE_SNAPSHOT_PATH")
    packed = snapshot_path.read_bytes()
    if hashlib.sha256(packed).hexdigest() != manifest["gzip_sha256"]:
        raise ValueError("SHARE_SNAPSHOT_ARCHIVE_HASH_MISMATCH")
    raw = gzip.decompress(packed)
    if hashlib.sha256(raw).hexdigest() != manifest["json_sha256"]:
        raise ValueError("SHARE_SNAPSHOT_CONTENT_HASH_MISMATCH")
    snapshot = json.loads(raw)
    # Never attach shares first seen after the reference day's close to a
    # historical price-day signal. No retrospective/backfilled trade alerts.
    cutoff = dt.datetime.combine(
        dt.date.fromisoformat(asof), dt.time(23, 59, 59),
        tzinfo=dt.timezone(dt.timedelta(hours=8))
    ).astimezone(dt.timezone.utc)
    for timestamp in (manifest["available_at"], snapshot["snapshot_available_at"]):
        if _timestamp(timestamp) > cutoff:
            raise ValueError("SHARE_SNAPSHOT_NOT_AVAILABLE_AT_PRICE_DATE")
    masters = snapshot.get("master")
    if not isinstance(masters, dict):
        raise ValueError("SHARE_MASTER_MISSING_FROM_SNAPSHOT")
    result = {}
    for code, record in masters.items():
        code = str(code)
        if not re.fullmatch(r"\d{4}", code) or not isinstance(record, dict):
            continue
        market = record.get("market")
        if market not in ("TWSE", "TPEX"):
            continue
        try:
            source_date = _date(record.get("date"))
            shares = record.get("issued_shares")
            if (source_date > asof or not isinstance(shares, int)
                    or isinstance(shares, bool) or shares <= 0):
                continue
        except (TypeError, ValueError):
            continue
        key = (market, code)
        if key in result:
            raise ValueError("DUPLICATE_ISSUER_SHARE_ID")
        result[key] = {"issued_shares": shares, "source_date": source_date,
                       "receipt_hash": manifest["json_sha256"]}
    if not result:
        raise ValueError("NO_ELIGIBLE_DATED_ISSUED_SHARE_DENOMINATORS")
    return result


def assess_retreat(flow20, shares):
    """20 observed dated snapshots; trust activity only; no fake zero fills."""
    base = dict(
        status="PENDING_20_SESSION_EVIDENCE",
        threshold_issued_share_pct=0.3,
        trust_net_shares_20d=None,
        issued_shares=None,
        trust_net_20d_pct_issued_shares=None,
        warning_not_trade_instruction=True,
        fundamental_confirmation="NOT_ASSESSED",
        auto_exit=False,
        formal_rating_changed=False,
    )
    if not flow20 or flow20.get("sessions") != 20:
        return base
    trust = flow20.get("trust_net_shares")
    if not isinstance(trust, int) or isinstance(trust, bool):
        return {**base, "status": "PENDING_INVALID_FLOW_UNITS"}
    if not shares:
        return {**base, "status": "PENDING_DATED_ISSUED_SHARE_DENOMINATOR"}
    denominator = shares.get("issued_shares")
    if not isinstance(denominator, int) or isinstance(denominator, bool) or denominator <= 0:
        return {**base, "status": "PENDING_INVALID_SHARE_DENOMINATOR"}
    crossed = trust * SELL_FRACTION_DENOMINATOR <= -SELL_FRACTION_NUMERATOR * denominator
    return {
        **base,
        "status": "OBSERVED_RETREAT_REQUIRES_FUNDAMENTAL_REVIEW" if crossed
                  else "OBSERVED_NO_THRESHOLD_BREACH",
        "trust_net_shares_20d": trust,
        "issued_shares": denominator,
        "share_master_date": shares["source_date"],
        "share_master_receipt_hash": shares["receipt_hash"],
        "trust_net_20d_pct_issued_shares": round(100 * trust / denominator, 5),
        "observation_start": flow20["first_session"],
        "observation_end": flow20["last_session"],
        "observed_sessions": 20,
        "complete_trading_calendar_independently_certified": False,
        "fundamental_confirmation": "REQUIRES_SEPARATE_PIT_ACCOUNTING_EVIDENCE",
    }
