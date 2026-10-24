"""Official TWSE BWIBBU historical daily PB, captured by month with SHA receipts.

Backfilling now does NOT mean data was archived when trading happened.
Probe mode and incomplete months NEVER certify ten-year min/median/max.
"""
import argparse,base64,concurrent.futures,datetime,gzip,hashlib,json,math,pathlib,re,statistics,time,urllib.request,urllib.parse

END=datetime.date(2026,10,22)
BEGIN=datetime.date(2016,10,24)
ROOT=pathlib.Path("tw-market-data/research/footwear_pb_2016_2026")
STOCKS={"9904":("寶成","1990-01-01"),
        "6768":("志強-KY","2021-04-22"),
        "6965":("中傑-KY","2025-03-07"),
        "9802":("鈺齊-KY","2012-10-18"),
        "9910":("豐泰","1992-01-01")}
URL="https://www.twse.com.tw/exchangeReport/BWIBBU"
DAYS=re.compile(r"^(\d{2,3})年(\d{1,2})月(\d{1,2})日$")

def month_range(start,end):
    y,m=start.year,start.month
    while (y,m)<=(end.year,end.month):
        yield f"{y:04d}-{m:02d}"
        m+=1
        if m==13:
            y,m=y+1,1

def parsed_month(code,month,data):
    d=json.loads(data)
    if not isinstance(d,dict): raise ValueError("INVALID_OFFICIAL_RESPONSE")
    stat=str(d.get("stat",""))
    if stat!="OK":
        if "查無" in stat or "無資料" in stat: return [],stat
        raise ValueError("UNEXPECTED_TWSE_STAT:"+stat[:80])
    fields=d.get("fields")
    if not isinstance(fields,list) or not all(k in fields for k in ("日期","股價淨值比","財報年/季")):
        raise ValueError("OFFICIAL_PB_COLUMN_SCHEMA_CHANGED")
    idate=fields.index("日期")
    ipb=fields.index("股價淨值比")
    ifq=fields.index("財報年/季")
    observed=set()
    out=[]
    for row in d.get("data",[]):
        if len(row)!=len(fields): raise ValueError("OFFICIAL_ROW_COLUMN_MISMATCH")
        match=DAYS.fullmatch(str(row[idate]).strip())
        if not match: raise ValueError("UNSUPPORTED_ROC_DATE:"+str(row[idate]))
        year,mo,day=(int(v) for v in match.groups())
        daydate=datetime.date(year+1911,mo,day).isoformat()
        if not daydate.startswith(month) or daydate in observed:
            raise ValueError("INCORRECT_MONTH_OR_DUPLICATE_DATE")
        observed.add(daydate)
        pbstr=str(row[ipb]).replace(",","").strip()
        if pbstr in ("","-","--","不適用","N/A"): continue
        pb=float(pbstr)
        if not math.isfinite(pb) or not .01<=pb<=100:
            raise ValueError("INVALID_PB_NUMBER")
        out.append({"date":daydate,"pb":pb,"financial_quarter":str(row[ifq])})
    return out,"OK"

def fetch(code,month):
    requrl=URL+"?"+urllib.parse.urlencode({
        "response":"json","date":month.replace("-","")+"01","stockNo":code})
    last=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(requrl,headers={
                "User-Agent":"Mozilla/5.0","Accept":"application/json,*/*",
                "Referer":"https://www.twse.com.tw/"})
            with urllib.request.urlopen(req,timeout=18) as resp:
                blob=resp.read(150000)
                status=resp.status
            if status!=200: raise ValueError("HTTP_STATUS_"+str(status))
            rows,stat=parsed_month(code,month,blob)
            return {"code":code,"month":month,"url":requrl,"stat":stat,
                    "rows":rows,"sha256":hashlib.sha256(blob).hexdigest(),
                    "http_bytes_base64":base64.b64encode(blob).decode("ascii")}
        except Exception as exc:
            last=str(exc)
            if attempt<2: time.sleep(.45*(attempt+1))
    return {"code":code,"month":month,"url":requrl,"error":last}

def pct(values,p):
    pos=(len(values)-1)*p
    lo=int(pos)
    return values[lo]*(1-(pos-lo))+values[min(lo+1,len(values)-1)]*(pos-lo)

