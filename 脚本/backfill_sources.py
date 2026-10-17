#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_sources.py — 历史回溯补抓

用途：为「当日没有巡检快照」的历史自然日补齐原始快照。只用于支持
日期范围过滤参数的一手接口（官方 API，非网页猜测）：
    aihot / hn-algolia / github-search / arxiv-query / sec-edgar / federal-register
其余 RSS/Atom 信源只能返回「最近 N 条」，历史内容不可回溯 —— 这些信源的
历史条目来自相邻日期的巡检快照（classify.py 的跨快照合并），不在此补足，
以免混淆数据来源。

产出：
    数据/回溯/<日期>/<信源id>.json   与正式快照同结构（原文 + 抓取时间 + 校验值）
    数据/回溯/<日期>/补抓报告.md      该次补抓的来源清单与结果

用法：
    python backfill_sources.py --date 2026-10-11
    python backfill_sources.py --from 2026-10-11 --to 2026-10-12
    python backfill_sources.py --date 2026-10-11 --only arxiv-query,hn-algolia

依赖：仅 Python 标准库。抓取失败只记录，不生成占位文件（不凭空造数）。
"""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REGISTRY_PATH = BASE / "信源注册表" / "sources.json"
BACKFILL_ROOT = BASE / "数据" / "回溯"
USER_AGENT = "yuesheng-ai-infobot/0.1 (daily AI news aggregation; local-use)"
BJ = timezone(timedelta(hours=8))
REQUEST_GAP_SECONDS = 3


def bj_now():
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")


def day_dt(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=BJ)


# ---------------------------------------------------------------- URL 构造
def utc_epoch(date_str, hour=0):
    """北京时间 date_str HH:00 → UTC epoch 秒。"""
    return int(day_dt(date_str).replace(hour=hour).timestamp())


def arxiv_window(date_str):
    """arXiv submittedDate 用 UTC，北京时间整日 = UTC [前一日 16:00, 当日 15:59]。"""
    d = day_dt(date_str)
    s = (d - timedelta(hours=8)).strftime("%Y%m%d%H%M")
    e = (d + timedelta(hours=15, minutes=59)).strftime("%Y%m%d%H%M")
    return s, e


def build_url(sid, date_str):
    """按信源官方接口的日期过滤参数构造回溯 URL；不支持者返回 None。"""
    prev = (day_dt(date_str) - timedelta(days=1)).strftime("%Y-%m-%d")
    if sid == "aihot":
        return "https://aihot.news/api/v1/dailies/%s" % date_str
    if sid == "hn-algolia":
        return ("https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story"
                "&hitsPerPage=30&numericFilters=created_at_i>%d,created_at_i<%d"
                % (utc_epoch(date_str), utc_epoch(date_str) + 86400))
    if sid == "github-search":
        return ("https://api.github.com/search/repositories?q=topic:llm"
                "+pushed:%s..%s&sort=updated&per_page=20" % (date_str, date_str))
    if sid == "arxiv-query":
        s, e = arxiv_window(date_str)
        return ("https://export.arxiv.org/api/query?search_query="
                "(cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG+OR+cat:cs.CV)"
                "+AND+submittedDate:[%s+TO+%s]"
                "&sortBy=submittedDate&sortOrder=descending&max_results=100" % (s, e))
    if sid == "sec-edgar":
        return ("https://efts.sec.gov/LATEST/search-index?q=%%22artificial%%20intelligence%%22"
                "&dateRange=custom&startdt=%s&enddt=%s" % (date_str, date_str))
    if sid == "federal-register":
        return ("https://www.federalregister.gov/api/v1/documents.json"
                "?conditions%%5Bterm%%5D=artificial%%20intelligence"
                "&conditions%%5Bpublication_date%%5D%%5Bgte%%5D=%s"
                "&conditions%%5Bpublication_date%%5D%%5Blte%%5D=%s"
                "&order=newest&per_page=20"
                "&fields%%5B%%5D=title&fields%%5B%%5D=html_url"
                "&fields%%5B%%5D=publication_date&fields%%5B%%5D=agencies"
                % (date_str, date_str))
    return None


BACKFILL_IDS = ["aihot", "hn-algolia", "github-search", "arxiv-query",
                "sec-edgar", "federal-register"]


# ---------------------------------------------------------------- 抓取
def http_get(url, timeout=25, retries=3, pause=6):
    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace"), "ok"
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(pause * (attempt + 1))
                continue
            return e.code, last, "http"
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:120])
            if attempt < retries - 1:
                time.sleep(pause * (attempt + 1))
                continue
    return None, last, "network"


def rough_count(text, sid):
    """粗估条目数（仅用于报告，不做数据判定）。"""
    try:
        o = json.loads(text)
    except Exception:
        return len(text.split("<entry>")) - 1 if "<entry>" in text else 0
    if isinstance(o, dict):
        for k in ("hits", "items", "results", "documents"):
            if isinstance(o.get(k), list):
                return len(o[k])
        rep, sec = o.get("report"), 0
        if isinstance(rep, dict):
            for s in rep.get("sections", []):
                sec += len(s.get("items") or [])
            return sec
        if isinstance(o.get("hits"), dict):
            return o["hits"].get("total", {}).get("value", 0)
    return 0


def save_snapshot(date_str, src, url, status, text, kind, err=""):
    d = BACKFILL_ROOT / date_str
    d.mkdir(parents=True, exist_ok=True)
    raw = text if kind == "ok" else ""
    payload = {
        "source_id": src["id"], "source_name": src["name"], "tier": src.get("tier"),
        "fetched_at_bj": bj_now(), "url": url, "http_status": status,
        "valid": bool(raw) and (status or 0) < 400, "item_count": rough_count(raw, src["id"]),
        "field_completeness": -1, "unreachable": kind == "network", "error": err,
        "backfill": True,
        "sha1": hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest(),
        "raw": raw,
    }
    path = d / ("%s.json" % src["id"])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path, payload["item_count"]


def write_report(date_str, rows):
    lines = ["# 历史回溯补抓报告 · %s" % date_str, "",
             "- 补抓时间：%s（北京时间）" % bj_now(),
             "- 补抓目录：数据/回溯/%s/" % date_str,
             "- 抓取范围：支持日期范围参数的一手接口 %d 个" % len(rows),
             "- 说明：仅补足可凭官方接口按日检索的信源；RSS/Atom 信源的历史条目"
             "来自相邻日期的巡检快照，由 classify.py 跨快照合并时纳入。",
             "", "| 信源 ID | 名称 | HTTP | 粗估条目 | 结果 |", "|---|---|---|---|---|"]
    for sid, name, status, n, ok, note in rows:
        lines.append("| %s | %s | %s | %s | %s |" % (
            sid, name, "—" if status is None else status, n,
            "✅" if ok else ("🌐 网络不可达" if note == "network" else "❌ " + note[:40])))
    lines.append("")
    lines.append("> 补抓失败不写占位数据；该信源当日数据以「无」记录。")
    p = BACKFILL_ROOT / date_str / "补抓报告.md"
    p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return p


def run_date(date_str, only=None):
    reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    sources = {s["id"]: s for s in reg["sources"]}
    ids = [i for i in BACKFILL_IDS if not only or i in only]
    print("== 回溯补抓 %s（%d 个信源）==" % (date_str, len(ids)))
    rows = []
    for i, sid in enumerate(ids):
        if i:
            time.sleep(REQUEST_GAP_SECONDS)
        src = sources.get(sid)
        url = build_url(sid, date_str)
        if not src or not url:
            rows.append((sid, (src or {}).get("name", sid), None, 0, False, "无回溯 URL"))
            continue
        status, text, kind = http_get(url)
        ok = kind == "ok" and (status or 0) < 400 and bool(text)
        err = "" if ok else (text if kind != "ok" else "HTTP %s" % status)
        _p, n = save_snapshot(date_str, src, url, status, text, kind, err)
        rows.append((sid, src["name"], status, n, ok, kind if not ok else ""))
        print("%s %-16s HTTP=%-5s items=%-4s %s" % (
            "OK  " if ok else ("ENV " if kind == "network" else "FAIL"),
            sid, status, n, url[:70]))
    report = write_report(date_str, rows)
    ok_n = sum(1 for r in rows if r[4])
    print("== %s 完成：%d/%d 成功；报告 %s ==" % (date_str, ok_n, len(rows), report))


def main():
    ap = argparse.ArgumentParser(description="历史回溯补抓（仅官方日期范围接口）")
    ap.add_argument("--date", help="回溯目标自然日 YYYY-MM-DD")
    ap.add_argument("--from", dest="from_date", help="起始自然日（含）")
    ap.add_argument("--to", dest="to_date", help="结束自然日（含）")
    ap.add_argument("--only", help="只补抓指定信源，逗号分隔")
    args = ap.parse_args()

    dates = []
    if args.date:
        dates = [args.date]
    elif args.from_date and args.to_date:
        d0, d1 = day_dt(args.from_date), day_dt(args.to_date)
        while d0 <= d1:
            dates.append(d0.strftime("%Y-%m-%d"))
            d0 += timedelta(days=1)
    if not dates:
        raise SystemExit("需指定 --date 或 --from/--to")
    only = set(x.strip() for x in args.only.split(",")) if args.only else None
    for ds in dates:
        run_date(ds, only)


if __name__ == "__main__":
    main()
