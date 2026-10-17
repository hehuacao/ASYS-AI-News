# -*- coding: utf-8 -*-
"""L2 视图投影层 —— 把 L1 事实源翻译成展现语义的薄投影。

为什么需要这一层
----------------
L1（`数据/日报/<自然日>.json`）是**加工层**的内部结构：含 `route`、
`review_queue`、`unclassified_pool`、`noise_reason`、快照溯源等字段。
前端直接读它，等于把业务逻辑泄漏到展现层；而且 24h/48h 合并口径若在两处
各自实现，早晚会漂移。

本层只做一件事：**把事实源翻译成「前端零业务逻辑」可消费的投影**，
并且是24h/48h 合并口径与展现排序编号的**唯一实现**。

产物
----
   数据/视图/index.json          目录索引：最近完整日、各日双窗口条数与校验值
   数据/视图/<日期>_<窗口>.json单日单窗口投影（窗口 = 24 / 48）

约束
----
- 投影**只由本模块生成**，禁止手工编辑；一致性由 `validate_view.py` 逐条校验。
- 契约带版本号（`SCHEMA`）：字段增删不破坏旧页面。
- 投影只含数据字段，不含样式、颜色与布局信息。
- 写入为**原子替换**（临时文件 + os.replace）：生成失败不会留下半个文件，
  页面只会读到上一版完整投影。
- 投影**不含 SVG / 颜色 / 布局**等表现层内容，只带语义字段（如国家 ISO 码）。
"""
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY_ROOT = ROOT / "数据" / "日报"
SNAPSHOT_ROOT = ROOT / "数据" / "快照"
VIEW_ROOT = ROOT / "数据" / "视图"

SCHEMA = "VIEW-01"
WINDOWS = (24, 48)
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
BJ = timezone(timedelta(hours=8))

# 主线五节点（规范第二篇 3「AI 产业化价值链」）：顺序即价值推进顺序，
# **全站唯一的节点定义来源**；色值属表现层，留在渲染器（投影不含颜色）。
NODE_DEFS = [
    ("capability", "能力", "CAPABILITY",
     "模型、算法、算力的前沿进展——AI 能做什么的证据",
     "模型、算法、算力的前沿进展"),
    ("product", "产品", "PRODUCT",
     "能力转化为用户可用的产品、工具与开源项目",
     "能力转化为可用的产品与工具"),
    ("industry", "产业", "INDUSTRY",
     "资本、市场与组织——谁在投钱、谁在赚钱",
     "资本、市场与组织动向"),
    ("governance", "治理", "GOVERNANCE",
     "规则、监管、安全与伦理——社会对 AI 的回应",
     "规则、监管、安全与伦理"),
    ("frontier", "趋势", "FRONTIER",
     "方向性信号——正在发生的下一步",
     "方向性信号与前瞻观点"),
]
NODE_ORDER = [n[0] for n in NODE_DEFS]
IMPORTANCE_RANK = {"头条": 0, "重要": 1, "一般": 2}


def display_order(items):
    """条目 → 展现顺序（节点顺序 → 重要度 → 发布时间新→旧）并赋连续序号。

    **展现排序与编号的唯一实现**：L3（渲染层）不再自行排序/编号，离线单文件与
    运行态薄壳因此天然同序，也让两个渲染器之间的逐条比对有意义。
    序号 `num` 在「单日单窗口」内从 01 连续（跨日不续号）。
    """
    rank = {k: i for i, k in enumerate(NODE_ORDER)}
    out = list(items)
    out.sort(key=lambda it: it.get("published_iso") or "", reverse=True)
    out.sort(key=lambda it: (rank.get(it.get("node"), 99),
                             IMPORTANCE_RANK.get(it.get("importance"), 3)))
    for i, it in enumerate(out, 1):
        it["num"] = "%02d" % i
    return out


# ---------------------------------------------------------------- 事实源读取
def spec_version():
    """现行规范版本号：从 classify.py 单一来源取，避免多处写死。"""
    import classify as CLS
    return CLS.SPEC_VERSION


def load_dailies(dates=None):
    """读全部自然日数据集（升序）。dates 为 None 时读 DAILY_ROOT 下全部。"""
    out = []
    for p in sorted(DAILY_ROOT.glob("2026-*.json")):
        day = p.stem
        if dates and day not in dates:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "items" not in data:
            continue
        out.append((day, data))
    return out


