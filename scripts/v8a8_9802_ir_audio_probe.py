#!/usr/bin/env python3
"""One-off reachability probe for official TWSE 9802 hosted IR recordings.

HTTP metadata alone cannot prove the video contains an audible Q&A.
This script never claims a recording was listened to or transcribed.
"""
import json
import urllib.request
from urllib.parse import urlsplit

VIDEO_SOURCES={
    "2026-09-17":"https://irconference.twse.com.tw/9802_86_20260917_ch.mp4",
    "2025-11-26":"https://irconference.twse.com.tw/9802_83_20251126_ch.mp4",
    "2025-09-03":"https://irconference.twse.com.tw/9802_82_20250903_ch.mp4",
}

def inspect_source(day,url):
    host=urlsplit(url)
    if not (host.scheme=="https"
            and host.hostname=="irconference.twse.com.tw"
            and host.path.endswith(".mp4")
            and host.path.startswith("/9802_")):
        raise ValueError("Unexpected original recording origin")
    req=urllib.request.Request(url,headers={
        "Range":"bytes=0-65535",
        "User-Agent":"Mozilla/5.0 (compatible; FulgentSunIRReview/1.0)",
        "Accept":"video/mp4,application/octet-stream;q=0.9,*/*;q=0.5",
    })
    try:
        with urllib.request.urlopen(req,timeout=30) as res:
            first=res.read(128)
            mime=res.headers.get("Content-Type","").split(";",1)[0].strip().lower()
            return dict(day=day,remote_url=url,http_status=res.status,
                        content_type=mime,
                        content_length=res.headers.get("Content-Length"),
                        content_range=res.headers.get("Content-Range"),
                        mp4_container_looks_valid=(len(first)>=12 and first[4:8]==b"ftyp"),
                        first_bytes_hex=first[:16].hex(),
                        confirmed_audio_or_QA_recorded=False,
                        source_downloaded_or_transcribed=False)
    except Exception as exc:
        return dict(day=day,remote_url=url,status="DOWNLOAD_UNAVAILABLE",
                    reason=type(exc).__name__+":"+str(exc)[:220],
                    source_downloaded_or_transcribed=False,
                    confirmed_audio_or_QA_recorded=False)

def main():
    records=[inspect_source(d,u) for d,u in VIDEO_SOURCES.items()]
    print(json.dumps(records,ensure_ascii=False,indent=2))
    if not any(r.get("mp4_container_looks_valid") for r in records):
        raise SystemExit("No original playable MP4 source could be reached from runner")

if __name__=="__main__":
    main()
