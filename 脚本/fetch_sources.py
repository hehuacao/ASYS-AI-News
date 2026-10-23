#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_sources.py — 信源抓取巡检引擎

按信源注册表逐个抓取并归档原始快照：
  - 通道测试（试抓）：HTTP 状态 + 内容解析 + 字段完整率（注册流程准入依据）
  - 原始快照全量存档：原文 + 抓取时间 + 校验值，存 数据/快照/<日期>/<信源id>.json
  - 注册表运行时字段回写：last_ok / last_fail / last_status / last_probe /
    last_item_count / last_completeness / fail_streak
  - 失败判定：HTTP 200 且内容可解析 = 源可达（条目为空记为「无数据」）；
    网络不可达与代理 403/429/5xx 记为环境或配额受限，均不计入失败计数；
    真失败按自然日累计，达阈值自动禁用并写入 disabled_at
  - JSON 接口分页：源配置 pagination 后按总数翻页取全，规避单次硬上限
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
TOTAL_KEYS = ("total_count", "totalHits", "totalResults", "count")
# 退路时扫描的常见容器（不扫全部 dict 值，避免命中与结果无关的计数字段）
TOTAL_HOLDER_KEYS = ("hits", "data", "meta", "page", "pagination", "result")

# HTTP 状态分类：**信源失效**只应源于源本身（路径写错、schema 变更导致解析失败）。
# 代理抖动 / 配额限流 / 上游 5xx 属环境或配额问题，计入 fail_streak 会把健康信源误杀。
# 故 403 / 429 / 5xx 归 env_limited，与「网络不可达」同样不计失败。
ENV_LIMITED_STATUS = frozenset({403, 429})


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


def extract_json_items(obj, with_path=False):
    """尽力从 JSON 中提取条目列表；找不到返回 None。
    with_path=True 时返回 (items, path)：path 是 items 在 obj 中的键路径
    （一或两级），供分页合并时把多页结果写回同一位置。"""
    if isinstance(obj, list):
        return (obj, ()) if with_path else obj
    if isinstance(obj, dict):
        for k in LIST_KEYS:
            v = obj.get(k)
            if isinstance(v, list):
                return (v, (k,)) if with_path else v
            if isinstance(v, dict):
                for k2 in LIST_KEYS:
                    v2 = v.get(k2)
                    if isinstance(v2, list):
                        return (v2, (k, k2)) if with_path else v2
    return (None, None) if with_path else None


def extract_total(obj, path=None):
    """提取「总条目数」；找不到返回 None。

    首选**条目所在容器**的 total —— 同一容器里的 total 才与该列表同源。
    EDGAR 响应的 hits.total.value=172 与 hits.hits 同级，而顶层 _shards.total
    是分片命中数（50），与结果条数无关，必须排除。

    path 为 extract_json_items(with_path=True) 返回的条目键路径。
    """
    if not isinstance(obj, (dict, list)):
        return None
    if path is not None:
        container = obj
        for k in path[:-1]:
            container = container.get(k) if isinstance(container, dict) else None
            if container is None:
                break
        if isinstance(container, dict):
            t = container.get("total")
            if isinstance(t, dict):
                v = t.get("value")
                if isinstance(v, (int, float)):
                    return int(v)
                inner = t.get("hits")
                if isinstance(inner, dict) and isinstance(inner.get("value"), (int, float)):
                    return int(inner["value"])
            elif isinstance(t, (int, float)):
                return int(t)
    holders = [obj] if isinstance(obj, dict) else []
    for k in TOTAL_HOLDER_KEYS:
        v = obj.get(k) if isinstance(obj, dict) else None
        if isinstance(v, dict):
            holders.append(v)
    for holder in holders:
        t = holder.get("total")
        if isinstance(t, dict):
            v = t.get("value")
            if isinstance(v, (int, float)):
                return int(v)
        elif isinstance(t, (int, float)):
            return int(t)
        for k in TOTAL_KEYS:
            v = holder.get(k)
            if isinstance(v, (int, float)):
                return int(v)
    return None


def is_env_limited(status):
    """HTTP 状态是否属「环境或配额受限」（代理拦截、限流、上游 5xx）。"""
    if status is None:
        return False
    if status in ENV_LIMITED_STATUS:
        return True
    return 500 <= status < 600


def build_paged_url(url, param, offset):
    sep = "&" if "?" in url else "?"
    return "%s%s%s=%d" % (url, sep, param, offset)


def merge_items_into(base_obj, path, merged):
    """把合并后的条目写回 JSON 文档的同一位置，返回新文档（不改原对象）。"""
    if not path or base_obj is None:
        return base_obj
    doc = json.loads(json.dumps(base_obj, ensure_ascii=False))
    cur = doc
    for k in path[:-1]:
        cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is None:
            return base_obj
    if isinstance(cur, dict):
        cur[path[-1]] = merged
    return doc