# ---------------------------------------------------------------- 完整性判定
def snapshot_coverage():
    """最近一次抓取的时点（北京时间）：数据只能覆盖到这一刻。"""
    latest = None
    dirs = sorted(SNAPSHOT_ROOT.iterdir()) if SNAPSHOT_ROOT.is_dir() else []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.json"):
            try:
                t = json.loads(f.read_text(encoding="utf-8")).get("fetched_at_bj")
                dt = datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
            except Exception:
                continue          # 文件损坏/字段缺失：跳过该源，不影响整体判定
            if latest is None or dt > latest:
                latest = dt
    return latest


def is_complete_day(date_str, coverage_until):
    """自然日 D 是否完整：需存在 D+1 00:00 之后的抓取（隔夜内容才可能补齐）。"""
    if coverage_until is None:
        return False
    end = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=BJ) + timedelta(days=1)
    return end <= coverage_until


# ---------------------------------------------------------------- 48h 合并口径
def merge_day_items(prev_daily, cur_daily):
    """48h 视图：前一日 + 当日条目合并（按 source_id+URL 去重，保留先出现者）。

    **口径唯一实现**：渲染层与投影层都调用本函数，不各自实现。

    条目范围 = 除 `excluded` 外的全部条目。
    带上非入档条目是**热点区成立的前提**：L1 按规范 7.4 把跨信源同一事件的非代表
    条目收敛为 `event_member`，待人工处理的为 `unclassified` / `review`；一个 N 信源
    事件在数据里是「1 条 filed + 若干非入档成员」。若只取 filed，重算事件时每个
    事件只剩代表一条，`source_count` 一律退化为 1，48h 的今日热点会整区清零——
    而 24h 走 L1 已存的完整 events 不受影响，两窗口自相矛盾
    （实证 10-13：24h 有 6 条交叉热点、48h 为 0；10-17：FLUX 3 事件第二条成员
    是 `unclassified`，被滤掉后该事件掉出 48h 热点区）。
    只有 `excluded` 是被噪声闸门判为无关而排除的，不参与归组。
    面板只渲染 `filed`，故带上这些条目不改变卡片区，只修复热点区。
    """
    import classify as CLS
    seen, out = set(), []
    src = ((prev_daily or {}).get("items") or []) + list(cur_daily["items"])
    for it in src:
        if it.get("route") == "excluded":
            continue
        u = (it.get("url") or "").strip()
        k = (it.get("source_id"), u)
        if u and k in seen:
            continue
        if u:
            seen.add(k)
        out.append(copy.deepcopy(it))
    # 合并视图的事件与重要度重算（跨日去重分组）
    events = CLS.dedup_and_merge(out)
    CLS.assign_importance(out)
    return out, events


# ---------------------------------------------------------------- 投影构造
def load_translations():
    """读 L1.5 译表（可再生缓存；缺失即无对照，不报错、不阻塞投影）。"""
    path = ROOT / "数据" / "翻译" / "译表.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def project_items(filed, trans=None):
    """条目 → 展现字段全集（不含 SVG / 颜色等表现层内容）。

    `trans` = L1.5 译表。译文以 `*_alt` 附加，不替换原文——规范 R-02 规定
    **标题即信源原标题、禁止改写**，译文只作对照层，由展现层按需取用。
    """
    trans = trans or {}
    fields = ("num", "id", "title", "summary", "summary_full",
              "summary_compressed",
              "node", "node_name", "subcategory", "importance",
              "source_id", "source_name", "source_tier", "authority",
              "country", "country_name", "region",
              "published_bj", "time_basis", "url", "mirror_url")
    out = []
    for it in filed:
        row = {k: it.get(k) if k not in ("id", "title", "node") else it[k]
               for k in fields}
        row["tags_b"] = it.get("tags_b") or []
        row["tags_c"] = it.get("tags_c") or []
        t = trans.get(it["id"]) or {}
        row["lang"] = t.get("lang") or lang_of(it.get("title") or "")
        row["title_alt"] = t.get("title_alt") or ""
        row["summary_alt"] = t.get("summary_alt") or ""
        row["summary_full_alt"] = t.get("full_alt") or ""
        # 人工定稿标记**稀疏写入**：未校对（绝大多数）不出现，避免每条都带一个
        # 恒定不变的元数据块（provider/model/reviewed 的汇总见视图级 translation）
        if (t.get("trans") or {}).get("reviewed"):
            row["alt_reviewed"] = True
        # 摘要译文**覆盖不全**标记（稀疏）：① L1.5 显式标记（原文过长、段数超限或个别段失败）
        # ② 兜底比例判定——译文长度不足原文 15% 时同样视为覆盖不全。
        #    实测分段翻译后仍有 4 条因模型自行截断而明显偏短（1680 字符原文 → 249 字译文）；
        #    不标出来，详情页就会让读者以为「译文就是全文」——这正是要避免的观感。
        # 英文→中文的长度比约 0.3~0.45，0.15 足以区分「正常压缩」与「被截断」。
        if t.get("full_partial"):
            row["summary_full_alt_partial"] = True
        else:
            src_len = len((it.get("summary_full") or "").strip())
            alt_len = len(row["summary_full_alt"])
            if src_len > 200 and alt_len and alt_len < src_len * 0.15:
                row["summary_full_alt_partial"] = True
        out.append(row)
    return out


