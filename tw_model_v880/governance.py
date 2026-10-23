"""Source-backed governance events, with prospective capture clocks.

An indictment is not a conviction, and an alleged loss is not a new expense.
Open material events reopen existing management/auditor review obligations;
they never manufacture an EPS charge, PE haircut or fourteenth quality gate.
The event register is not a complete market-wide legal clearance service.
"""
import copy
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from .evidence import gate, timestamp

SCHEMA = "ISSUER_GOVERNANCE_EVENTS_V1"
BLOCK = "MATERIAL_GOVERNANCE_REVIEW_REQUIRED"
INVALID = "GOVERNANCE_SOURCE_INVALID_REVIEW_REQUIRED"
COVERAGE = "REGISTERED_EVENTS_ONLY_NOT_FULL_MARKET_LEGAL_CLEARANCE"
REOPEN_GATES = ("management_promises", "auditor_scope")
CLOSURE_CHECKS = ("legal_disposition_review_complete", "accounting_effect_review_complete",
                  "internal_controls_review_complete", "minority_shareholder_remedy_review_complete")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


class SourceText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


def verify_source(root, source, checked, issuer_domains):
    """Check captured original bytes and documented issuer identity markers."""
    require(isinstance(source, dict), "GOVERNANCE_SOURCE_INVALID")
    parsed = urlparse(source.get("url", ""))
    host = parsed.hostname or ""
    official = host.endswith(".gov.tw") or host in ("mops.twse.com.tw", "mopsov.twse.com.tw", "www.twse.com.tw", "www.tpex.org.tw")
    issuer = any(host == domain or host.endswith("." + domain) for domain in issuer_domains)
    require(parsed.scheme == "https" and not parsed.username and (official or issuer),
            "GOVERNANCE_SOURCE_ORIGIN_NOT_ALLOWED")
    require(source.get("origin_identity_reviewed") is True and source.get("http_status") == 200,
            "GOVERNANCE_SOURCE_IDENTITY_NOT_REVIEWED")
    require(timestamp(source["available_at"]) <= timestamp(source["captured_at_utc"]) <= checked,
            "GOVERNANCE_SOURCE_CLOCK_INVALID")
    rel = Path(source["archive_path"])
    path = (root / rel).resolve()
    require(not rel.is_absolute() and ".." not in rel.parts and root in path.parents,
            "GOVERNANCE_ARCHIVE_PATH_UNSAFE")
    raw = path.read_bytes()
    require(re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", "")) is not None
            and hashlib.sha256(raw).hexdigest() == source["sha256"], "GOVERNANCE_SOURCE_HASH_MISMATCH")
    markers = source.get("required_text_markers")
    require(isinstance(markers, list) and markers and all(isinstance(x, str) and x.strip() for x in markers),
            "GOVERNANCE_SOURCE_IDENTITY_MARKERS_MISSING")
    parser = SourceText()
    parser.feed(raw.decode("utf-8"))
    compact = re.sub(r"\s+", "", " ".join(parser.parts))
    require(all(re.sub(r"\s+", "", marker) in compact for marker in markers),
            "GOVERNANCE_SOURCE_IDENTITY_MARKER_MISMATCH")
    if source.get("role") == "official_disposition":
        require(official, "GOVERNANCE_DISPOSITION_REQUIRES_OFFICIAL_ORIGIN")
    return dict(path=rel.as_posix(), sha256=source["sha256"],
                meaning="GOVERNANCE_ORIGINAL_BYTES_IDENTITY_REVIEWED_NOT_A_JUDICIAL_FINDING")


