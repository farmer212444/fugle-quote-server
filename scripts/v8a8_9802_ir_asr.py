#!/usr/bin/env python3
"""Time-coded ASR draft from a TWSE original 9802 IR recording.

This is *not* a verbatim-certified transcript: Mandarin technical names,
speaker attribution, and questionable clauses require manual listening.
Do not label ASR sentences as CEO statements until individual voice ID verified.
The complete, timecoded working copy stays as an ephemeral CI artifact.
"""
import argparse
import datetime
import hashlib
import json
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from v8a8_9802_ir_audio_probe import VIDEO_SOURCES

SCHEMA="V8A8_UNVERIFIED_AUDIO_TRANSCRIPTION_DRAFT"
KEYWORDS=re.compile(
    r"毛利|毛率|新廠|工廠|稼動|產能|產值|訂單|營收|EPS|獲利|工資|原物料|"
    r"關稅|擴廠|稅後|直接人工|工人|成本|恢復|回升|改善|量產|爬坡|"
    r"承諾|保證|庫存|明年|今年|下一季|下半年|2027|2026|2025|法說"
)

def download_mp4(day,output):
    url=VIDEO_SOURCES[day]
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; FulgentSunIRSourceAudit/1.0)",
        "Accept":"video/mp4,application/octet-stream;q=0.9,*/*;q=0.5",
    })
    expected={"2026-09-17":81463384,"2025-09-03":58718487}
    max_bytes=160_000_000
    with urllib.request.urlopen(req,timeout=60) as res:
        if res.status not in (200,206):
            raise ValueError("Unexpected TWSE video response code")
        mime=res.headers.get("Content-Type","").lower()
        if "video/mp4" not in mime and "application/octet-stream" not in mime:
            raise ValueError("Upstream video not MP4")
        total=0
        sha=hashlib.sha256()
        with output.open("wb") as sink:
            while True:
                block=res.read(1024*1024)
                if not block:break
                total+=len(block)
                if total>max_bytes:
                    raise ValueError("Official MP4 source exceeds cautious ASR limit")
                sha.update(block)
                sink.write(block)
    if total!=expected.get(day):
        raise ValueError(f"MP4_SHOULD_NOT_BE_TRUNCATED: {total} expected {expected.get(day)}")
    raw_header=output.open("rb").read(32)
    if raw_header[4:8]!=b"ftyp":
        raise ValueError("Invalid original MP4 container")
    return dict(url=url,downloaded_bytes=total,original_mp4_sha256=sha.hexdigest(),
                downloaded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())


def transcribe(day,model_name,output_dir):
    from faster_whisper import WhisperModel
    output_dir.mkdir(parents=True,exist_ok=True)
    print(f"Official TWSE video session {day}: starting byte retrieval",flush=True)
    mp4=output_dir/"official.mp4"
    source=download_mp4(day,mp4)
    print(f"Confirmed {source['downloaded_bytes']} MP4 bytes from {source['url']}, SHA256={source['original_mp4_sha256']}",flush=True)
    print(f"Loading faster-whisper {model_name} CPU/int8, initial ASR ONLY",flush=True)
    model=WhisperModel(model_name,device="cpu",compute_type="int8",cpu_threads=4,num_workers=2)
    samples,info=model.transcribe(
        str(mp4),language="zh",beam_size=3,condition_on_previous_text=False,
        vad_filter=True,vad_parameters=dict(min_silence_duration_ms=450),
        word_timestamps=False)
    lines=[]
    begun=time.monotonic()
    for i,s in enumerate(samples):
        text=s.text.strip()
        if not text:continue
        row=dict(start_seconds=round(s.start,2),end_seconds=round(s.end,2),
                 text_asr_draft=text,average_log_probability=round(s.avg_logprob,4),
                 no_speech_probability=round(s.no_speech_prob,4),
                 speaker_not_independently_identified=True,original_audio_listening_verified=False)
        lines.append(row)
        if i%35==0:
            print(f"ASR drafted {len(lines)} segments, audio position {s.end:.1f}/{info.duration:.1f}s after {(time.monotonic()-begun):.0f}s CPU",flush=True)
    result=dict(schema=SCHEMA,session_date=day,
        recorded_audio_source=source,model=model_name,asr_engine="faster-whisper",
        language_code_detected=info.language,
        audio_duration_seconds=round(info.duration,2),
        full_original_audio_has_been_manually_listened_to=False,
        raw_ASR_is_not_a_verified_verbatim_record=True,
        person_specific_speaker_identity_verified=False,
        legal_or_issuer_integrity_conclusion="NOT_ASSESSED_ASR_REQUIRES_LISTENING",
        segments=lines)
    draft=output_dir/"asr_timed_workpaper.json"
    draft.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    matches=[j for j,r in enumerate(lines) if KEYWORDS.search(r["text_asr_draft"])]
    snapshots=[]
    last=-999
    for idx in matches:
        row=lines[idx]
        if row["start_seconds"]-last<6:continue
        last=row["start_seconds"]
        low=max(0,idx-1);high=min(len(lines),idx+2)
        snapshots.append(dict(seconds=row["start_seconds"],
                              near_context=" ".join(x["text_asr_draft"] for x in lines[low:high]),
                              original_audio_verification="NOT_DONE"))
    summary=dict(schema="V8A8_ASR_KEYWORD_REVIEW_QUEUE_ONLY",day=day,
                 source_sha256=source["original_mp4_sha256"],
                 duration=info.duration,segments=len(lines),
                 keyword_hits=len(matches),review_windows=snapshots,
                 no_quote_may_be_attributed_to_ceo_without_voice_confirmation=True)
    (output_dir/"qa_keyword_review_queue.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    # Print no full transcript or lengthy protected source verbatim.
    print(json.dumps(dict(
        session=day,duration_seconds=round(info.duration,2),
        original_sha256=source["original_mp4_sha256"],
        ASR_transcribed_segments=len(lines),
        potential_operating_or_margin_claim_windows=len(snapshots),
        draft_workpaper_only=True,
        manual_listening_complete=False),ensure_ascii=False),flush=True)
    mp4.unlink(missing_ok=True)  # never republish original hosted video
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",default="2026-09-17",choices=["2026-09-17","2025-09-03"])
    p.add_argument("--model",default="small")
    p.add_argument("--output",default="temp_9802_ir_draft")
    opts=p.parse_args()
    transcribe(opts.date,opts.model,Path(opts.output))

if __name__=="__main__":
    main()
