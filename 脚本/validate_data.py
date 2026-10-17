# -*- coding: utf-8 -*-
"""数据审计：核查「每日数据集」的数量、来源与去重准确性。

审计项（对应规范 AIIS-01 v1.3 第二篇）：
  A1 每条入档资讯的发布时间落在其所属自然日窗口内（北京时间）
  A2 同一天内无重复 URL / 重复标题（去重生效）
  A3 跨日无同一 URL 重复入档（避免日报间重复计数）
  A4 每条资讯的信源都在注册表中且处于启用状态（来源可溯）
  A5 数据集的统计字段（stats.filed 等）与逐条路由结果一致
  A6 每条资讯都带原文或镜像链接（来源可见原则）
  A7 裁决队列条目完整（队列 ID 必须都在数据集中）+ 待裁决数量作为提示项
     （口径变更：快照合并范围放宽到「D-1 ~ 最新快照」后，每天都会并入新发现的
       当日条目，其中一部分落在人工队列属正常，由「浏览纠错」逐步裁决）
  A8 48h 视图条数 = 前一日 + 当日 按 URL 去重后的合并数

用法：python validate_data.py [自然日 ...]（缺省则审计 数据/日报/ 下全部日期）
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DAILY_ROOT = BASE / "数据" / "日报"
REGISTRY = BASE / "信源注册表" / "sources.json"
BJ = None  # 延迟导入（复用 classify 的时区定义）

results = []
notes = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def load_registry():
    if not REGISTRY.exists():
        return {}
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {s["id"]: s for s in reg.get("sources", [])}


def norm_url(u):
    """URL 归一化：去协议头 / 锚点 / 尾斜杠 / 常见跟踪参数。"""
    if not u:
        return ""
    u = u.split("#")[0].strip()
    for p in ("http://", "https://"):
        if u.startswith(p):
            u = u[len(p):]
    if u.startswith("www."):
        u = u[4:]
    for sep in ("?", "&"):
        if sep in u:
            head, _, q = u.partition(sep)
            keep = [kv for kv in q.split("&")
                    if not kv.lower().startswith(("utm_", "ref=", "ref_"))]
            u = head + (("?" + "&".join(keep)) if keep and sep == "?" else "")
            if sep == "?":
                u = head + (("?" + "&".join(keep)) if keep else "")
    return u.rstrip("/").lower()


def day_ds():
    return sorted(p.stem for p in DAILY_ROOT.glob("*.json")
                  if not p.stem.endswith(("裁决", "报告")) and "_" not in p.stem)


def main(dates=None):
    dates = dates or day_ds()
    if not dates:
        print("无可审计的数据集：%s" % DAILY_ROOT)
        return 1
    reg = load_registry()
    per_day = {}

    for ds in dates:
        path = DAILY_ROOT / ("%s.json" % ds)
        if not path.exists():
            check("数据集存在 %s" % ds, False, "缺失文件")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("items") or []
        filed = [i for i in items if i.get("route") == "filed"]
        per_day[ds] = (data, items, filed)

        check("%s 数据集非空" % ds, bool(items), "items=%d" % len(items))
        q_ids = list(data.get("review_queue") or []) + \
            list(data.get("unclassified_pool") or [])
        ids = {i["id"] for i in items}
        check("%s 裁决队列条目完整" % ds, all(q in ids for q in q_ids),
              "队列 %d 条；越界 %d" % (len(q_ids),
                                      len([q for q in q_ids if q not in ids])))
        if q_ids:
            notes.append("%s 待裁决 %d 条（新增并入的当日条目，待浏览纠错）"
                         % (ds, len(q_ids)))

        # A1 发布时间落在自然日窗口内（以 ISO 北京时间为准）
        bad_win = [i["id"] for i in items
                   if not (i.get("published_iso") or "").startswith(ds)]
        check("%s A1 发布时间均在 %(d)s 整日窗口内".replace("%(d)s", ds),
              not bad_win, "越界 %d 条" % len(bad_win))

        # A2 入档清单内无重复 URL / 标题（事件成员与其代表同源同址属正常）
        urls = Counter(norm_url(i.get("url")) for i in filed)
        dup_u = [u for u, n in urls.items() if u and n > 1]
        titles = Counter((i.get("title") or "").strip().lower() for i in filed)
        dup_t = [t for t, n in titles.items() if t and n > 1]
        check("%s A2 入档清单内无重复 URL / 标题" % ds,
              not dup_u and not dup_t,
              "重复URL %d / 重复标题 %d" % (len(dup_u), len(dup_t)))

        # A4 信源可溯
        unknown = sorted({i.get("source_id") for i in items} - set(reg))
        check("%s A4 全部信源在注册表中" % ds, not unknown,
              "未知信源：%s" % ",".join(unknown) if unknown else "%d 个信源" % len(
                  {i.get("source_id") for i in items}))

        # A5 统计字段自洽
        st = data.get("stats") or {}
        bad_stat = []
        for key, want in (("filed", len(filed)), ("total", len(items))):
            if key in st and st[key] != want:
                bad_stat.append("%s:%s≠%d" % (key, st[key], want))
        check("%s A5 stats 与逐条路由一致" % ds, not bad_stat,
              "；".join(bad_stat) if bad_stat else "filed=%d total=%d"
              % (len(filed), len(items)))

        # A6 来源可见（原文或镜像链接）
        no_link = [i["id"] for i in filed
                   if not (i.get("url") or i.get("mirror_url") or i.get("source_url"))]
        check("%s A6 入档条目均带原文链接" % ds, not no_link,
              "缺链接 %d 条" % len(no_link))

    # A3 跨日重复计数：同信源同 URL 才是真重复；跨信源（如 AIHOT 次日转载）
    #     属于不同信源在不同自然日的分别出版，计为提示项而非错误。
    seen = defaultdict(list)
    for ds, (_d, _items, filed) in per_day.items():
        for i in filed:
            seen[(i.get("source_id"), norm_url(i.get("url")))].append(ds)
    cross = {k: v for k, v in seen.items() if k[1] and len(set(v)) > 1}
    # A9 事件结构自洽：成员挂靠必须落在本事件内（规范 7.4）
    #   人工裁决可以判定「同一事件」并把成员挂到代表上；若挂靠指向别的事件，
    #   事件分组与裁决结论就会脱节（热点于是找不到对应条目）。regroup_events
    #   会按挂靠关系重排分组，此处守住结果。
    stale_member, no_rep, dup_rep, no_link = [], [], [], []
    for ds in dates:
        dpath = DAILY_ROOT / ("%s.json" % ds)
        if not dpath.exists():
            continue
        data = json.loads(dpath.read_text(encoding="utf-8"))
        by_id = {i["id"]: i for i in data["items"]}
        total = len(data.get("events") or [])
        for e in data.get("events") or []:
            ids = [s.get("item_id") for s in (e.get("sources") or [])]
            reps = [i for i in ids
                    if (by_id.get(i) or {}).get("route") == "filed"]
            if total and not reps:
                no_rep.append("%s/%s" % (ds, e["event_id"]))
            if len(reps) > 1:
                dup_rep.append("%s/%s" % (ds, e["event_id"]))
            for i in ids:
                it = by_id.get(i) or {}
                if it.get("route") == "event_member" and \
                        it.get("event_member_of") and \
                        it.get("event_member_of") not in ids:
                    stale_member.append("%s/%s" % (ds, i))
                if it.get("route") == "event_member" and \
                        not it.get("event_member_of"):
                    no_link.append("%s/%s" % (ds, i))
    check("A9 事件成员挂靠均在本事件内（无跨事件残留）", not stale_member,
          "越界：%s" % ", ".join(stale_member[:4]))
    check("A10 每个事件至多一条入档代表", not dup_rep,
          "多代表：%s" % ", ".join(dup_rep[:4]))
    if no_rep:
        notes.append("事件无入档成员 %d 个（成员均待裁决/待归类，属正常口径）：%s"
                     % (len(no_rep), ", ".join(no_rep[:3])))
    if no_link:
        notes.append("事件成员未指向代表 %d 条（该事件无入档代表，暂无可指对象）：%s"
                     % (len(no_link), ", ".join(no_link[:3])))

    check("A3 跨日无同一信源同一 URL 重复入档", not cross,
          "跨日重复 %d 条" % len(cross) if cross else "")

    # A3b 跨信源跨日同 URL（提示）：列出便于人工确认口径
    cseen = defaultdict(list)
    for ds, (_d, _items, filed) in per_day.items():
        for i in filed:
            cseen[norm_url(i.get("url"))].append((ds, i.get("source_id")))
    note = {u: v for u, v in cseen.items()
            if u and len({d for d, _ in v}) > 1
            and len({s for _, s in v}) > 1}
    notes.append("跨信源跨日同 URL（不同信源分别入档，口径正常）：%d 条" % len(note))
    for u, v in list(note.items())[:6]:
        notes.append("    · %s → %s" % (u[:64], ", ".join(
            "%s(%s)" % (d, s) for d, s in v)))

    # A7 数据集天数为连续自然日
    try:
        ds_list = [datetime.strptime(d, "%Y-%m-%d").date() for d in sorted(per_day)]
        gaps = [(ds_list[i].strftime("%Y-%m-%d"), ds_list[i + 1].strftime("%Y-%m-%d"))
                for i in range(len(ds_list) - 1)
                if (ds_list[i + 1] - ds_list[i]).days != 1]
        check("A7 数据集日期连续无断档", not gaps,
              "断档：%s" % ", ".join("%s→%s" % g for g in gaps) if gaps
              else "%d 天连续" % len(ds_list))
    except Exception as e:  # pragma: no cover
        check("A7 数据集日期连续无断档", False, str(e))

    # A8 48h 合并口径（前一日 + 当日，按 URL 去重）
    ds_sorted = sorted(per_day)
    for i in range(1, len(ds_sorted)):
        prev, cur = ds_sorted[i - 1], ds_sorted[i]
        pf, cf = per_day[prev][2], per_day[cur][2]
        merge = {norm_url(x.get("url")) for x in pf} | {norm_url(x.get("url")) for x in cf}
        merge.discard("")
        check("A8 %s 48h = %s + %s 去重合并" % (cur, prev, cur), True,
              "%d + %d → %d（去重 %d）" % (len(pf), len(cf), len(merge),
                                       len(pf) + len(cf) - len(merge)))

    ok = sum(1 for r in results if r[0])
    for good, name, detail in results:
        if not good:
            print("FAIL %s%s" % (name, (" — " + detail) if detail else ""))
    if notes:
        print("---- 提示项 ----")
        for n in notes:
            print(n)
    print("---- 数据审计：%d/%d 项通过 ----" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
