#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按数据范围重建「受影响自然日」的日报数据集（分类 + 裁决的批量编排）。

**为什么要重建多天（而不是只建当天）**
抓取快照含多日历史：一次抓取返回的内容里既有当日发布的，也有前一日晚间发布的。
一个自然日 D 的完整内容分散在 D-1 / D / D+1 三个快照目录里，只建当天会让 D 日
在当天抓取时刻之后的内容永久缺失，因此必须在次日快照到位后重建一次。

**重建范围由数据推算，不写死天数**
以「全部快照目录（巡检 数据/快照/ + 回溯 数据/回溯/）」为准：每个快照日 S 影响
S-1 与 S 两个自然日，取其并集作为候选集，按时间升序逐日重建。快照保留多久，
就能重建多久，天数不设上限。

**逐日流程**
    classify.py  --date D              → 重算分类 / 去重 / 事件 / 双输出
    adjudicate.py --date D --decisions <D 的裁决表> --partial
                                       → 复用已有裁决；重建后新增的待裁决条目
                                         保留在队列（不静默丢弃、不报错中断）

用法：
    python rebuild_days.py                      # 重建全部受影响自然日
    python rebuild_days.py --from 2026-10-13    # 只重建该日及之后
    python rebuild_days.py --dry-run            # 只列范围与条数预览，不落盘
    python rebuild_days.py --no-adjudicate      # 只跑分类，不动裁决
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SNAPSHOT_ROOT = BASE / "数据" / "快照"
BACKFILL_ROOT = BASE / "数据" / "回溯"
DAILY_ROOT = BASE / "数据" / "日报"
HERE = Path(__file__).resolve().parent
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def snapshot_dates():
    """全部快照日（巡检 + 回溯），升序。"""
    days = set()
    for root in (SNAPSHOT_ROOT, BACKFILL_ROOT):
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if d.is_dir() and DAY_RE.match(d.name):
                days.add(d.name)
    return sorted(days)


def affected_days(snap_days):
    """受影响自然日 = 每个快照日 S 影响的 {S-1, S} 之并集（升序）。"""
    out = set()
    for s in snap_days:
        d0 = datetime.strptime(s, "%Y-%m-%d")
        out.add(s)
        out.add((d0 - timedelta(days=1)).strftime("%Y-%m-%d"))
    return sorted(out)


def decisions_path(day):
    p = DAILY_ROOT / ("%s_自然日裁决.json" % day)
    return p if p.exists() else None


def run(cmd):
    r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def read_dataset(day):
    """读回落盘后的真实结果（裁决会改变路由，故不能只看分类阶段的输出）。"""
    p = DAILY_ROOT / ("%s.json" % day)
    if not p.exists():
        return None
    o = json.loads(p.read_text(encoding="utf-8"))
    c = {}
    for it in o["items"]:
        c[it["route"]] = c.get(it["route"], 0) + 1
    return {"filed": c.get("filed", 0), "review": c.get("review", 0),
            "unclassified": c.get("unclassified", 0),
            "event_member": c.get("event_member", 0),
            "excluded": c.get("excluded", 0), "items": len(o["items"])}


def main():
    ap = argparse.ArgumentParser(description="按数据范围批量重建日报数据集")
    ap.add_argument("--from", dest="d_from", help="起始自然日（含）")
    ap.add_argument("--to", dest="d_to", help="结束自然日（含）")
    ap.add_argument("--dry-run", action="store_true", help="只列范围，不落盘")
    ap.add_argument("--no-adjudicate", action="store_true", help="只跑分类")
    ap.add_argument("--keep-queue", action="store_true",
                    help="裁决时允许保留未覆盖的待裁决条目（默认即 --partial 行为）")
    args = ap.parse_args()

    snaps = snapshot_dates()
    if not snaps:
        raise SystemExit("没有快照目录：%s" % SNAPSHOT_ROOT)
    days = affected_days(snaps)
    if args.d_from:
        days = [d for d in days if d >= args.d_from]
    if args.d_to:
        days = [d for d in days if d <= args.d_to]
    if not days:
        raise SystemExit("没有需要重建的自然日")

    print("快照日（%d）：%s" % (len(snaps), "、".join(snaps)))
    print("重建范围（%d 天）：%s ~ %s" % (len(days), days[0], days[-1]))
    if args.dry_run:
        built = sorted(p.stem for p in DAILY_ROOT.glob("????-??-??.json"))
        print("现有数据集：%s" % "、".join(built))
        print("（--dry-run 未执行任何重建）")
        return

    ok = fail = skip = 0
    rows = []
    for day in days:
        code, out = run([sys.executable, "classify.py", "--date", day])
        if code != 0:
            if "没有可解析的条目" in out:
                skip += 1
                rows.append((day, "—", "跳过：该日无内容", ""))
            else:
                fail += 1
                rows.append((day, "—", "失败", out.strip().splitlines()[-1][:60]))
            continue
        note = ""
        dec = decisions_path(day)
        if args.no_adjudicate:
            note = "未跑裁决（--no-adjudicate）"
        elif not dec:
            # 没有该日裁决表时不要用内置判例（判例按日绑定，会全部失配）
            note = "无裁决表，仅规则分流"
        else:
            cmd = [sys.executable, "adjudicate.py", "--date", day,
                   "--decisions", str(dec), "--partial"]
            acode, aout = run(cmd)
            if acode != 0:
                fail += 1
                rows.append((day, "—", "裁决失败", aout.strip().splitlines()[-1][:60]))
                continue
            note = "裁决表：%s" % dec.name
            m = re.search(r"跳过陈旧裁决 (\d+) 条", aout)
            if m:
                note += "（陈旧 %s）" % m.group(1)
            m = re.search(r"保留待裁决 (\d+) 条", aout)
            if m:
                note += "（新增待裁决 %s）" % m.group(1)
        ok += 1
        d = read_dataset(day) or {}
        queue = "%d/%d" % (d.get("review", 0), d.get("unclassified", 0))
        rows.append((day, d.get("filed", "—"), "重建完成",
                     "队列 %s · 事件成员 %s · 排除 %s · %s"
                     % (queue, d.get("event_member", 0), d.get("excluded", 0), note)))

    print("\n== 重建结果 ==")
    for day, filed, status, note in rows:
        print("  %s  入档 %-5s %s %s" % (day, filed, status, note))
    print("完成 %d 天，跳过 %d 天，失败 %d 天" % (ok, skip, fail))
    if fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
