"""Append-only, source-bound binary forecasts. Never emits trading signals."""
import datetime as dt
import hashlib
import json
import math
import os
import re
import statistics
from pathlib import Path

from .experiments import calibration_summary

SCHEMA = "SUPERFORECAST_PREISSUED_V1"
HEX = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,79}$")
TAIPEI = dt.timezone(dt.timedelta(hours=8))


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def parse_time(value):
    when = dt.datetime.fromisoformat(value)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP_FORBIDDEN")
    return when.astimezone(dt.timezone.utc)


def clock(now=None):
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("NAIVE_CLOCK")
    return value.astimezone(dt.timezone.utc)


def root_dir(root):
    return Path(root).resolve() / "experiments" / "superforecast_v1"


def source_check(root, evidence):
    if not isinstance(evidence, dict):
        raise ValueError("MISSING_SOURCE_EVIDENCE")
    name, expected = evidence.get("path"), evidence.get("sha256")
    if not isinstance(name, str) or not isinstance(expected, str) or not HEX.fullmatch(expected):
        raise ValueError("INVALID_SOURCE_IDENTITY")
    base = Path(root).resolve()
    candidate = (base / name).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        raise ValueError("SOURCE_OUTSIDE_ROOT_OR_MISSING")
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
        raise ValueError("SOURCE_HASH_MISMATCH")


def probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("INVALID_PROBABILITY")
    return float(value)


def issued_identity(spec):
    fid = spec.get("forecast_id")
    if not isinstance(fid, str) or not IDENTIFIER.fullmatch(fid):
        raise ValueError("INVALID_FORECAST_ID")
    if (not isinstance(spec.get("market"), str) or not spec["market"].strip()
            or not isinstance(spec.get("code"), str) or not spec["code"].strip()
            or not isinstance(spec.get("event_definition"), str) or len(spec["event_definition"].strip()) < 12):
        raise ValueError("EVENT_NOT_PRECISELY_DEFINED")
    if not isinstance(spec.get("model_method_sha256"), str) or not HEX.fullmatch(spec["model_method_sha256"]):
        raise ValueError("MISSING_MODEL_METHOD_HASH")
    return fid


def write_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(blob)
    return data


def issue(root, spec, *, now=None):
    """Actual issue clock is recorded by the runner, never supplied in spec."""
    when = clock(now)
    fid = issued_identity(spec)
    due = dt.date.fromisoformat(spec["event_due_date"])
    if due <= when.astimezone(TAIPEI).date():
        raise ValueError("FORECAST_MUST_PRECEDE_DUE_DATE")
    p = probability(spec["probability"])
    source_check(root, spec.get("evidence"))
    baseline = spec.get("baseline_probability")
    baseline_proof = spec.get("baseline_evidence")
    if (baseline is None) != (baseline_proof is None):
        raise ValueError("BASELINE_REQUIRES_PROVENANCE")
    if baseline is not None:
        baseline = probability(baseline)
        source_check(root, baseline_proof)
    record = dict(schema=SCHEMA, forecast_id=fid, market=spec["market"].strip(),
                  code=spec["code"].strip(), event_definition=spec["event_definition"].strip(),
                  event_due_date=due.isoformat(), probability=p,
                  baseline_probability=baseline, baseline_evidence=baseline_proof,
                  model_method_sha256=spec["model_method_sha256"],
                  evidence=spec["evidence"], issued_at_utc=when.isoformat(),
                  does_not_certify_original_publication_time=True)
    record["record_sha256"] = digest(record)
    return write_once(root_dir(root) / "issued" / (fid + ".json"), record)


def resolve(root, spec, *, now=None):
    """Resolution is immutable and cannot be registered before the due date."""
    when = clock(now)
    fid = spec.get("forecast_id")
    if not isinstance(fid, str) or not IDENTIFIER.fullmatch(fid):
        raise ValueError("INVALID_FORECAST_ID")
    issued = read_record(root_dir(root) / "issued" / (fid + ".json"))
    validate_issue(root, issued, fid)
    if when.astimezone(TAIPEI).date() < dt.date.fromisoformat(issued["event_due_date"]):
        raise ValueError("EVENT_NOT_YET_DUE")
    if when <= parse_time(issued["issued_at_utc"]):
        raise ValueError("OUTCOME_PRECEDES_FORECAST")
    outcome = spec.get("outcome")
    if type(outcome) is not bool:
        raise ValueError("OUTCOME_MUST_BE_BOOLEAN")
    source_check(root, spec.get("verification_evidence"))
    record = dict(schema=SCHEMA, forecast_id=fid, issued_sha256=issued["record_sha256"],
                  outcome=outcome, verified_at_utc=when.isoformat(),
                  verification_evidence=spec["verification_evidence"],
                  evidence_hash_verified_not_independent_adjudication=True)
    record["record_sha256"] = digest(record)
    return write_once(root_dir(root) / "resolved" / (fid + ".json"), record)


