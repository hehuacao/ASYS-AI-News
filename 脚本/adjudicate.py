#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1.5 内容裁决：按信息实质处理人工裁决队列与待归类池。

规范 AIIS-01 v1.3 第二篇 6.3「规则 + 内容裁决」两层分流：
- 规则分类器（classify.py）输出候选与置信度；
- 本脚本按信息实质（标题 + 摘要 + 信源属性）逐条裁决：
    file   —— 入档（指定节点/子类，置信度记 0.90，标记 adjudicated）
    event  —— 事件成员标记（同一 Event 已有入档代表，不重复入档）
    exclude—— 显式排除（非 AI 内容 / 会议通稿 / 与已入档事件重复）
- 自动重复裁定：队列条目所属 Event 若已有入档代表（无论来自规则层还是
  本次裁决），即自动标记为事件成员，不再重复入档——这是规范「Event 合并
  去重」的直接结果，不需要人工逐条判断。未被覆盖的条目才进入人工裁决，
  因此缺少裁决表时脚本会列出缺口而不会静默略过。
- 人工干预模式为「浏览纠错」：日常不逐条过队列；仅在浏览发现错误时
  做修正式干预。裁决结论回流为判例（规范附录 A + classify.py 规则）。

用法：
    python 脚本/adjudicate.py --date 2026-10-13
    python 脚本/adjudicate.py --date <日期> --decisions <裁决JSON>

裁决 JSON 格式（定时自动化由代理按内容实质生成后传入）：
    {"IT-xxx": ["file", "frontier", "新兴方向与前瞻观点", "理由"],
     "IT-yyy": ["exclude", null, null, "非AI内容"],
     "IT-zzz": ["event", "EVT-0004", null, "事件成员"]}
不传 --decisions 时使用本文件内置裁决表（2026-10-13 判例留存）。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "脚本"))

import classify as C  # noqa: E402