def fetch_json_with_pagination(url, src):
    """抓取 JSON 接口，支持按源配置翻页取全。

    源配置可选字段 `pagination`：{"param": "from", "step": 100, "max_pages": 10}。
    仅在响应能解析出总条目数、且已取条数小于总数时继续翻页；单次硬上限
    （服务端忽略 size、每页固定 N 条）由此绕开。返回 dict：
    status / text / kind / items / base_obj / path / total / pages。
    """
    pg = src.get("pagination") or {}
    param = pg.get("param") or "from"
    step = int(pg.get("step") or 100)
    max_pages = int(pg.get("max_pages") or 10)
    out = {"status": None, "text": "", "kind": "network", "items": None,
           "base_obj": None, "path": None, "total": None, "pages": 0}
    status, text, kind = http_get(url)
    out["status"], out["text"], out["kind"] = status, text, kind
    if kind != "ok" or not text:
        return out
    try:
        base_obj = json.loads(text)
    except Exception:
        out["kind"] = "json"
        return out
    items, path = extract_json_items(base_obj, with_path=True)
    out["base_obj"], out["path"] = base_obj, path
    if items is None:
        return out
    merged = list(items)
    total = extract_total(base_obj, path)
    out["total"] = total
    out["pages"] = 1
    if path and total and len(merged) < total and step > 0:
        offset = len(merged)
        while out["pages"] < max_pages and offset < total:
            pstatus, ptext, pkind = http_get(build_paged_url(url, param, offset))
            if pkind != "ok" or not ptext:
                break
            try:
                pobj = json.loads(ptext)
            except Exception:
                break
            pitems, _ = extract_json_items(pobj, with_path=True)
            if not pitems:
                break
            merged.extend(pitems)
            out["pages"] += 1
            offset += len(pitems)
            if len(pitems) < step:
                break
    out["items"] = merged
    return out


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
    res = {
        "id": src["id"],
        "url": url,
        "http_status": None,
        "fetched_at": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "valid": False,
        "unreachable": False,
        "item_count": 0,
        "completeness": 0.0,
        "error": "",
        "raw": "",
    }
    try:
        if src["type"] in ("rss", "atom"):
            status, text, kind = http_get(url)
            res["http_status"] = status
            res["raw"] = text if kind == "ok" else ""
            if kind != "ok" or not text:
                res["error"] = text or ("HTTP %s" % status)
                res["unreachable"] = kind == "network"
                if kind == "http" and is_env_limited(status):
                    res["env_limited"] = True
                return res
            pairs = parse_feed_items(text)
            res["item_count"] = len(pairs)
            res["completeness"] = feed_completeness(pairs)
            res["valid"] = len(pairs) > 0
            if not res["valid"]:
                res["error"] = "feed 可解析但无条目"
        elif src["type"] in ("json_api", "api"):
            r = fetch_json_with_pagination(url, src)
            res["http_status"] = r["status"]
            res["raw"] = r["text"] if r["kind"] == "ok" else ""
            res["pages"] = r["pages"]
            res["total"] = r["total"]
            if r["kind"] != "ok":
                res["error"] = r["text"] or ("HTTP %s" % r["status"])
                res["unreachable"] = r["kind"] == "network"
                if r["kind"] == "http" and is_env_limited(r["status"]):
                    res["env_limited"] = True
                return res
            obj = r["base_obj"]
            items = r["items"]
            if items is None:
                res["valid"] = True
                res["item_count"] = -1
                res["completeness"] = -1
                res["note"] = "非列表 JSON 结构（如 AIHOT 日报），解析成功即有效"
            else:
                res["item_count"] = len(items)
                res["completeness"] = json_field_completeness(items)
                if items:
                    res["valid"] = True
                else:
                    # 空列表 ≠ 信源失效：HTTP 200 且 JSON 可解析即说明源可达，
                    # 「当日无内容」是正常状态（周末无更新、索引尚未发布、
                    # 订阅源当日无文）。记为 no_data，不计入失败计数。
                    res["valid"] = True
                    res["no_data"] = True
                    res["error"] = "无数据（源可达，当日无内容）"
                if r["pages"] > 1:
                    # 多页合并：把合并后的条目写回 JSON 文档同一位置后落盘，
                    # 让下游解析（classify.parse_*）拿到完整条目集。
                    merged_doc = merge_items_into(obj, r["path"], items)
                    res["raw"] = json.dumps(merged_doc, ensure_ascii=False)
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
        "env_limited": res.get("env_limited", False),
        "no_data": res.get("no_data", False),
        "pages": res.get("pages", 1),
        "total": res.get("total"),
        "error": res["error"],
        "sha1": hashlib.sha1(res["raw"].encode("utf-8", errors="replace")).hexdigest(),
        "raw": res["raw"],
    }
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def fmt(v):
    return "—" if v in (None, -1) else str(v)