def read_record(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("INVALID_LEDGER_OBJECT")
    given = obj.get("record_sha256")
    body = {k: v for k, v in obj.items() if k != "record_sha256"}
    if not isinstance(given, str) or digest(body) != given:
        raise ValueError("LEDGER_RECORD_HASH_MISMATCH")
    return obj


def validate_issue(root, row, fid):
    if row.get("schema") != SCHEMA or row.get("forecast_id") != fid:
        raise ValueError("ISSUANCE_IDENTITY_MISMATCH")
    issued_identity(row)
    probability(row.get("probability"))
    due = dt.date.fromisoformat(row["event_due_date"])
    issued_at = parse_time(row["issued_at_utc"])
    if due <= issued_at.astimezone(TAIPEI).date():
        raise ValueError("RETROACTIVE_FORECAST")
    source_check(root, row.get("evidence"))
    b = row.get("baseline_probability")
    proof = row.get("baseline_evidence")
    if (b is None) != (proof is None):
        raise ValueError("BASELINE_REQUIRES_PROVENANCE")
    if b is not None:
        probability(b)
        source_check(root, proof)


def validate_resolve(root, row, issued):
    if (row.get("schema") != SCHEMA or row.get("forecast_id") != issued["forecast_id"]
            or row.get("issued_sha256") != issued["record_sha256"]):
        raise ValueError("RESOLUTION_ISSUE_MISMATCH")
    if type(row.get("outcome")) is not bool:
        raise ValueError("INVALID_BOOLEAN_OUTCOME")
    ended = parse_time(row["verified_at_utc"])
    if ended <= parse_time(issued["issued_at_utc"]) or ended.astimezone(TAIPEI).date() < dt.date.fromisoformat(issued["event_due_date"]):
        raise ValueError("OUTCOME_UNDERMINES_PIT")
    source_check(root, row.get("verification_evidence"))


def report(root, *, asof=None, minimum=100):
    """Read-only as-of scoring. Reject entire ledger if any record is corrupt."""
    cutoff = clock(asof)
    folder = root_dir(root)
    issued_files = sorted((folder / "issued").glob("*.json"))
    resolved_files = sorted((folder / "resolved").glob("*.json"))
    try:
        issuances = {}
        for path in issued_files:
            row = read_record(path)
            validate_issue(root, row, path.stem)
            issuances[path.stem] = row
        resolutions = {}
        for path in resolved_files:
            row = read_record(path)
            if path.stem not in issuances:
                raise ValueError("ORPHAN_RESOLUTION")
            validate_resolve(root, row, issuances[path.stem])
            resolutions[path.stem] = row
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return dict(schema=SCHEMA, status="LEDGER_REJECTED", reason=str(exc),
                    issued_count=len(issued_files), resolved_count=0, scored_count=0,
                    brier_score=None, baseline_brier_score=None, brier_skill_score=None,
                    promotes_Aplus=False, investment_outperformance_proven=False)
    scores = []
    baselines = []
    awaiting = 0
    for fid, issued in issuances.items():
        issue_at = parse_time(issued["issued_at_utc"])
        if issue_at > cutoff:
            continue
        resolved = resolutions.get(fid)
        if resolved is None or parse_time(resolved["verified_at_utc"]) > cutoff:
            if dt.date.fromisoformat(issued["event_due_date"]) <= cutoff.astimezone(TAIPEI).date():
                awaiting += 1
            continue
        row = dict(sample_id=fid, predicted_probability=issued["probability"],
                   probability_issued_at=issued["issued_at_utc"],
                   outcome=resolved["outcome"], outcome_at=resolved["verified_at_utc"])
        scores.append(row)
        if issued["baseline_probability"] is not None:
            baselines.append((issued["probability"], issued["baseline_probability"], int(resolved["outcome"])))
    diagnostics = calibration_summary(scores, min_samples=minimum)
    baseline = None
    skill = None
    if len(scores) >= minimum and len(baselines) == len(scores):
        brier = diagnostics["brier_score"]
        baseline = statistics.fmean((b-y)**2 for _, b, y in baselines)
        skill = 1-brier/baseline if baseline > 0 else None
    return dict(schema=SCHEMA, status=diagnostics["status"],
                issued_count=sum(parse_time(v["issued_at_utc"]) <= cutoff for v in issuances.values()),
                resolved_count=len(scores), awaiting_evidence_count=awaiting, scored_count=len(scores),
                minimum_scored_events=minimum, brier_score=diagnostics.get("brier_score"),
                reliability_bins=diagnostics.get("reliability_bins", []),
                baseline_brier_score=baseline, brier_skill_score=skill,
                baseline_comparison_status=("MATCHED_BASELINE_COMPARISON" if baseline is not None
                                            else "NOT_ENOUGH_MATCHED_PREISSUED_BASELINES"),
                source_validation="REPOSITORY_BYTES_SHA256_ONLY_NOT_EXTERNAL_TIMESTAMP_ATTESTATION",
                independent_outcome_adjudication=False,
                forecasts_not_auto_invented=True, promotes_Aplus=False,
                investment_outperformance_proven=False)
