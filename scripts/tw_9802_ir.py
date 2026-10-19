#!/usr/bin/env python3
"""9802 IR official-publication watcher. Discovery is NOT an earnings certification."""
import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://www.fulgentsun.com/"
SOURCES = {
    "quarterly": "investors03_2.asp",
    "monthly": "investors03_1.asp",
    "news": "investors04_1.asp",
    "events": "investors05_1.asp",
}
OUT = Path("tw-market-data/issuer/9802")
CAPTURE = Path("market-raw-9802-ir")
DATE_RE = re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(20\d{2})\b")
MAX_BYTES = 12_000_000
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; public-financial-research/1.0)"}

def allowed(url):
    p = urllib.parse.urlparse(url)
    return p.scheme == "https" and p.hostname in ("www.fulgentsun.com", "fulgentsun.com")

def digest(data):
    return hashlib.sha256(data).hexdigest()

def fetch(url):
    if not allowed(url):
        raise ValueError("NON_OFFICIAL_HOST")
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        final = response.geturl()
        if not allowed(final):
            raise ValueError("REDIRECT_TO_NON_OFFICIAL_HOST")
        payload = response.read(MAX_BYTES + 1)
        if not payload or len(payload) > MAX_BYTES:
            raise ValueError("EMPTY_OR_OVERSIZED_RESPONSE")
        return payload, response.headers.get("Content-Type", "")

def decoded(raw):
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("HTML_ENCODING_UNRECOGNIZED")

class Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.parts = None
        self.links = None
        self.active = None
    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.parts, self.links = [], []
        if tag == "a" and self.parts is not None:
            self.active = {"href": dict(attrs).get("href", ""), "parts": []}
    def handle_data(self, value):
        if self.parts is not None:
            self.parts.append(value)
        if self.active is not None:
            self.active["parts"].append(value)
    def handle_endtag(self, tag):
        if tag == "a" and self.active is not None:
            self.links.append({"href": self.active["href"], "title": " ".join(" ".join(self.active["parts"]).split())})
            self.active = None
        if tag == "tr" and self.parts is not None:
            self.rows.append((" ".join(" ".join(self.parts).split()), self.links))
            self.parts, self.links, self.active = None, None, None

def items(category, html):
    parser = Rows()
    parser.feed(html)
    found = {}
    for row, links in parser.rows:
        match = DATE_RE.search(row)
        if not match:
            continue
        month, day, year = map(int, match.groups())
        if year < 2025:
            continue
        try:
            released = dt.date(year, month, day).isoformat()
        except ValueError:
            continue
        for link in links:
            if not link["href"] or not link["title"]:
                continue
            url = urllib.parse.urljoin(BASE + SOURCES[category], link["href"])
            parsed = urllib.parse.urlsplit(url)
            # IR site sometimes publishes PDF paths with literal spaces.
            url = urllib.parse.urlunsplit((
                parsed.scheme, parsed.netloc,
                urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/%()_.-~"),
                urllib.parse.quote(urllib.parse.unquote(parsed.query), safe="=&;%+_.-~"),
                "",
            ))
            if not allowed(url):
                continue
            key = digest(url.encode())[:20]
            found[key] = {
                "id": key, "category": category, "site_display_date": released,
                "title": link["title"], "url": url,
                "individual_MOPS_PIT_verified": False,
            }
    return sorted(found.values(), key=lambda e: (e["site_display_date"], e["title"]), reverse=True)

def q3_early_candidate(item):
    title = item["title"].lower()
    return (item["category"] == "news" and item["site_display_date"].startswith("2026-")
            and any(s in title for s in ("第三季", "3q", "q3"))
            and any(s in title for s in ("財報", "財務", "financial", "results")))

