# -*- coding: utf-8 -*-
"""视图投影一致性校验（L2 ↔ L1）：保证投影不漂移、不泄漏业务字段。

校验六类：
  A 契约完整：schema / spec_version / date / window_hours / 必需字段齐全
  B 与事实源逐条比对：24h 投影条目集 == L1 中 route=filed 的条目集，字段值逐一相等
  C 统计自洽：stats 各项与投影 items 重算结果一致
  D 48h 口径：与 merge_day_items 的唯一实现结果一致，且是 24h 的超集
  E 索引一致性：index 的条数 / 字节数 / sha256 与磁盘文件实测一致，latest 取最近完整日
  F 无业务字段泄漏：投影不得出现 route / review_queue / noise_reason / 事件成员等加工层字段
  G 无陈旧投影文件（目录内每个文件都被 index 覆盖）
  H 展现语义：序号/顺序/节点读数/标签计数由 L2 唯一确定，且与 L1 同一输入逐条同序
"""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "数据" / "日报"
VIEW = ROOT / "数据" / "视图"
BJ = timezone(timedelta(hours=8))

SKIP = {"summaries", "datasets", "skipped_snapshots", "partial_snapshots"}

results = []
notes = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def norm(s):
    return (s or "").strip()


def main():
    if not (VIEW / "index.json").exists():
        raise SystemExit("缺少 %s —— 先运行 view_projection.py" % (VIEW / "index.json"))
    index = json.loads((VIEW / "index.json").read_text(encoding="utf-8"))

    import classify as CLS
    import view_projection as VP

    dailies = VP.load_dailies()
    by_day = dict(dailies)
    coverage = VP.snapshot_coverage()

    # ---------- A 契约完整 ----------
    for k in ("schema", "spec_version", "generated_at", "windows",
              "latest", "newest", "days"):
        check("A1 index 含字段 %s" % k, k in index)
    check("A2 index schema == VIEW-01", index.get("schema") == VP.SCHEMA)
    check("A3 index windows == [24, 48]", index.get("windows") == [24, 48])

    per_day = {}
    for date_str, daily in dailies:
        for w in VP.WINDOWS:
            f = VIEW / ("%s_%dh.json" % (date_str, w))
            check("A4 存在投影 %s" % f.name, f.exists())
            if not f.exists():
                continue
            text = f.read_text(encoding="utf-8")
            v = json.loads(text)
            per_day[(date_str, w)] = (v, text)
            for k in ("schema", "spec_version", "date", "window_hours", "live",
                      "generated_at", "meta", "stats", "hot_events", "items"):
                check("A5 %s_%dh 含字段 %s" % (date_str, w, k), k in v)
            check("A6 %s_%dh date/window 正确" % (date_str, w),
                  v.get("date") == date_str and v.get("window_hours") == w)
            check("A7 %s_%dh meta 完整" % (date_str, w),
                  all(v.get("meta", {}).get(k) for k in ("md", "full", "weekday")))

    # ---------- B 与事实源逐条比对 ----------
    for date_str, daily in dailies:
        v, _t = per_day[(date_str, 24)]
        src_filed = [i for i in daily["items"] if i.get("route") == "filed"]
        src_ids = {i["id"] for i in src_filed}
        got_ids = {i["id"] for i in v["items"]}
        check("B1 %s 24h 条目集与 L1 一致" % date_str, src_ids == got_ids,
              "投影 %d / 事实源 %d" % (len(got_ids), len(src_ids)))
        by_src = {i["id"]: i for i in src_filed}
        diff = []
        for it in v["items"]:
            o = by_src.get(it["id"])
            if not o:
                continue
            for k in ("title", "node", "subcategory", "region", "country",
                      "published_bj", "url", "importance", "source_name"):
                a = norm(it.get(k)) if isinstance(it.get(k), str) else it.get(k)
                b = norm(o.get(k)) if isinstance(o.get(k), str) else o.get(k)
                if a != b:
                    diff.append("%s.%s" % (it["id"][-4:], k))
        check("B2 %s 投影字段值与事实源逐一相等" % date_str, not diff,
              "不一致 %d 处：%s" % (len(diff), ", ".join(diff[:5])))
        check("B3 %s 入档条目均有可点链接" % date_str,
              all(norm(i.get("url")) for i in v["items"]),
              "缺链接 %d 条" % sum(1 for i in v["items"] if not norm(i.get("url"))))

    # ---------- C 统计自洽 ----------
    for (date_str, w), (v, _t) in per_day.items():
        st, items = v["stats"], v["items"]
        by_node, by_country, by_imp = {}, {}, {}
        for i in items:
            by_node[i["node"]] = by_node.get(i["node"], 0) + 1
            by_country[i.get("country") or "UN"] = \
                by_country.get(i.get("country") or "UN", 0) + 1
            key = i.get("importance") or "常规"
            by_imp[key] = by_imp.get(key, 0) + 1
        check("C1 %s_%dh stats.filed 与 items 一致" % (date_str, w),
              st.get("filed") == len(items))
        check("C2 %s_%dh stats.sources 一致" % (date_str, w),
              st.get("sources") == len({i.get("source_name") for i in items}))
        check("C3 %s_%dh stats.by_node 一致" % (date_str, w),
              st.get("by_node") == by_node)
        check("C4 %s_%dh stats.by_country 一致" % (date_str, w),
              st.get("by_country") == by_country)
        check("C5 %s_%dh stats.by_importance 一致" % (date_str, w),
              st.get("by_importance") == by_imp)
        check("C6 %s_%dh stats.china / headline 一致" % (date_str, w),
              st.get("china") == sum(1 for i in items if i.get("region") == "china")
              and st.get("headline") == sum(1 for i in items
                                            if i.get("importance") == "头条"))
        check("C7 %s_%dh stats.hot_events 与 hot_events 一致" % (date_str, w),
              st.get("hot_events") == len(v["hot_events"]) and
              all(e.get("source_count", 0) >= 2 for e in v["hot_events"]))
        check("C8 %s_%dh 节点归属无空值" % (date_str, w),
              all(i.get("node") for i in items),
              "缺节点 %d 条" % sum(1 for i in items if not i.get("node")))

    # ---------- D 48h 口径 ----------
    for date_str, daily in dailies:
        prev = by_day.get((datetime.strptime(date_str, "%Y-%m-%d")
                           - timedelta(days=1)).strftime("%Y-%m-%d"))
        exp_items, _ev = VP.merge_day_items(prev, daily)
        v48, _t = per_day[(date_str, 48)]
        ids48 = {i["id"] for i in v48["items"]}
        # 投影只输出面板可见的 `filed` 条目；`event_member` 是交叉事件的非代表
        # 成员，参与归组（热点区的 source_count 靠它们）但不出现在面板里。
        # 故期望集合同样按 filed 过滤，否则口径不同必然不等。
        exp_filed = {i["id"] for i in exp_items if i.get("route") == "filed"}
        check("D1 %s 48h 与 merge_day_items 唯一实现一致" % date_str,
              ids48 == exp_filed,
              "投影 %d / 期望 %d" % (len(ids48), len(exp_filed)))
        v24, _t = per_day[(date_str, 24)]
        ids24 = {i["id"] for i in v24["items"]}
        check("D2 %s 48h ⊇ 24h（更宽窗口只能是超集）" % date_str,
              ids24 <= ids48,
              "24h 独有 %d 条" % len(ids24 - ids48))
        # 回归锁：48h = 前日 + 当日，热点（多信源交叉事件）**不得比24h 少**。
        # 早先 48h 合并只取 route=="filed"，把交叉事件的非代表成员
        # （route=event_member）全滤掉，重算事件时每事件只剩代表一条，
        # source_count 一律退化为 1 → 48h 热点整区清零（实证 10-13：24h 6 条、
        # 48h 0 条）。
        # 同一事件在两窗口的**标题可能不同**：入档代表按「权威度高→发布最早」选，
        # 48h 窗口里若前日存在权威度更高的报道，代表会换成那一条（实测 Muse Spark
        # 事件 24h 落 10-16、48h 落 10-15，信源数 2→4）。故不能用标题比对，
        # 改用**成员 URL 集合**：24h 的每个热点，其全部成员都必须出现在 48h 里。
        def urls(h):
            return {s.get("url") for s in (h.get("members") or []) if s.get("url")}
        u48 = [urls(h) for h in v48.get("hot_events", [])]
        missing = []
        for h in v24.get("hot_events", []) or []:
            u = urls(h)
            if u and not any(u <= x for x in u48):
                missing.append((h.get("canonical_title") or "")[:40])
        check("D3 %s 48h 热点覆盖 24h 全部热点成员（宽窗口不得丢热点）" % date_str,
              not missing,
              "24h 有 %d 条热点在 48h 中找不到同成员事件：%s" % (len(missing), missing[:2]))

        # D4 热点必须是**真交叉**：`source_count` 数的是独立报道的信源数，不是
        # 「有几家转载过同一篇原文」。聚合策展站与社区站会把原文原样转载（URL 相同），
        # 按 source_id 去重会把一篇报道算成 2 个信源，凭一条转载混进热点区、
        # 并顺带污染头条判定。
        # 断言口径与 classify._independent_source_ids 一致：**独立报道数 ≥ 信源数**，
        # 且落在热点区的事件至少有 2 篇不同 URL 的独立报道。
        def indep_reports(h):
            return len({CLS.norm_url(m.get("url") or "")
                        for m in (h.get("members") or [])} - {""})
        fake = []
        for h in (v24.get("hot_events") or []) + (v48.get("hot_events") or []):
            n_indep = indep_reports(h)
            if h.get("source_count", 0) > n_indep:
                fake.append("信源%d>独立报道%d" % (h["source_count"], n_indep))
            if n_indep < 2:
                fake.append("仅%d篇独立报道" % n_indep)
        check("D4 %s 热点均为真实多信源交叉（转载不虚增信源）" % date_str,
              not fake,
              "伪交叉 %d 处：%s" % (len(fake), fake[:2]))
        if prev:
            note = "" if len(ids48) >= len(ids24) else "（合并后反而变少，需排查去重键）"
            if note:
                notes.append("%s 48h 合并 %s" % (date_str, note))

    # ---------- E 索引一致性 ----------
    for date_str, meta in index["days"].items():
        for w in VP.WINDOWS:
            f = VIEW / ("%s_%dh.json" % (date_str, w))
            text = f.read_text(encoding="utf-8")
            rec = meta["windows"].get(str(w))
            check("E1 %s_%dh 索引含条数/字节/sha256" % (date_str, w),
                  isinstance(rec, dict)
                  and {"filed", "bytes", "sha256"} <= set(rec or {}))
            if not isinstance(rec, dict):
                continue
            check("E2 %s_%dh 索引条数一致" % (date_str, w),
                  rec["filed"] == json.loads(text)["stats"]["filed"])
            check("E3 %s_%dh 索引字节数一致" % (date_str, w),
                  rec["bytes"] == len(text.encode("utf-8")),
                  "索引 %d / 实测 %d" % (rec["bytes"], len(text.encode("utf-8"))))
            check("E4 %s_%dh 索引 sha256 一致" % (date_str, w),
                  rec["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])
    complete = [d for d in index["days"]
                if VP.is_complete_day(d, coverage)]
    check("E5 index.latest = 最近完整自然日",
          index["latest"] == (complete[-1] if complete else index["newest"]),
          "latest=%s 完整日=%s" % (index["latest"], complete[-1] if complete else "—"))
    check("E6 index.newest = 数据集最新一日",
          index["newest"] == dailies[-1][0])
    check("E7 latest ≤ newest 且两者都在 index.days 内",
          index["latest"] in index["days"] and index["newest"] in index["days"])
    check("E8 投影 day 集合与事实源一致",
          set(index["days"]) == {d for d, _ in dailies})

    # ---------- F 无业务字段泄漏 ----------
    leaked = set()
    for (date_str, w), (v, _t) in per_day.items():
        blob = json.dumps(v, ensure_ascii=False)
        for bad in ("review_queue", "unclassified_pool", "noise_reason",
                    "event_member_of", "summary_compressed\": false, \"route",
                    "\"route\"", "fetch_runs", "filtered_by_source"):
            if bad in blob:
                leaked.add(bad)
    check("F1 投影不含加工层业务字段", not leaked, "泄漏：%s" % ", ".join(sorted(leaked)))
    for (date_str, w), (v, _t) in per_day.items():
        check("F2 %s_%dh 条目字段在契约白名单内" % (date_str, w),
              all(set(i) <= {
                  "num", "id", "title", "summary", "summary_full",
                  "summary_compressed",
                  "node", "node_name", "subcategory", "importance",
                  "source_id", "source_name", "source_tier", "authority",
                  "country", "country_name", "region", "published_bj", "time_basis",
                  "url", "mirror_url", "tags_b", "tags_c",
                  "hot_event", "hot_sources",
                  # 双语附加层（译文只作对照，不替换原文）
                  "lang", "title_alt", "summary_alt", "summary_full_alt",
                  "alt_reviewed", "summary_full_alt_partial"} for i in v["items"]))

    # ---------- H 展现语义（顺序/序号/节点/标签，L3 不得自行推算） ----------
    iso_map = {}
    for _d, _daily in dailies:
        for _i in _daily["items"]:
            iso_map[_i["id"]] = _i.get("published_iso") or ""
    for (date_str, w), (v, _t) in per_day.items():
        items = v["items"]
        tag = "%s_%dh" % (date_str, w)
        check("H1 %s 序号从 01 连续且与数组顺序一致" % tag,
              [i.get("num") for i in items] == ["%02d" % k
                                                for k in range(1, len(items) + 1)])
        rank = {k: i for i, k in enumerate(VP.NODE_ORDER)}
        imp = VP.IMPORTANCE_RANK
        order_ok = all(
            (rank.get(items[a]["node"], 99), imp.get(items[a]["importance"], 3))
            <= (rank.get(items[b]["node"], 99), imp.get(items[b]["importance"], 3))
            for a, b in zip(range(len(items) - 1), range(1, len(items))))
        check("H2 %s 条目按节点→重要度成组有序" % tag, order_ok)
        inner_time_ok = all(
            iso_map[items[a]["id"]] >= iso_map[items[b]["id"]]
            for a, b in zip(range(len(items) - 1), range(1, len(items)))
            if (items[a]["node"], items[a]["importance"])
            == (items[b]["node"], items[b]["importance"]))
        check("H3 %s 同节点同重要度内按时间新→旧" % tag, inner_time_ok)
        check("H4 %s 主轴节点：五节点、计数与条目一致" % tag,
              [n["key"] for n in v["nodes"]] == VP.NODE_ORDER and
              all(n["count"] == sum(1 for i in items if i["node"] == n["key"])
                  for n in v["nodes"]) and
              all(n["headline"] == sum(1 for i in items if i["node"] == n["key"]
                                       and i["importance"] == "头条")
                  for n in v["nodes"]))
        by_tag = {}
        for i in items:
            for t in i["tags_b"]:
                by_tag[t] = by_tag.get(t, 0) + 1
        check("H5 %s 标签计数与条目一致" % tag, by_tag == v["stats"]["by_tag"])
        # 与 L1 事实源逐条同序：L2 顺序 == display_order(同一输入)
        prev_day = by_day.get((datetime.strptime(date_str, "%Y-%m-%d")
                               - timedelta(days=1)).strftime("%Y-%m-%d"))
        src = (by_day[date_str]["items"] if w == 24
               else VP.merge_day_items(prev_day, by_day[date_str])[0])
        src = [i for i in src if i.get("route") == "filed"]
        check("H6 %s 顺序 == display_order(事实源)" % tag,
              [(i["id"], i.get("num")) for i in items]
              == [(i["id"], i.get("num")) for i in VP.display_order(src)])

        # 热点 ↔ 面板：canonical 必须是本视图可见的入档条目，且带环节与序号；
        # 卡片上的多信源标记必须与对应事件的 source_count 一致
        items_by_id = {i["id"]: i for i in items}
        bad_link, bad_mark = [], []
        for e in v["hot_events"]:
            cid = e.get("canonical_item")
            c = items_by_id.get(cid) if cid else None
            # 允许「本视图无入档条目」：此时 canonical_item 必须为 null 且无定位信息
            ok_link = ((c is not None and e.get("canonical_num") == c.get("num")
                        and e.get("canonical_node") == c.get("node")
                        and bool(e.get("canonical_node_name")))
                       or (c is None and cid is None
                           and e.get("canonical_num") is None
                           and not e.get("canonical_node")))
            if not ok_link or not e.get("canonical_title"):
                bad_link.append("%s→%s" % (e.get("event_id"), cid))
            marked = [i for i in items if i.get("hot_event") == e.get("event_id")]
            # 与 H7 同一口径：本视图无入档条目时 canonical_item 为 null，
            # 此时「恰一条代表」应表述为「没有卡片带该热点标记」（期望空列表）。
            # 旧实现固定写成 [cid]（= [None]），在 canonical 为 null 的视图必假报 FAIL。
            expect = [cid] if cid else []
            if ([i["id"] for i in marked] != expect
                    or any(i.get("hot_sources") != e.get("source_count")
                           for i in marked)):
                bad_mark.append(e.get("event_id"))
        check("H7 %s 每个热点条目的代表 = 本视图入档条目（含环节与序号）" % tag,
              not bad_link, "失配：%s" % ", ".join(bad_link))
        check("H8 %s 卡片多信源标记与事件一致（每事件恰一条代表）" % tag,
              not bad_mark, "异常：%s" % ", ".join(bad_mark))
        check("H9 %s 无热点标记的卡片 hot_sources 为 0" % tag,
              all(i.get("hot_sources") == 0 for i in items
                  if not i.get("hot_event")))

    # ---------- G 无陈旧文件 ----------
    wanted = {("index.json" if False else "%s_%dh.json" % (d, w))
              for d in index["days"] for w in VP.WINDOWS} | {"index.json"}
    actual = {f.name for f in VIEW.iterdir() if f.is_file()
              and not f.name.endswith(".tmp")}
    check("G1 视图目录无陈旧/多余文件", actual <= wanted,
          "多余：%s" % ", ".join(sorted(actual - wanted)))
    leftover = [f.name for f in VIEW.iterdir() if f.name.endswith(".tmp")]
    check("G2 无写入残留（.tmp）", not leftover, "残留：%s" % ", ".join(leftover))

    # ---------- 汇总 ----------
    ok = sum(1 for r in results if r[0])
    for good, name, detail in results:
        if not good:
            print("FAIL %s%s" % (name, (" — " + detail) if detail else ""))
    if notes:
        print("---- 提示项 ----")
        for n in notes:
            print(" · " + n)
    print("---- 视图投影校验：%d/%d 项通过 ----" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