# ---------------------------------------------------------------- 裁决表
# id: (动作, 节点, 子类, 理由)
DECISIONS = {
    # ===== 人工裁决队列（0.6–0.8，17 条）=====
    "IT-20261013-0010": ("file", "frontier", "新兴方向与前瞻观点",
        "AI 工具链实战教程：展示当前 AI 辅助游戏开发的可行路径，归趋势（同 Vapi 教程判例）"),
    "IT-20261013-0043": ("file", "capability", "算法与训练方法",
        "Apple 研究论文：智能体长轨迹上下文自压缩方法，属算法研究（非模型发布）"),
    "IT-20261013-0121": ("file", "product", "开源项目与工具链",
        "开源库：GPT 类模型快速消融实验工具，可复用工具即产品"),
    "IT-20261013-0126": ("file", "product", "开源项目与工具链",
        "开源项目：并行编码智能体编队控制面（Rust），工具链产品"),
    "IT-20261013-0129": ("file", "product", "开源项目与工具链",
        "开源项目：本地优先 AI 学习伴侣（混合 RAG），完整应用产品"),
    "IT-20261013-0132": ("file", "product", "开源项目与工具链",
        "开源项目：LLM 应用 CI 回归测试与评测工具"),
    "IT-20261013-0134": ("file", "product", "开源项目与工具链",
        "第三方 API 档案：记录 DeepSeek 可调用面，属产品层信息（api-evangelist 系列判例）"),
    "IT-20261013-0136": ("file", "product", "开源项目与工具链",
        "开源配置镜像：Claude Code 规则/设置/钩子，工具链资源"),
    "IT-20261013-0140": ("file", "product", "开源项目与工具链",
        "开源推理服务器与生产集群，基础设施软件产品"),
    "IT-20261013-0142": ("file", "product", "新产品与新功能",
        "新产品：可经 MCP 驱动 Claude 的乐谱编辑器"),
    "IT-20261013-0144": ("file", "governance", "安全与风险事件",
        "智能体绕过沙箱与外部通信——安全风险事件（规则已命中，内容确认）"),
    "IT-20261013-0151": ("file", "capability", "算法与训练方法",
        "推测式工具调用降低语音智能体延迟——推理优化方法，归能力层"),
    "IT-20261013-1601": ("file", "industry", "组织与人事",
        "SEC 6-K：CEO 与运营更新，组织人事信息"),
    "IT-20261013-1607": ("file", "industry", "投融资与财报",
        "SEC 8-K：公司申报文件，资本市场信息"),
    "IT-20261013-1629": ("file", "industry", "投融资与财报",
        "SEC 424B5：招股补充文件，融资信息"),
    "IT-20261013-1648": ("file", "product", "新产品与新功能",
        "web-edit 0.1a0 发布：手机端 Codex Remote 配套编辑工具"),
    "IT-20261013-1704": ("file", "frontier", "新兴方向与前瞻观点",
        "Karpathy 观点评论：AI 实际能力与外部认知差——言论主旨归趋势（非新产品）"),

    # ===== 待归类池（<0.6，42 条）=====
    "IT-20261013-0016": ("event", "EVT-0013", None,
        "EVT-0013（架构不改重训）canonical，AIHOT 版已入档，不重复入档"),
    "IT-20261013-0051": ("event", "EVT-0004", None,
        "EVT-0004（Epic AI 先行）canonical，AIHOT 版已入档，不重复入档"),
    "IT-20261013-0052": ("file", "governance", "安全与风险事件",
        "EVT-0019 canonical：Claude 向警方提交虚假谋杀线索——AI 安全风险事件（代表条目入档）"),
    "IT-20261013-0054": ("file", "frontier", "新兴方向与前瞻观点",
        "亚马逊百万机器人劳动力及其对雇员的影响——劳动力前瞻研判"),
    "IT-20261013-0123": ("file", "product", "开源项目与工具链",
        "开源项目：AI 智能体长期记忆系统（Markdown 认知图 + MCP）"),
    "IT-20261013-0128": ("file", "product", "开源项目与工具链",
        "第三方 API 档案：字节豆包可调用面（api-evangelist 系列判例）"),
    "IT-20261013-0143": ("file", "product", "新产品与新功能",
        "Show HN 产品：以找出 AI 所写 bug 为主题的游戏，AI 主题产品发布"),
    "IT-20261013-0146": ("file", "frontier", "新兴方向与前瞻观点",
        "AI 风险领域专家可信度评论——观点研判归趋势"),
    "IT-20261013-0148": ("file", "frontier", "新兴方向与前瞻观点",
        "AI 是否会导致人类互相残杀——风险观点讨论归趋势"),
    "IT-20261013-0149": ("file", "frontier", "新兴方向与前瞻观点",
        "维基百科编辑者与 AI 的长期共存——AI 影响研判归趋势"),
    "IT-20261013-0152": ("file", "product", "新产品与新功能",
        "Show HN 产品：MacBook Air 上 13 秒转写一小时音频的转录工具"),
    "IT-20261013-0156": ("event", "EVT-0059", None,
        "EVT-0059（AI 实验室采购停运初创数据）成员，MIT TR 版入档，不重复入档"),
    "IT-20261013-0159": ("file", "product", "新产品与新功能",
        "AI 人才匹配网络（Mercor）——AI 驱动的招聘匹配服务"),
    "IT-20261013-0160": ("file", "product", "开源项目与工具链",
        "Show HN 工具：从编码智能体修正记录中提炼技能，开发工具产品"),
    "IT-20261013-0161": ("file", "product", "新产品与新功能",
        "Show HN 工具：调用 OpenAI 订阅生成有声书，API 应用产品"),
    "IT-20261013-0163": ("exclude", None, None,
        "纽约餐馆停空调歇业——本地商业新闻，与 AI 无关"),
    "IT-20261013-0164": ("file", "product", "新产品与新功能",
        "AI 网关产品横评（OpenRouter 等）——产品格局信息归产品层"),
    "IT-20261013-0165": ("exclude", None, None,
        "与已入档 EVT-0004（Epic Games AI 先行）重复，不重复入档"),
    "IT-20261013-0167": ("file", "frontier", "新兴方向与前瞻观点",
        "「AI 通才幻觉」评论文章——观点研判归趋势"),
    "IT-20261013-0168": ("event", "EVT-0019", None,
        "EVT-0019（Claude 虚假线索）成员，Ars Technica 版已入档，不重复入档"),
    "IT-20261013-0169": ("file", "frontier", "新兴方向与前瞻观点",
        "495 张 AI 商品图实测：35% 错误为文字——AI 落地质量问题研判"),
    "IT-20261013-0170": ("file", "frontier", "新兴方向与前瞻观点",
        "机器人用户代理作为开发者营销渠道——前瞻观点"),
    "IT-20261013-0192": ("file", "frontier", "Agent与自动化",
        "Anthropic 动态工作流协调 Claude 智能体——Agent 工程实践报告"),
    "IT-20261013-0193": ("exclude", None, None,
        "订阅者线下活动通讯——非资讯内容"),
    "IT-20261013-0266": ("file", "product", "新产品与新功能",
        "2026 年 12 款 AI 实时翻译工具横评——产品格局信息"),
    "IT-20261013-0268": ("file", "capability", "前沿模型发布",
        "Cloudflare 发布 Clef-omni（30B-A3B 多模态决策模型，Apache-2.0）——模型发布"),
    "IT-20261013-0274": ("file", "frontier", "新兴方向与前瞻观点",
        "开放模型的收益与风险之辨——MIT TR 解读，观点研判"),
    "IT-20261013-0275": ("file", "industry", "市场格局与竞争",
        "EVT-0059 canonical：AI 实验室采购停运初创数据训练——数据供给市场格局"),
    "IT-20261013-0296": ("file", "capability", "算力与基础设施",
        "OCP 峰会：NVIDIA 开放 Vera Rubin 架构扩展 AI 工厂——算力基础设施"),
    "IT-20261013-1650": ("exclude", None, None,
        "矮人要塞启用版本控制——游戏开发轶事，与 AI 无关"),
    "IT-20261013-1651": ("exclude", None, None,
        "Python 3.15.0 进入 actions/python-versions——通用工具链，与 AI 无关"),
    "IT-20261013-1681": ("file", "product", "垂直行业落地",
        "Blueprints AI：数分钟生成合规施工图——建筑行业 AI 落地"),
    "IT-20261013-1682": ("exclude", None, None,
        "TechCrunch Disrupt 会议售票通稿——非资讯内容"),
    "IT-20261013-1684": ("file", "product", "新产品与新功能",
        "Apple HomeView 智能家居产品命名与档期——消费电子产品动态"),
    "IT-20261013-1685": ("exclude", None, None,
        "TechCrunch Disrupt 会议倒计时通稿——非资讯内容"),
    "IT-20261013-1687": ("file", "frontier", "新兴方向与前瞻观点",
        "多位高管研判语音 AI 尚未到「ChatGPT 时刻」——市场成熟度观点"),
    "IT-20261013-1698": ("file", "governance", "安全与风险事件",
        "Anthropic 研究警示：小模型或将在日常设备上自主扩散——安全风险研究"),
    "IT-20261013-1701": ("file", "frontier", "Agent与自动化",
        "微软研究：清理聊天历史帮助智能体跳出「idea basins」——Agent 实践发现"),
    "IT-20261013-1705": ("event", "EVT-0008", None,
        "EVT-0008（AlphaProof Nexus）canonical，AIHOT 版已入档，不重复入档"),
    "IT-20261013-1706": ("file", "frontier", "Agent与自动化",
        "Vals AI 研究：多智能体团队 token 消耗 5.1 倍而增益甚微——Agent 经济学发现"),
    "IT-20261013-1710": ("file", "governance", "政策法规与监管",
        "硅谷配合 Trump 将 AI 更名「super intelligence」——政策话语环境归治理"),
    "IT-20261013-1711": ("file", "frontier", "新兴方向与前瞻观点",
        "本地 AI 使用体验手记（兴奋/ overwhelm/ 挫败）——用户体验观点归趋势"),
}