def run(limit):
    OUT.mkdir(parents=True, exist_ok=True)
    CAPTURE.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    old = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    receipts = old.get("receipts", {})
    all_items, errors = [], []
    pages_ok = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for category, path in SOURCES.items():
        try:
            raw, kind = fetch(BASE + path)
            if b"<html" not in raw[:2000].lower() and b"<!doctype" not in raw[:2000].lower():
                raise ValueError("NOT_A_LISTING_HTML")
            found = items(category, decoded(raw))
            if not found:
                raise ValueError("NO_DATED_ISSUER_RECORDS")
            (CAPTURE / ("listing_" + category + ".html")).write_bytes(raw)
            all_items += found
            pages_ok += 1
        except Exception as exc:
            errors.append({"category": category, "error": str(exc)[:180]})
    if pages_ok == 0:
        (CAPTURE / "run_status.json").write_text(
            json.dumps({"captured_at_utc": now, "errors": errors}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        raise RuntimeError("ALL_OFFICIAL_9802_LISTINGS_FAILED")
    # A failed category must not erase previously discovered records.
    # Previous versions stored unescaped spaces from the publisher's hrefs.
    # Drop malformed legacy discoveries; the freshly parsed canonical URL supersedes them.
    existing = {x["id"]: x for x in old.get("discovered", [])
                if " " not in x.get("url", "")}
    for item in all_items:
        existing[item["id"]] = item
    discovered = sorted(existing.values(), key=lambda x: (x["site_display_date"], x["category"], x["id"]), reverse=True)
    changed = []
    # Prioritize previously unseen notices; periodically check newest known URL for corrections.
    newest = {cat: next((x for x in discovered if x["category"] == cat), None) for cat in SOURCES}
    chosen = []
    for x in discovered:
        if x["id"] not in receipts:
            chosen.append(x)
    for x in newest.values():
        if x is not None and all(v["id"] != x["id"] for v in chosen):
            chosen.append(x)
    for item in chosen[:limit]:
        url = item["url"]
        try:
            body, mimetype = fetch(url)
            pdf = body.startswith(b"%PDF-")
            html = b"<html" in body[:2500].lower() or b"<!doctype" in body[:2500].lower()
            if not pdf and not html:
                raise ValueError("DOCUMENT_NOT_HTML_OR_PDF")
            sha = digest(body)
            previous = receipts.get(item["id"], {})
            versions = previous.get("versions", [])
            if not versions or versions[-1]["sha256"] != sha:
                extension = ".pdf" if pdf else ".html"
                (CAPTURE / (item["id"] + "_" + sha[:12] + extension)).write_bytes(body)
                versions.append({
                    "sha256": sha, "bytes": len(body), "mime_type": "application/pdf" if pdf else "text/html",
                    "captured_at_utc": now, "source_url": url,
                    "site_display_date": item["site_display_date"],
                    "issuer_filing_PIT_verified": False,
                })
                changed.append({"id": item["id"], "title": item["title"], "sha256": sha})
            receipts[item["id"]] = {"versions": versions}
        except Exception as exc:
            errors.append({"document": item["id"], "url": url, "error": str(exc)[:180]})
    candidate = [x for x in discovered if q3_early_candidate(x)]
    new_manifest = {
        "format_version": 1, "issuer": "9802", "publisher": "鈺齊國際",
        "sources": {k: BASE + v for k, v in SOURCES.items()},
        "discovered": discovered, "receipts": receipts,
        "early_2026_q3_status": "IR_Q3_RELEASE_CANDIDATE_REQUIRES_NUMERIC_MOPS_VERIFICATION"
        if candidate else "WAITING_OFFICIAL_IR_Q3_EARNINGS_RELEASE",
        "early_2026_q3_candidate_urls": [x["url"] for x in candidate],
        "formal_Aplus_certified": False, "official_issuer_PIT_verified": False,
        "limitations": "IR display date is not a verified MOPS issuer filing timestamp. No EPS, GM, PE or A+ gate is changed. Source bytes in Actions artifacts expire; durable manifest stores hashes and URLs.",
    }
    new_text = json.dumps(new_manifest, ensure_ascii=False, indent=2) + "\n"
    if not manifest_path.exists() or manifest_path.read_text("utf-8") != new_text:
        manifest_path.write_text(new_text, encoding="utf-8")
    status = {
        "captured_at_utc": now, "pages_succeeded": pages_ok, "pages_total": len(SOURCES),
        "discovered": len(discovered), "documents_captured_or_updated": changed,
        "errors": errors, "q3_status": new_manifest["early_2026_q3_status"],
        "automatic_valuation_modified": False,
    }
    (CAPTURE / "run_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0

def self_test():
    snippet = ('<table><tr><td>10/19/2026</td><td><a href="img/Finance/115Q3.pdf">'
               '2026年第三季合併財務報告</a></td></tr>'
               '<tr><td>10/08/2026</td><td><a href="investors04_1_1.asp?seq=42">'
               '2026年9月營收新聞稿</a></td></tr></table>')
    q = items("quarterly", snippet)
    assert len(q) == 2
    assert "img/Finance/115Q3.pdf" in q[0]["url"]
    assert not q3_early_candidate(q[0])
    n = items("news", '<tr><td>10/19/2026</td><td><a href="ir.asp?seq=1">2026年第三季自結財報新聞稿</a></td></tr>')
    assert q3_early_candidate(n[0])
    assert not allowed("https://example.org/bad.pdf")
    spaced = items("news", '<tr><td>10/19/2026</td><td><a href="img/News_Release/My PDF_CN(1).pdf">test</a></td></tr>')
    assert "%20" in spaced[0]["url"] and " " not in spaced[0]["url"]
    print("SELF_TEST_OK")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-docs", type=int, default=6)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        sys.exit(run(max(1, min(25, args.max_docs))))