def lang_of(text):
    """原文语言判定（与 L1.5 译表同判据，两处不得各写一套）。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    if cjk >= max(2, len(text or "") * 0.2):
        return "zh"
    return "en"


# L1.5 译表：进程启动时读一次（可再生缓存；缺失即无对照层，不阻塞投影）
TRANS = load_translations()


def project_hot_events(events, item_map, filed_map=None):
    """多信源交叉事件 → 可渲染的热点条目（含成员信源与国家，供绘国旗）。

    `filed_map`（= 本视图已入档且已编号的条目）用于给出**入档代表**的定位信息：
    `canonical_num` / `canonical_node` / `canonical_node_name` 是热点条目与下方
    面板建立联系所需的全部信息（「在哪个环节、第几条」），由本层唯一给出，
    展现层不得自行推算（规范第三篇 §8.2）。
    """
    filed_map = filed_map or {}
    hot = [e for e in events if e.get("source_count", 0) >= 2]
    hot.sort(key=lambda e: -e["source_count"])
    out = []
    for e in hot:
        members = []
        for s in (e.get("sources") or []):
            si = item_map.get(s.get("item_id"), {})
            members.append({
                "item_id": s.get("item_id"),
                "source_id": si.get("source_id") or "",
                "source_name": s.get("source_name") or "",
                "authority": s.get("authority"),
                "url": s.get("url") or "",
                "country": si.get("country") or "",
                "country_name": si.get("country_name") or "",
                "region": si.get("region") or "",
            })
        # 入档代表 = **本视图内**承载该事件的可见条目（热点条目定位到面板的落点）。
        # 该事件若在本视图没有任何入档条目（成员全部待裁决/待归类），
        # canonical_item 记为 null —— 该事件仅在热点区呈现，面板里没有对应卡片。
        panel = filed_map.get(e.get("canonical_item"))
        if panel is None:
            alt = [filed_map[s["item_id"]] for s in (e.get("sources") or [])
                   if s.get("item_id") in filed_map]
            alt.sort(key=lambda it: (-(it.get("authority") or 0),
                                     it.get("published_iso") or ""))
            panel = alt[0] if alt else None
        src = panel or item_map.get(e.get("canonical_item")) or {}
        # 「涉及中国」判定：**以面板落点条目（canonical）的 region 为准**，
        # 与卡片 .card-region 的判定同源——两者都看同一张投影里的同一个字段。
        # 早期用 `any(m["region"] == "china" for m in members)`，即「成员里任意一条
        # 被判涉华就整条标中国」；而落点卡片按自身 region 显示，两者会打架：
        # 实证 10-16 的 Muse Spark 事件，48h 窗口落点是Hugging Face（region=global）
        # 的条目，卡片无标记，热点条却挂着中国国旗，看起来像错标。
        # 该事件确有另一成员（The Decoder）被判涉华，但那属于**成员报道**的地域，
        # 不是这条热点（= 落点卡片）的地域，按成员传播会把无关条目染上中国标记。
        # 未入档的事件（panel 为 None）没有落点可比，退回成员口径。
        if panel is not None:
            is_china = (panel.get("region") == "china")
        else:
            is_china = any(m.get("region") == "china" for m in members)
        out.append({
            "event_id": e.get("event_id"),
            "canonical_item": panel.get("id") if panel else None,
            "canonical_title": src.get("title") or "",
            "canonical_title_alt": src.get("title_alt") or "",
            "canonical_lang": src.get("lang") or "",
            "canonical_num": panel.get("num") if panel else None,
            "canonical_node": (panel or {}).get("node") or "",
            "canonical_node_name": (panel or {}).get("node_name") or "",
            "source_count": e.get("source_count", 0),
            "source_ids": e.get("source_ids") or [],
            "max_authority": e.get("max_authority"),
            "china": is_china,
            "members": members,
        })
    return out


def build_view(date_str, daily, window_h, items, events, coverage_until):
    """构造单日单窗口投影 dict。"""
    item_map = {it["id"]: it for it in items}
    # 展现顺序（节点 → 重要度 → 时间新→旧）与序号在此**唯一确定**
    filed = display_order([it for it in items if it.get("route") == "filed"])
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    by_node, by_country, by_imp, by_tag = {}, {}, {}, {}
    for it in filed:
        by_node[it["node"]] = by_node.get(it["node"], 0) + 1
        c = it.get("country") or "UN"
        by_country[c] = by_country.get(c, 0) + 1
        by_imp[it.get("importance") or "常规"] = \
            by_imp.get(it.get("importance") or "常规", 0) + 1
        for t in (it.get("tags_b") or []):
            by_tag[t] = by_tag.get(t, 0) + 1
    l1st = daily.get("stats", {}) or {}
    # 事件 → 入档代表（口径唯一实现：classify.sync_event_canonical）。
    # 本层再兜一次，保证投影里的 canonical_item 恒指向本视图可见的入档条目，
    # 热点条目的「定位到面板」因此永远有落点。
    import classify as CLS
    CLS.regroup_events(items, events)
    CLS.normalize_member_links(items, events)
    CLS.sync_event_canonical(items, events)
    # 先投影条目（含 L1.5 译文），再以**投影后的条目**作为热点的落点来源：
    # 热点标题的对照译文与卡片必须同源，否则两处译文会取自不同实现而漂移。
    items_out = project_items(filed, TRANS)
    filed_map = {r["id"]: r for r in items_out}
    hot = project_hot_events(events, item_map, filed_map)
    hot_of = {h["canonical_item"]: h for h in hot if h.get("canonical_item")}
    for row in items_out:
        h = hot_of.get(row["id"])
        # 卡片侧的「交叉热点」标记：本条是该多信源事件的入档代表
        row["hot_event"] = h["event_id"] if h else None
        row["hot_sources"] = h["source_count"] if h else 0
    # 主轴节点（顺序即价值链推进顺序）：计数 + 头条数，供 L1 主轴与分布面板直读
    nodes = [{
        "key": key, "name": name, "en": en, "desc": desc, "short": short,
        "count": by_node.get(key, 0),
        "headline": sum(1 for it in filed
                        if it["node"] == key and it.get("importance") == "头条"),
    } for key, name, en, desc, short in NODE_DEFS]
    # 译文元信息汇总（视图级）：逐条重复同一份 provider/model/at 没有意义
    providers, models, ats = {}, {}, []
    for it in items_out:
        t = (TRANS.get(it["id"]) or {}).get("trans") or {}
        if t.get("provider"):
            providers[t["provider"]] = providers.get(t["provider"], 0) + 1
        if t.get("model"):
            models[t["model"]] = models.get(t["model"], 0) + 1
        if t.get("at"):
            ats.append(t["at"])
    translation = {
        "provider": max(providers, key=providers.get) if providers else "",
        "model": max(models, key=models.get) if models else "",
        "at": max(ats) if ats else "",
        "items": sum(1 for it in items_out if it.get("title_alt")),
        "reviewed": sum(1 for it in items_out if it.get("alt_reviewed")),
    }
    return {
        "schema": SCHEMA,
        "spec_version": spec_version(),
        "date": date_str,
        "window_hours": window_h,
        "day_kind": "natural",
        "live": not is_complete_day(date_str, coverage_until),
        "generated_at": daily.get("generated_at") or "",
        "translation": translation,
        "meta": {
            "md": "%02d.%02d" % (dt.month, dt.day),
            "full": "%d 年 %d 月 %d 日" % (dt.year, dt.month, dt.day),
            "weekday": WEEKDAYS[dt.weekday()],
        },
        "stats": {
            "filed": len(filed),
            "sources": len({it.get("source_name") for it in filed}),
            "china": sum(1 for it in filed if it.get("region") == "china"),
            "headline": sum(1 for it in filed if it.get("importance") == "头条"),
            "hot_events": len(hot),
            # 数据完备性提示：待人工裁决 / 待归类条数（脚注展示，不参与统计展示口径）
            "review": l1st.get("review", 0),
            "unclassified": l1st.get("unclassified", 0),
            "by_node": by_node, "by_country": by_country,
            "by_importance": by_imp, "by_tag": by_tag,
        },
        "nodes": nodes,
        "hot_events": hot,
        "items": items_out,
    }


# ---------------------------------------------------------------- 落盘
def _atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_all(verbose=True):
    """生成全部投影 + index；返回汇总 dict。调用方可直接用于验收/日志。"""
    dailies = load_dailies()
    if not dailies:
        raise SystemExit("没有可投影的数据集（%s）" % DAILY_ROOT)
    VIEW_ROOT.mkdir(parents=True, exist_ok=True)
    coverage_until = snapshot_coverage()
    by_day = {d: v for d, v in dailies}

    days_meta, wanted = {}, set()
    for date_str, daily in dailies:
        prev = by_day.get((datetime.strptime(date_str, "%Y-%m-%d")
                           - timedelta(days=1)).strftime("%Y-%m-%d"))
        per_window = {}
        for w in WINDOWS:
            if w == 24:
                items, events = daily["items"], daily.get("events") or []
            else:
                items, events = merge_day_items(prev, daily)
            view = build_view(date_str, daily, w, items, events, coverage_until)
            text = json.dumps(view, ensure_ascii=False, separators=(",", ":"))
            name = "%s_%dh.json" % (date_str, w)
            _atomic_write(VIEW_ROOT / name, text)
            wanted.add(name)
            per_window[str(w)] = {
                "filed": view["stats"]["filed"],
                "bytes": len(text.encode("utf-8")),
                "sha256": _sha256(text),
            }
        days_meta[date_str] = {
            "live": not is_complete_day(date_str, coverage_until),
            "generated_at": daily.get("generated_at") or "",
            "windows": per_window,
        }

    # 陈旧投影清理（只清本模块管辖的命名，绝不触碰其他文件）
    pruned = []
    for f in sorted(VIEW_ROOT.glob("2026-*_*h.json")):
        if f.name not in wanted:
            f.unlink()
            pruned.append(f.name)

    complete = [d for d in days_meta if not days_meta[d]["live"]]
    index = {
        "schema": SCHEMA,
        "spec_version": spec_version(),
        "generated_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "windows": list(WINDOWS),
        "latest": complete[-1] if complete else dailies[-1][0],
        "newest": dailies[-1][0],
        "coverage_until": coverage_until.strftime("%Y-%m-%d %H:%M:%S")
        if coverage_until else "",
        "days": days_meta,
    }
    _atomic_write(VIEW_ROOT / "index.json",
                  json.dumps(index, ensure_ascii=False, indent=1) + "\n")

    if verbose:
        total = sum(v["bytes"]
                    for m in days_meta.values() for v in m["windows"].values())
        print("== 视图投影已生成（%s，%d 天 × %d 窗口）=="
              % (SCHEMA, len(days_meta), len(WINDOWS)))
        for d in sorted(days_meta):
            m = days_meta[d]
            print("   %s  %s  24h %-4d / 48h %-4d  %s"
                  % (d, "进行中" if m["live"] else "完整  ",
                     m["windows"]["24"]["filed"], m["windows"]["48"]["filed"],
                     "%.0f KB" % (sum(v["bytes"] for v in m["windows"].values())
                                  / 1024)))
        print("   索引 latest=%s（最近完整日）newest=%s · 投影总体积 %.0f KB"
              % (index["latest"], index["newest"], total / 1024))
        if pruned:
            print("   清理陈旧投影：%s" % "、".join(pruned))
    return index


def main():
    ap = argparse.ArgumentParser(description="L2 视图投影层：事实源 → 数据/视图/")
    ap.add_argument("--clean", action="store_true",
                    help="先清空 数据/视图/ 再重建（目录为生成物，可安全重建）")
    args = ap.parse_args()
    if args.clean and VIEW_ROOT.is_dir():
        shutil.rmtree(VIEW_ROOT)
    build_all()


if __name__ == "__main__":
    main()