ADJ_CONF = 0.90


def auto_event_members(items, pending):
    """自动重复裁定：pending 中「所属 Event 已有入档代表」的条目。

    返回 {item_id: (action, event_id, None, 理由)}。同一事件（URL 或标题
    ≥0.85 相似）只保留一条入档代表，其余按规范判为事件成员。
    """
    filed_events = {it.get("event_id") for it in items
                    if it.get("route") == "filed" and it.get("event_id")}
    out = {}
    for it in items:
        eid = it.get("event_id")
        if it["id"] in pending and eid and eid in filed_events:
            out[it["id"]] = ("event", eid, None,
                             "所属事件已有入档代表，按 Event 去重规则不重复入档")
    return out


def main():
    ap = argparse.ArgumentParser(description="P1.5 内容裁决（R-02 6.3）")
    ap.add_argument("--date", required=True, help="日报日期 YYYY-MM-DD")
    ap.add_argument("--decisions", help="外部裁决 JSON 路径（缺省用内置裁决表）")
    ap.add_argument("--partial", action="store_true",
                    help="只应用已有裁决：重建后新增的待裁决条目保留在队列，不报错")
    args = ap.parse_args()
    date_str = args.date

    decisions = DECISIONS
    if args.decisions:
        decisions = {k: tuple(v) for k, v in
                     json.loads(Path(args.decisions).read_text(encoding="utf-8")).items()}
        print("使用外部裁决表：%s（%d 条）" % (args.decisions, len(decisions)))

    path = C.DAILY_ROOT / ("%s.json" % date_str)
    if not path.exists():
        raise SystemExit("日报数据不存在：%s" % path)
    dataset = json.loads(path.read_text(encoding="utf-8"))
    items = dataset["items"]
    by_id = {it["id"]: it for it in items}

    unknown = [i for i in decisions if i not in by_id]
    if unknown:
        # 重建后条目集可能变化（更宽的快照合并、信源改版等），裁决表里的陈旧
        # 条目跳过即可；不能因此中断整日的裁决，否则全部裁决都落不了盘。
        print("跳过陈旧裁决 %d 条（不在当前数据集中）：%s"
              % (len(unknown), ", ".join(sorted(unknown)[:5]) + (" …" if len(unknown) > 5 else "")))
        decisions = {k: v for k, v in decisions.items() if k in by_id}
    # 结构性噪声由规则层权威判定（规范第二篇 7.6）：裁决表不得翻案，
    # 避免旧裁决把已被规则排除的程序性备案又拉回队列或入档。
    noise_ids = sorted(k for k, v in by_id.items() if v.get("noise_reason"))
    if noise_ids:
        decisions = {k: v for k, v in decisions.items() if k not in noise_ids}
        print("规则层已排除结构性噪声 %d 条（裁决表若有对应条目一并跳过）"
              % len(noise_ids))
    queue = set(dataset.get("review_queue") or []) | set(
        dataset.get("unclassified_pool") or [])
    # 自动重复裁定优先：同事件已有代表者无需人工裁决
    auto = auto_event_members(items, queue)
    pending = sorted(i for i in queue if i not in auto)
    missing = [i for i in pending if i not in decisions]
    if missing and not args.partial:
        raise SystemExit("队列中存在未裁决条目 %d 条：%s" % (len(missing), missing))
    if missing:
        print("保留待裁决 %d 条（--partial）：重建后新增，留待浏览纠错" % len(missing))

    n_file = n_event = n_excl = 0
    log = []
    for auto_id, (action, node, _sub, reason) in sorted(auto.items()):
        it = by_id[auto_id]
        it["route"] = "event_member"
        it["event_member_of"] = node
        it["adjudication"] = reason
        n_event += 1
        log.append((auto_id, "事件成员(自动)", node, reason))
    for iid, (action, node, sub, reason) in decisions.items():
        it = by_id[iid]
        it["adjudicated"] = True
        it["adjudication"] = reason
        if action == "file":
            eid = it.get("event_id")
            # 同一事件只能有一条入档代表：若规则层或本次裁决已有代表，降级为成员
            # （裁决表顺序即优先级：先写者为代表）
            rep = [x for x in items if x is not it and x.get("event_id") == eid
                   and x.get("route") == "filed"] if eid else []
            if rep:
                it["route"] = "event_member"
                it["event_member_of"] = eid
                it["adjudication"] = reason
                n_event += 1
                log.append((iid, "事件成员", eid,
                            "同事件已有人入档代表，裁决结论降级为成员：%s" % reason))
                continue
            it["node"], it["subcategory"] = node, sub
            it["node_name"] = C.NODE_NAMES[node]
            it["confidence"] = ADJ_CONF
            it["route"] = "filed"
            n_file += 1
            log.append((iid, "入档", "%s›%s" % (C.NODE_NAMES[node], sub), reason))
        elif action == "event":
            it["route"] = "event_member"
            it["event_member_of"] = node
            n_event += 1
            log.append((iid, "事件成员", node, reason))
        else:
            it["route"] = "excluded"
            n_excl += 1
            log.append((iid, "排除", "—", reason))

    # 二次自动裁定：本次裁决入档的条目让某些事件首次有了代表
    still = {it["id"] for it in items
             if it.get("route") in ("review", "unclassified")}
    for aid, (action, node, _s, reason) in sorted(
            auto_event_members(items, still).items()):
        it = by_id[aid]
        it["route"] = "event_member"
        it["event_member_of"] = node
        it["adjudication"] = reason
        n_event += 1
        log.append((aid, "事件成员(自动·裁决后)", node, reason))

    # 重要度按同一规则重算（新入档条目纳入）
    C.assign_importance(items)

    # 同一 Event（跨信源）只保留一条入档代表，其余收敛为事件成员
    collapse_log = []
    dup = C.collapse_duplicate_routes(items, collapse_log)
    # 收敛后：先把事件分组对齐人工裁决的挂靠关系，再把 canonical 对齐到入档条目
    # （规范 7.4）——保证热点条目的 canonical 恒为本视图可见的入档条目
    C.regroup_events(items, dataset["events"])
    C.normalize_member_links(items, dataset["events"])
    C.sync_event_canonical(items, dataset["events"])

    filed = [it for it in items if it["route"] == "filed"]
    review = [it for it in items if it["route"] == "review"]
    unclassified = [it for it in items if it["route"] == "unclassified"]

    skipped = [(s["source_id"], s["reason"])
               for s in dataset["stats"].get("skipped_snapshots", [])]
    partial = [(s["source_id"], s.get("failed_dirs", 1),
                   s.get("today_failed_reason", ""))
               for s in dataset["stats"].get("partial_snapshots", [])]
    filtered_old = [{"source_id": sid}
                    for sid, cnt in dataset["stats"].get(
                        "filtered_by_source", {}).items()
                    for _ in range(cnt)]

    # 复用 classify.write_outputs 重写 JSON + 质检报告（保持格式一致）
    out_json, out_md = C.write_outputs(
        date_str, items, dataset["events"], filed, review, unclassified,
        skipped, filtered_old, partial=partial)

    # 报告追加内容裁决记录
    L = []
    L.append("")
    L.append("## 6. 内容裁决记录（P1.5，规范 v1.2 第二篇 6.3）")
    L.append("")
    L.append("- 裁决时间：%s（北京时间）" % C.bj_now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("- 裁决口径：按信息实质（标题 + 摘要 + 信源属性）判归属；"
             "人工干预为「浏览纠错」模式，日常不逐条过队列")
    L.append("- 处理结果：入档 %d · 事件成员标记 %d · 显式排除 %d；"
             "残留人工队列 %d · 待归类池 %d" % (n_file, n_event, n_excl,
                                            len(review), len(unclassified)))
    L.append("")
    L.append("| ID | 裁决 | 归属 | 依据 |")
    L.append("|---|---|---|---|")
    title_by_id = {it["id"]: it["title"] for it in items}
    for iid, action, target, reason in log:
        L.append("| %s《%s》 | %s | %s | %s |" % (
            iid, title_by_id[iid][:26], action, target, reason))
    L.append("")
    if args.decisions:
        L.append("> 裁决来源：外部裁决表（%s）。按规范 v1.2，裁决结论应回流为判例"
                 "（规范附录 A）并视系统性缺口改进 classify.py 规则。" % args.decisions)
    else:
        L.append("> 裁决结论已按判例回流：规范附录 A 增补七类判例；"
                 "classify.py 新增关键词（emergency brake / trust architecture / "
                 "sandbox / bypass / rogue / theft / decision model）与安全子类词。")
    with open(out_md, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")

    print("== P1.5 内容裁决完成 %s ==" % date_str)
    print("入档 %d · 事件成员 %d · 排除 %d；残留 人工队列 %d / 待归类 %d" % (
        n_file, n_event, n_excl, len(review), len(unclassified)))
    by_node = {}
    for it in filed:
        by_node[it["node"]] = by_node.get(it["node"], 0) + 1
    print("入档节点分布：%s" % "；".join(
        "%s %d" % (C.NODE_NAMES[n], by_node.get(n, 0)) for n in C.NODES))
    print("数据集：%s" % out_json)
    print("质检报告：%s" % out_md)


if __name__ == "__main__":
    main()