def evaluate_document(root, code, document, asof):
    root = Path(root).resolve()
    cut = timestamp(asof)
    require(document.get("schema") == SCHEMA and document.get("code") == code,
            "GOVERNANCE_LEDGER_IDENTITY_MISMATCH")
    require(document.get("market") in ("TWSE", "TPEX"), "GOVERNANCE_LEDGER_MARKET_INVALID")
    domains = document.get("issuer_domains")
    require(isinstance(domains, list) and domains and all(
        isinstance(x, str) and re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", x) for x in domains),
        "GOVERNANCE_ISSUER_DOMAINS_INVALID")
    events = document.get("events")
    require(isinstance(events, list) and events, "GOVERNANCE_EVENTS_MISSING")
    seen, active, receipts = set(), [], []
    for event in events:
        event_id = event["event_id"]
        require(isinstance(event_id, str) and event_id and event_id not in seen,
                "GOVERNANCE_DUPLICATE_OR_INVALID_EVENT")
        seen.add(event_id)
        require(event.get("materiality") in ("MAJOR", "OTHER"), "GOVERNANCE_MATERIALITY_UNKNOWN")
        updates = event.get("updates")
        require(isinstance(updates, list) and updates, "GOVERNANCE_EVENT_UPDATES_MISSING")
        latest, previous = None, None
        for update in updates:
            recorded = timestamp(update["first_recorded_at"])
            checked = timestamp(update["checked_at"])
            available = timestamp(update["available_at"])
            require(available <= recorded <= checked, "GOVERNANCE_UPDATE_CLOCK_INVALID")
            require(previous is None or recorded > previous, "GOVERNANCE_UPDATES_NOT_APPEND_ORDERED")
            previous = recorded
            # Today's capture cannot be used to improve a historical live signal.
            if checked > cut:
                continue
            require(update.get("status") in ("OPEN_REVIEW_REQUIRED", "CLOSED_REVIEWED"),
                    "GOVERNANCE_EVENT_STATUS_UNKNOWN")
            require(isinstance(update.get("reviewed_by"), str) and update["reviewed_by"].strip(),
                    "GOVERNANCE_REVIEWER_MISSING")
            sources = update.get("sources")
            require(isinstance(sources, list) and sources, "GOVERNANCE_EVENT_SOURCES_MISSING")
            for source in sources:
                receipts.append(verify_source(root, source, checked, domains))
            if update["status"] == "CLOSED_REVIEWED":
                require(all(update.get(name) is True for name in CLOSURE_CHECKS)
                        and any(s.get("role") == "official_disposition" for s in sources),
                        "GOVERNANCE_CLOSURE_NOT_SUBSTANTIATED")
            latest = update
        if latest is not None:
            active.append(dict(event_id=event_id, category=event.get("category"),
                materiality=event["materiality"], summary=event.get("summary"),
                status=latest["status"], legal_stage=latest.get("legal_stage"),
                first_recorded_at=updates[0]["first_recorded_at"], checked_at=latest["checked_at"],
                available_at=latest["available_at"], sources=latest["sources"],
                alleged_loss_ntd=event.get("alleged_loss_ntd"),
                alleged_loss_is_not_current_period_expense=True,
                conviction_not_inferred=True, next_evidence=event.get("next_evidence", [])))
    if not active:
        return None
    open_ids = [x["event_id"] for x in active if x["materiality"] == "MAJOR" and x["status"] == "OPEN_REVIEW_REQUIRED"]
    return dict(schema=SCHEMA, code=code, market=document["market"], coverage=COVERAGE,
                status=BLOCK if open_ids else "REGISTERED_EVENTS_NO_OPEN_MATERIAL_REVIEW",
                blocks_recommendation=bool(open_ids), material_open_event_ids=open_ids,
                events=active, source_receipts=receipts,
                eps_pe_unchanged=True, judicial_guilt_not_determined=True)


def load_governance_reviews(root, asof):
    root = Path(root).resolve()
    reviews, errors, receipts = {}, [], []
    for path in sorted((root / "evidence/v880/governance").glob("[0-9]*.json")):
        code = path.stem
        receipts.append(dict(path=path.relative_to(root).as_posix(),
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             meaning="DATED_GOVERNANCE_EVENT_REGISTER_NOT_FULL_MARKET_CLEARANCE"))
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            review = evaluate_document(root, code, document, asof)
            if review is not None:
                reviews[code] = review
                receipts.extend(review["source_receipts"])
        except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
            # A damaged registered case never disappears as a clean issuer.
            reviews[code] = dict(schema=SCHEMA, code=code, status=INVALID, coverage=COVERAGE,
                                 blocks_recommendation=True, material_open_event_ids=[],
                                 events=[], reason=str(exc), eps_pe_unchanged=True)
            errors.append(dict(source=path.relative_to(root).as_posix(), error=str(exc)))
    return reviews, errors, receipts


def issuer_review(reviews, code, market):
    review = copy.deepcopy(reviews.get(code))
    if review is None:
        return dict(status="NO_EVENT_LEDGER_NOT_LEGAL_CLEARANCE", coverage=COVERAGE,
                    blocks_recommendation=False, material_open_event_ids=[], events=[])
    if review.get("market") not in (None, market):
        review.update(status=INVALID, blocks_recommendation=True, reason="GOVERNANCE_MARKET_MISMATCH")
    return review


def reopen_quality_reviews(gates, review):
    """Keep all 13 obligations; preserve any existing documented FAIL."""
    blocked = review.get("blocks_recommendation") is True
    closed = [e for e in review.get('events', [])
              if e.get('materiality') == 'MAJOR' and e.get('status') == 'CLOSED_REVIEWED']
    if not blocked and not closed:
        return gates
    result = copy.deepcopy(gates)
    for name in REOPEN_GATES:
        prior = result.get(name, {})
        if prior.get('status') == 'FAIL':
            continue
        if not blocked:
            try:
                fresh = (prior.get('status') == 'PASS'
                         and all(timestamp(prior['checked_at']) >= timestamp(e['checked_at'])
                                 and e['event_id'] in prior.get('governance_event_ids', []) for e in closed))
            except (KeyError, TypeError, ValueError, AttributeError):
                fresh = False
            if fresh:
                continue
        if blocked or prior.get('status') == 'PASS':
            result[name] = gate("PENDING", review["status"] if blocked else 'GOVERNANCE_CLOSURE_REQUIRES_GATE_REVIEW',
                                governance_event_ids=review.get("material_open_event_ids", []),
                                prior_gate_status=prior.get("status"))
    return result
