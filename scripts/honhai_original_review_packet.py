#!/usr/bin/env python3
"""Read-only SHA-proven auditor review locator for 2317, NEVER formal A+."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from scripts.honhai_original_statements import MANIFEST, safe, validate_archive, window
from scripts.v891_gate_certification import write_if_changed

SCHEMA="HONHAI_2317_AUDITOR_REVIEW_PREP_V1"
KEYWORDS=("保留結論","保留意見","強調事項","其他事項",
          "未經會計師核閱","未經會計師查核","非重要子公司","權益法")
MAX_PAGES=20
MAX_HITS=18

def auditor_leads(pdf_path):
    """Find citation pages only; words are NOT auditor opinion findings."""
    import fitz
    hits=[]
    readable=0
    with fitz.open(pdf_path) as doc:
        scanned=min(len(doc),MAX_PAGES)
        for index in range(scanned):
            body=re.sub(r"\s+","",doc[index].get_text())
            if len(body)>=30:
                readable+=1
            for word in KEYWORDS:
                for found in re.finditer(re.escape(word),body):
                    if len(hits)<MAX_HITS:
                        hits.append(dict(pdf_page_1based=index+1,keyword=word,
                            text_lead=body[max(0,found.start()-25):min(len(body),found.end()+45)],
                            formal_scope_conclusion=None))
    return dict(pages_scanned=scanned,pages_with_readable_text=readable,
                keyword_leads=hits,keyword_leads_may_be_truncated=len(hits)>=MAX_HITS,
                complete_notes_reviewed=False,formal_auditor_opinion_reviewed=False)

def build_packet(root,last_quarter,asof):
    root=Path(root).resolve()
    archive=validate_archive(root,last_quarter,asof)
    manifest=safe(root,MANIFEST)
    sha=hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else None
    documented={d["period"]:d for d in archive["documents"]}
    rows=[]
    for period in window(last_quarter):
        doc=documented.get(period)
        if doc is None:
            rows.append(dict(period=period,archive_state="NOT_SHA_VERIFIED",
                             sha256=None,source_url=None,archive_path=None,
                             auditor_leads=None,publication_PIT_verified=False,
                             formal_gate_pass=False))
            continue
        # validate_archive strictly rehashes PDF bytes and TWSE proof bytes.
        clues=auditor_leads(safe(root,doc["archive_path"]))
        rows.append(dict(period=period,archive_state="SHA_REHASHED",
                         sha256=doc["sha256"],source_url=doc["source_url"],
                         archive_path=doc["archive_path"],
                         captured_at_utc=doc["captured_at_utc"],
                         twse_provenance_reverified=period=="2026-Q2"
                             and bool(doc.get("twse_provenance")),
                         pdf_page_count=doc["pdf_identity"]["page_count"],
                         auditor_leads=clues,publication_PIT_verified=False,
                         formal_gate_pass=False))
    if archive["coverage"] is None:
        coverage=dict(status="UNKNOWN_NO_MANIFEST",archived_count=None,required_count=8)
    else:
        c=archive["coverage"]
        coverage=dict(status=("EIGHT_ORIGINALS_REHASHED" if len(c["found_quarters"])==8
                              else "PARTIAL_ORIGINALS_REHASHED"),
                      archived_count=len(c["found_quarters"]),
                      required_count=len(c["required_quarters"]),
                      missing_quarters=list(c["missing_quarters"]))
    return dict(schema=SCHEMA,issuer="2317",financial_period=last_quarter,
                research_cutoff=asof,source_manifest_sha256=sha,coverage=coverage,
                original_documents=rows,
                original_eight_quarter_statements_gate="PENDING_REVIEW_SIGNOFF",
                auditor_scope_gate="PENDING_MATERIALITY_HUMAN_REVIEW",
                point_in_time_gate="PENDING_PUBLICATION_VERSION_TIMESTAMPS",
                strategy_out_of_sample_gate="PENDING_SEPARATE_WALK_FORWARD",
                keyword_hits_are_not_auditor_findings=True,
                capture_time_is_not_original_publication_time=True,
                reviewer_id=None,review_completed=False,formal_Aplus=False,
                formal_gate_pass_count_created=0,formal_certificate_emitted=False,
                next_actions=[
                    "逐季人工核閱全部四表、重要附註與原件來源",
                    "核對會計師查核或核閱意見、其他會計師範圍、未核閱子公司與重要性",
                    "建立首次公告與更正版本PIT，不以本次下載時間替代",
                    "具名完成原13項review_pack及策略扣成本Walk-Forward"])

def render(packet):
    c=packet["coverage"]
    n=(str(c["archived_count"])+"/"+str(c["required_count"])
       if c["archived_count"] is not None else "未知")
    lines=["# 2317 鴻海：八季完整財報核閱準備清單（非正式認證）","",
           "核對期間："+packet["financial_period"]+"；研究截止："+packet["research_cutoff"],
           "已重驗原件："+n+"季；狀態："+c["status"],
           "清冊SHA256："+str(packet["source_manifest_sha256"]),"",
           "|季度|原件SHA|PDF頁數|前20頁會計師字詞線索|",
           "|---|---|---:|---|"]
    for row in packet["original_documents"]:
        if row["archive_state"]!="SHA_REHASHED":
            lines.append("|"+row["period"]+"|未經SHA重驗|—|不可判定|")
            continue
        lead=row["auditor_leads"]
        terms="、".join(sorted(set(x["keyword"] for x in lead["keyword_leads"]))) or "無命中"
        lines.append("|"+row["period"]+"|"+row["sha256"][:16]+"…|"+
                     str(row["pdf_page_count"])+"|"+terms+"（掃描"+str(lead["pages_scanned"])+"頁）|")
    lines+=["","## 注意",
            "字詞命中是人工查核頁碼線索，不等於有保留結論，也不代表重要性已經審查。",
            "掃描前20頁不等於完整四表及全部附註已核閱。",
            "SHA封存的擷取日期不等於財報首次公告時點；仍需正式PIT查核。",
            "本報告不產生任何正式PASS、FAIL、A+、A++或第13項策略認證。","",
            "## PDF頁碼線索",""]
    for row in packet["original_documents"]:
        if row["archive_state"]!="SHA_REHASHED":continue
        hits=row["auditor_leads"]["keyword_leads"]
        lines.append("- "+row["period"]+"："+(
            "；".join("第"+str(x["pdf_page_1based"])+"頁「"+x["keyword"]+"」" for x in hits[:8])
            if hits else "前20頁未命中字詞，仍需人工審閱"))
    lines+=["","## 下一步",""]
    lines+=["- "+action for action in packet["next_actions"]]
    return "\n".join(lines)+"\n"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",default="tw-market-data")
    options=parser.parse_args()
    root=Path(options.data_root)
    latest=json.loads((root/"rankings/latest_research.json").read_text(encoding="utf-8"))
    packet=build_packet(root,latest["financial_last_quarter"],latest["estimate_vintage"])
    out=root/"rankings"
    write_if_changed(out/"2317_original_review_packet_latest.json",
                     json.dumps(packet,ensure_ascii=False,indent=2)+"\n")
    write_if_changed(out/"2317_original_review_packet_latest.md",render(packet))
    print(json.dumps(dict(issuer="2317",coverage=packet["coverage"],formal_pass_created=0),
                     ensure_ascii=False))

if __name__=="__main__":
    main()
