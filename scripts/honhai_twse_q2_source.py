#!/usr/bin/env python3
"""Strict official TWSE electronic-document retrieval for 2317 2026-Q2.

No guessed PDF URL. The signed official listing identifies an exact filename,
its byte count and company/quarter. Download resolution stays within doc.twse,
with session cookies. The caller must archive both HTML provenance pages and
the PDF itself and must not convert this to any formal quality PASS.
"""
import http.cookiejar
import re
import urllib.parse
import urllib.request

INDEX_URL = ("https://doc.twse.com.tw/server-java/t57sb01"
             "?co_id=2317&colorchg=1&mtype=A&step=1&year=115")
FORM_URL = "https://doc.twse.com.tw/server-java/t57sb01"
FILENAME = "202602_2317_AI1.pdf"
EXPECTED_BYTES = 4_018_369
MAX_HTML_BYTES = 2_000_000
PREFIX = "https://doc.twse.com.tw"
PDF_HREF_RE = re.compile(
    rb'href\s*=\s*["\x27](/pdf/202602_2317_AI1_[0-9]{8}_[0-9]{6}\.pdf)["\x27]',
    re.I,
)

def extract_pdf_url(index, resolver):
    if not isinstance(index, bytes) or not isinstance(resolver, bytes):
        raise ValueError("TWSE_LISTING_OR_RESOLVER_BYTES_REQUIRED")
    # The name must come from the issuer's actual TWSE listing, never a
    # filename extrapolated from a neighboring issuer or quarter.
    if (FILENAME.encode("ascii") not in index
            or b"2317" not in index
            or b"202602" not in index):
        raise ValueError("TWSE_2317_2026Q2_FILE_NOT_IN_OFFICIAL_LISTING")
    links=set(PDF_HREF_RE.findall(resolver))
    if len(links)!=1:
        raise ValueError("TWSE_2317_2026Q2_RESOLVED_PDF_LINK_AMBIGUOUS_OR_MISSING")
    return PREFIX+next(iter(links)).decode("ascii")

def _get(opener, request, expected_url, cap):
    with opener.open(request,timeout=30) as response:
        if response.status!=200 or response.geturl()!=expected_url:
            raise ValueError("TWSE_ELECTRONIC_SOURCE_HTTP_OR_REDIRECT_INVALID")
        raw=response.read(cap+1)
    if not 10<len(raw)<=cap:
        raise ValueError("TWSE_ELECTRONIC_SOURCE_EMPTY_OR_OVERSIZED")
    return raw

def download(*,opener=None):
    if opener is None:
        opener=urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    hdr={"User-Agent":"Mozilla/5.0 (official issuer-original archive)"}
    index=_get(opener,urllib.request.Request(INDEX_URL,headers=hdr),
               INDEX_URL,MAX_HTML_BYTES)
    # Do not POST an unchecked filename to the resolution endpoint.
    if FILENAME.encode("ascii") not in index or b"2317" not in index:
        raise ValueError("TWSE_2317_2026Q2_LISTING_REJECTED")
    payload=urllib.parse.urlencode(dict(step="9",kind="A",co_id="2317",
                                         filename=FILENAME)).encode("ascii")
    form_headers=dict(hdr,Referer=INDEX_URL)
    form_headers["Content-Type"]="application/x-www-form-urlencoded"
    resolver=_get(opener,urllib.request.Request(
        FORM_URL,data=payload,headers=form_headers,method="POST"),
        FORM_URL,MAX_HTML_BYTES)
    pdf_url=extract_pdf_url(index,resolver)
    pdf=_get(opener,urllib.request.Request(
        pdf_url,headers=dict(hdr,Referer=FORM_URL)),
        pdf_url,EXPECTED_BYTES)
    if len(pdf)!=EXPECTED_BYTES:
        raise ValueError("TWSE_2317_2026Q2_OFFICIAL_PDF_SIZE_MISMATCH")
    return pdf,dict(index_bytes=index,resolution_bytes=resolver,
                    resolved_pdf_url=pdf_url)

def provenance_from_bytes(index,resolver,pdf_url):
    expected=extract_pdf_url(index,resolver)
    if pdf_url!=expected:
        raise ValueError("TWSE_RESOLVED_PDF_PROVENANCE_MISMATCH")
    return dict(official_index_url=INDEX_URL,official_filename=FILENAME,
                expected_bytes=EXPECTED_BYTES,resolved_pdf_url=pdf_url)