def audit_one(code,months,mode):
    name,ipo=STOCKS[code]
    from_date=max(BEGIN,datetime.date.fromisoformat(ipo))
    accepted=sorted([
      dict(r,month=item["month"]) for item in months if item.get("stat")=="OK"
      for r in item["rows"] if from_date<=datetime.date.fromisoformat(r["date"])<=END
    ],key=lambda r:r["date"])
    if len({r["date"] for r in accepted})!=len(accepted):
        raise ValueError("CROSS_MONTH_DUPLICATE_DATE")
    nums=sorted(r["pb"] for r in accepted)
    required=set(month_range(from_date,END))
    ok={x["month"] for x in months if x.get("stat")=="OK"}
    missing=sorted(required-ok)
    current=next((r for r in accepted if r["date"]==END.isoformat()),None)
    certified=(mode=="full" and not missing and current is not None and len(nums)>=200)
    report={
       "issuer":code,"name":name,"listing_date":ipo,
       "start":from_date.isoformat(),"end":END.isoformat(),
       "has_full_10_year_listing_history":from_date==BEGIN,
       "requested_months":len(months),"complete_months":len(ok),
       "post_listing_missing_months":missing,
       "observed_daily_points":len(accepted),
       "official_dated_snapshot_PIT_backfilled_not_historical_capture":True,
       "historical_extremes_and_median_certified":certified,
       "sample_kind":"COMPLETE_DAILY" if certified else "PARTIAL_RETRIEVED_SAMPLES",
       "minimum_pb":min(nums) if nums else None,
       "median_pb":round(statistics.median(nums),4) if nums else None,
       "maximum_pb":max(nums) if nums else None,
       "p10_pb":round(pct(nums,.1),4) if nums else None,
       "p25_pb":round(pct(nums,.25),4) if nums else None,
       "asof_2026_10_22_pb":current["pb"] if current else None,
       "asof_pb_percentile_pct":round(100*sum(v<=current["pb"] for v in nums)/len(nums),2) if current else None,
       "minimum_dates":[r["date"] for r in accepted if nums and r["pb"]==nums[0]][:4],
       "maximum_dates":[r["date"] for r in accepted if nums and r["pb"]==nums[-1]][:4]
    }
    return report

def run(mode,workers):
    tasks=[]
    for code,(_,ipo) in STOCKS.items():
        seq=list(month_range(max(BEGIN,datetime.date.fromisoformat(ipo)),END))
        if mode=="probe":
            seq=sorted(set([seq[0],seq[len(seq)//2],seq[-1]]))
        tasks.extend((code,m) for m in seq)
    if workers<1 or workers>5: raise ValueError("INVALID_WORKERS")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        originals=list(pool.map(lambda pair:fetch(*pair),tasks))
    ROOT.mkdir(parents=True,exist_ok=True)
    reports=[]
    for code in STOCKS:
        items=sorted((x for x in originals if x["code"]==code),key=lambda z:z["month"])
        report=audit_one(code,items,mode)
        reports.append(report)
        with gzip.open(ROOT/f"{code}_{mode}_originals.json.gz","wb",compresslevel=8) as f:
            f.write(json.dumps({"method":"official TWSE HTTP body base64 + sha256 by month",
                       "stock":code,"months":items},ensure_ascii=False,
                       separators=(",",":")).encode("utf-8"))
    result={
        "schema":"V8107_TWSE_2016_2026_DAILY_PB_RESEARCH_V1",
        "mode":mode,"retrieved_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "official_endpoint":URL,"anchor":END.isoformat(),"lookback_from":BEGIN.isoformat(),
        "official_http_errors":[{k:v for k,v in x.items() if k in ("code","month","error")}
                                for x in originals if "error" in x],
        "historical_original_first_captured_in_2026_not_asof_traded_date":True,
        "all_full_listing_histories_certified":mode=="full" and all(
            x["historical_extremes_and_median_certified"] for x in reports),
        "formal_Aplus_added":0,
        "companies":reports,
    }
    (ROOT/f"{mode}_pb_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"mode":mode,"requests":len(originals),
          "network_errors":len(result["official_http_errors"]),
          "summary":[{k:r[k] for k in ("issuer","observed_daily_points",
                      "minimum_pb","median_pb","maximum_pb","asof_2026_10_22_pb",
                      "historical_extremes_and_median_certified")} for r in reports]},ensure_ascii=False))
    if result["official_http_errors"]:
        raise SystemExit("MISSING_ORIGINAL_HTTP_RESPONSES_NO_PB_CERTIFICATION")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",default="probe",choices=["probe","full"])
    ap.add_argument("--workers",type=int,default=3)
    opt=ap.parse_args()
    run(opt.mode,opt.workers)