def write_report(date_str, results, registry=None):
    lines = []
    ok_n = sum(1 for _, r, _ in results if r["valid"])
    unreach = [(s, r) for s, r, _ in results if r.get("unreachable")]
    envlim = [(s, r) for s, r, _ in results if r.get("env_limited")]
    nodata = [(s, r) for s, r, _ in results if r.get("no_data")]
    real_fail = [(s, r) for s, r, _ in results
                 if not r["valid"] and not r.get("unreachable")
                 and not r.get("env_limited")]
    lines.append("# 信源巡检报告 · %s" % date_str)
    lines.append("")
    lines.append("- 巡检时间：%s（北京时间）" % bj_now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("- 巡检范围：enabled 信源 %d 个" % len(results))
    lines.append("- 结果：成功 %d（其中无数据 %d） / 信源失效 %d / 环境不可达 %d / 配额受限 %d" % (
        ok_n, len(nodata), len(real_fail), len(unreach), len(envlim)))
    lines.append("- 快照存档：数据/快照/%s/（每源一档：原文 + 抓取时间 + sha1）" % date_str)
    lines.append("")
    lines.append("| 信源 ID | 名称 | 层级 | HTTP | 条目数 | 字段完整率 | 结果 |")
    lines.append("|---|---|---|---|---|---|---|")
    for src, res, _ in results:
        if res.get("no_data"):
            mark = "◻️ 无数据"
        elif res["valid"]:
            mark = "✅"
        elif res.get("env_limited"):
            mark = "🚦 配额/环境受限"
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
    if envlim:
        lines.append("")
        lines.append("## 配额 / 环境受限清单（非信源失效，不计失败）")
        for src, res in envlim:
            lines.append("- **%s**（%s）：HTTP %s — %s" % (
                src["id"], src["name"], res["http_status"], res["error"]))
    if unreach:
        lines.append("")
        lines.append("## 环境不可达清单（非信源问题，不计失败）")
        for src, res in unreach:
            lines.append("- **%s**（%s）：%s" % (src["id"], src["name"], res["error"]))
    if nodata:
        lines.append("")
        lines.append("## 无数据清单（源可达，当日无内容）")
        for src, res in nodata:
            lines.append("- **%s**（%s）：%s" % (src["id"], src["name"], res["error"]))
    if registry:
        expired = [s for s in registry["sources"]
                   if s.get("trial_until") and s["trial_until"] <= date_str]
        pending = [s for s in registry["sources"]
                   if s.get("trial_until") and s["trial_until"] > date_str]
        lines.append("")
        lines.append("## 试用期信源清单（trial_until 临近或已到期）")
        if expired:
            for s in expired:
                lines.append("- ⏰ **%s**（%s）：trial_until %s 已到期，status=%s，enabled=%s" % (
                    s["id"], s["name"], s["trial_until"], s.get("status"),
                    "是" if s.get("enabled") else "否"))
        else:
            lines.append("- 无已到期源")
        if pending:
            lines.append("")
            lines.append("- 试用中（未到期）%d 个：%s" % (
                len(pending), "、".join(s["id"] for s in pending)))
    lines.append("")
    lines.append("> 字段完整率 = 条目中同时含标题与链接的比例；注册准入线为 ≥90%（规范第一篇 6.2）。")
    lines.append("> 「无数据」= HTTP 200 且 JSON 可解析但条目为空，源本身健康，不计入失败计数。")
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
        elif res.get("unreachable") or res.get("env_limited"):
            # 环境不可达 / 配额限流 ≠ 信源失效：记录但不计入失败计数。
            # 代理 502、匿名 API 限流、上游 5xx 都属此类。
            src["last_probe"] = stamp
            src["last_status"] = None
            results.append((src, res, snap))
            tag = "配额/环境受限" if res.get("env_limited") else "网络不可达"
            print("ENV  %-16s %-30s %s：%s" % (
                src["id"], src["name"][:30], tag, res["error"][:60]))
            continue
        else:
            src["last_fail"] = stamp
            # fail_streak 按**自然日**计：同一自然日内重复巡检只记一次失败，
            # 否则同日重跑会提前凑够阈值并触发误禁用。
            today = bj_today()
            dates = src.get("fail_dates", [])
            if dates and dates[-1] == today:
                dates[-1] = today          # 同日重跑：只刷新日期，不累加计数
            else:
                src["fail_streak"] = src.get("fail_streak", 0) + 1
                dates.append(today)
            src["fail_dates"] = dates[-5:]
            # 自动禁用防线：连续失败 ≥3 天且失败跨越 ≥2 个日期
            # （规范第一篇 7.3）
            distinct_days = len(set(src["fail_dates"][-3:]))
            if src["fail_streak"] >= FAIL_DISABLE_THRESHOLD and distinct_days >= 2:
                src["enabled"] = False
                src["disabled_at"] = today
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
    report = write_report(date_str, results, reg)
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
