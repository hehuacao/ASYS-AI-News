#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_sources.py — 信源抓取巡检引擎

按信源注册表逐个抓取并归档原始快照：
  - 通道测试（试抓）：HTTP 状态 + 内容解析 + 字段完整率（注册流程准入依据）
  - 原始快照全量存档：原文 + 抓取时间 + 校验值，存 数据/快照/<日期>/<信源id>.json
  - 注册表运行时字段回写：last_ok / last_fail / last_status / last_probe /
    last_item_count / last_completeness / fail_streak
  - 连续失败自动禁用 + 备注（防单日偶发失败误伤）
  - 每次巡检生成 数据/快照/<日期>/巡检报告.md

用法：
  python fetch_sources.py                 # 巡检全部 enabled 信源
  python fetch_sources.py --only aihot,hn-algolia
  python fetch_sources.py --status        # 仅查看注册表状态，不抓取

依赖：仅 Python 标准库。URL 支持 {today} / {yesterday} 占位符（北京时间日期）。
"""
import argparse
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REGISTRY_PATH = BASE / "信源注册表" / "sources.json"
SNAPSHOT_ROOT = BASE / "数据" / "快照"
USER_AGENT = "yuesheng-ai-infobot/0.1 (daily AI news aggregation; local-use)"
BJ = timezone(timedelta(hours=8))
FAIL_DISABLE_THRESHOLD = 3
REQUEST_GAP_SECONDS = 2

TITLE_KEYS = ("title", "name", "headline", "display_names")
URL_KEYS = ("html_url", "url", "link", "abs_url", "paper_id", "objectID", "id", "_id")
LIST_KEYS = ("results", "hits", "data", "items", "works", "entries", "notes",
             "documents", "papers", "reports", "sections", "flashes")


def bj_now():
    return datetime.now(BJ)


def bj_today():
    return bj_now().strftime("%Y-%m-%d")


def load_registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_registry(reg):
    reg["updated_at"] = bj_today()
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(REGISTRY_PATH)


def expand_url(url):
    today = bj_today()
    yesterday = (bj_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return url.replace("{today}", today).replace("{yesterday}", yesterday)


def http_get(url, timeout=15, retries=3):
    """返回 (status, text, kind)。kind: ok=成功 / http=HTTP错误 / network=网络不可达。"""
    last_err = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if "gzip" in enc:
                    raw = gzip.decompress(raw)
                elif "deflate" in enc:
                    raw = zlib.decompress(raw)
                return resp.status, raw.decode("utf-8", errors="replace"), "ok"
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s" % e.code
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return e.code, last_err, "http"
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, e)
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
    return None, last_err, "network"


def parse_feed_items(text):
    """RSS/Atom -> [(title, link)]，解析失败抛异常。"""
    root = ET.fromstring(text)
    items = []
    for it in root.iter("item"):
        items.append((it.findtext("title") or "", it.findtext("link") or ""))
    if not items:
        ns = "{http://www.w3.org/2005/Atom}"
        for it in root.iter(ns + "entry"):
            link = ""
            for l in it.findall(ns + "link"):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href") or ""
                    break
            items.append((it.findtext(ns + "title") or "", link))
    return items


def extract_json_items(obj):
    """尽力从 JSON 中提取条目列表；找不到返回 None。"""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in LIST_KEYS:
            v = obj.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for k2 in LIST_KEYS:
                    v2 = v.get(k2)
                    if isinstance(v2, list):
                        return v2
    return None


def json_field_completeness(items):
    if not items:
        return 0.0
    ok = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        # EDGAR 等接口的字段嵌在 _source 里，展开后计算
        if isinstance(it.get("_source"), dict):
            it = {**it, **it["_source"]}
        has_t = any(it.get(k) for k in TITLE_KEYS)
        has_u = any(it.get(k) for k in URL_KEYS)
        if has_t and has_u:
            ok += 1
    return round(ok / len(items), 3)


def feed_completeness(pairs):
    if not pairs:
        return 0.0
    ok = sum(1 for t, l in pairs if t and l)
    return round(ok / len(pairs), 3)


def probe_source(src):
    url = expand_url(src["url"])
    status, text, kind = http_get(url)
    res = {
        "id": src["id"],
        "url": url,
        "http_status": status,
        "fetched_at": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "valid": False,
        "unreachable": kind == "network",
        "item_count": 0,
        "completeness": 0.0,
        "error": "",
        "raw": text if kind == "ok" else "",
    }
    if kind != "ok" or not text:
        res["error"] = text or ("HTTP %s" % status)
        return res
    try:
        if src["type"] in ("rss", "atom"):
            pairs = parse_feed_items(text)
            res["item_count"] = len(pairs)
            res["completeness"] = feed_completeness(pairs)
            res["valid"] = len(pairs) > 0
            if not res["valid"]:
                res["error"] = "feed 可解析但无条目"
        elif src["type"] in ("json_api", "api"):
            obj = json.loads(text)
            items = extract_json_items(obj)
            if items is None:
                res["valid"] = True
                res["item_count"] = -1
                res["completeness"] = -1
                res["note"] = "非列表 JSON 结构（如 AIHOT 日报），解析成功即有效"
            else:
                res["item_count"] = len(items)
                res["completeness"] = json_field_completeness(items)
                res["valid"] = len(items) > 0
                if not res["valid"]:
                    res["error"] = "JSON 可解析但条目为空"
        else:
            res["error"] = "类型 %s 不在自动抓取范围（channel D 人工源）" % src["type"]
    except Exception as e:
        res["error"] = "解析失败: %s" % e
    return res


def save_snapshot(date_str, src, res):
    d = SNAPSHOT_ROOT / date_str
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("%s.json" % src["id"])
    payload = {
        "source_id": src["id"],
        "source_name": src["name"],
        "tier": src["tier"],
        "fetched_at_bj": res["fetched_at"],
        "url": res["url"],
        "http_status": res["http_status"],
        "valid": res["valid"],
        "item_count": res["item_count"],
        "field_completeness": res["completeness"],
        "unreachable": res.get("unreachable", False),
        "error": res["error"],
        "sha1": hashlib.sha1(res["raw"].encode("utf-8", errors="replace")).hexdigest(),
        "raw": res["raw"],
    }
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def fmt(v):
    return "—" if v in (None, -1) else str(v)


def write_report(date_str, results):
    lines = []
    ok_n = sum(1 for _, r, _ in results if r["valid"])
    unreach = [(s, r) for s, r, _ in results if r.get("unreachable")]
    real_fail = [(s, r) for s, r, _ in results
                 if not r["valid"] and not r.get("unreachable")]
    lines.append("# 信源巡检报告 · %s" % date_str)
    lines.append("")
    lines.append("- 巡检时间：%s（北京时间）" % bj_now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("- 巡检范围：enabled 信源 %d 个" % len(results))
    lines.append("- 结果：成功 %d / 信源失效 %d / 环境不可达 %d" % (
        ok_n, len(real_fail), len(unreach)))
    lines.append("- 快照存档：数据/快照/%s/（每源一档：原文 + 抓取时间 + sha1）" % date_str)
    lines.append("")
    lines.append("| 信源 ID | 名称 | 层级 | HTTP | 条目数 | 字段完整率 | 结果 |")
    lines.append("|---|---|---|---|---|---|---|")
    for src, res, _ in results:
        if res["valid"]:
            mark = "✅"
        elif res.get("unreachable"):
            mark = "🌐 环境不可达"
        else:
            mark = "❌"
        comp = fmt(res["completeness"])
        if comp != "—":
            comp = "%.0f%%" % (float(comp) * 100)
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            src["id"], src["name"], src["tier"], fmt(res["http_status"]),
            fmt(res["item_count"]), comp, mark))
    if real_fail:
        lines.append("")
        lines.append("## 信源失效清单（需人工处理）")
        for src, res in real_fail:
            lines.append("- **%s**（%s）：%s" % (src["id"], src["name"], res["error"]))
    if unreach:
        lines.append("")
        lines.append("## 环境不可达清单（非信源问题，不计失败）")
        for src, res in unreach:
            lines.append("- **%s**（%s）：%s" % (src["id"], src["name"], res["error"]))
    lines.append("")
    lines.append("> 字段完整率 = 条目中同时含标题与链接的比例；注册准入线为 ≥90%（规范第一篇 6.2）。")
    path = SNAPSHOT_ROOT / date_str / "巡检报告.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def run_probe(reg, only=None):
    sources = [s for s in reg["sources"] if s.get("enabled")]
    if only:
        only_set = set(x.strip() for x in only.split(",") if x.strip())
        sources = [s for s in sources if s["id"] in only_set]
        if not sources:
            print("没有匹配的 enabled 信源：%s" % only)
            return
    date_str = bj_today()
    print("== 信源巡检 %s（enabled %d 个）==" % (date_str, len(sources)))
    results = []
    for i, src in enumerate(sources):
        if i:
            time.sleep(REQUEST_GAP_SECONDS)
        res = probe_source(src)
        snap = save_snapshot(date_str, src, res)
        stamp = res["fetched_at"]
        if res["valid"] and res["http_status"] and res["http_status"] < 400:
            src["last_ok"] = stamp
            src["fail_streak"] = 0
            src.pop("fail_dates", None)
        elif res.get("unreachable"):
            # 网络环境不可达（代理/DNS/TLS）≠ 信源失效：记录但不计入失败计数
            src["last_probe"] = stamp
            src["last_status"] = None
            results.append((src, res, snap))
            print("ENV  %-16s %-30s 网络不可达：%s" % (
                src["id"], src["name"][:30], res["error"][:60]))
            continue
        else:
            src["fail_streak"] = src.get("fail_streak", 0) + 1
            src["last_fail"] = stamp
            dates = src.get("fail_dates", [])
            dates.append(bj_today())
            src["fail_dates"] = dates[-5:]
            # 自动禁用防线：连续失败 ≥3 次且失败跨越 ≥2 个日期，
            # 防止同日重复巡检把可修复的信源误杀（规范第一篇 7.3）
            distinct_days = len(set(src["fail_dates"][-3:]))
            if src["fail_streak"] >= FAIL_DISABLE_THRESHOLD and distinct_days >= 2:
                src["enabled"] = False
                # 追加一行简短状态，不写入历次巡检过程（保持注册表可读）：
                # 形如「…。当前备用：连续 3 次巡检失败（2026-10-15）。」
                src["notes"] = (src.get("notes", "") +
                                " 当前备用：连续 %d 次巡检失败（%s）。"
                                % (FAIL_DISABLE_THRESHOLD, date_str)).strip()
                print("!! %s 连续失败 %d 次且跨 %d 天，已自动禁用" % (src["id"], src["fail_streak"], distinct_days))
        src["last_status"] = res["http_status"]
        src["last_probe"] = stamp
        src["last_item_count"] = res["item_count"]
        src["last_completeness"] = res["completeness"]
        results.append((src, res, snap))
        mark = "OK  " if res["valid"] else "FAIL"
        print("%s %-16s %-30s HTTP=%-5s items=%-4s comp=%s" % (
            mark, src["id"], src["name"][:30], fmt(res["http_status"]),
            fmt(res["item_count"]), fmt(res["completeness"])))
    save_registry(reg)
    report = write_report(date_str, results)
    ok = sum(1 for _, r, _ in results if r["valid"])
    env_n = sum(1 for _, r, _ in results if r.get("unreachable"))
    print("== 完成：%d/%d 成功，%d 环境不可达，%d 信源失效；报告 %s ==" % (
        ok, len(results), env_n, len(results) - ok - env_n, report))


def show_status(reg):
    print("== 信源注册表状态（%s）==" % reg.get("updated_at"))
    enabled = [s for s in reg["sources"] if s.get("enabled")]
    disabled = [s for s in reg["sources"] if not s.get("enabled")]
    print("登记 %d 个 | 启用 %d | 备用 %d" % (len(reg["sources"]), len(enabled), len(disabled)))
    print()
    print("%-16s %-30s %-4s %-6s %-8s %s" % ("ID", "名称", "层级", "通道", "状态", "最近巡检"))
    for s in reg["sources"]:
        print("%-16s %-30s %-4s %-6s %-8s %s" % (
            s["id"], s["name"][:30], s["tier"], s["channel"],
            ("启用" if s.get("enabled") else "备用"),
            s.get("last_probe", "—")))


def main():
    ap = argparse.ArgumentParser(description="信源抓取巡检引擎")
    ap.add_argument("--only", help="只巡检指定信源，逗号分隔")
    ap.add_argument("--status", action="store_true", help="仅查看注册表状态，不抓取")
    args = ap.parse_args()
    reg = load_registry()
    if args.status:
        show_status(reg)
        return
    run_probe(reg, only=args.only)


if __name__ == "__main__":
    main()
