#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_spec_summary.py — 从完整体系规范派生「公开摘要」（开源仓库用）

**为什么需要这个脚本**
完整规范（119 KB）是项目内部唯一权威源，但其中约 65% 是内部过程记录：界面实现规格
（按钮位置、色值、动画收尾）、踩坑流水、修订记录、内部治理。这些对公开仓库的读者没有价值，
却让文档显得冗长。本脚本按**章节白名单**抽取其中「口径与契约」部分，生成公开摘要。

**为什么用脚本而不是手抄**
手抄的摘要在规范升版后必然漂移（规范改了、摘要没改，公开文档就开始说谎）。白名单抽取保证
摘要永远从权威源派生——与本项目「口径唯一实现」纪律一致：规范升版后重跑本脚本即可。

**取舍原则**
保留：决定数据怎么来的口径（分类、统计、去重、时间、契约、字段清单）。
丢弃：实现细节（界面规格、踩坑记录）、项目管理信息（修订记录、实施状态、迁移步骤）。

用法：
    python脚本/export_spec_summary.py            # 生成 规范标准/体系规范摘要.md
    python脚本/export_spec_summary.py --check     # 只校验摘要是否与规范同步（CI 用）
"""
import os
import re
import sys
import hashlib
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "规范标准", "月生·AI资讯体系规范.md")
OUT = os.path.join(ROOT, "规范标准", "体系规范摘要.md")

# WILDCARD：保留整章，但三级节按 CHAPTER_ONLY 逐个判
WILDCARD = "__all__"

# WILDCARD 章下要保留的三级节（键同 KEEP）
CHAPTER_ONLY = {
    "0": ["0.1", "0.2", "0.3"],   # 总纲只留定位/结构/接口，丢篇目代码·迭代规则·仓库结构
}

# 章节白名单。
# 键为「篇号.章号」。**必须带篇号**：三篇各自从 1 开始编号，同一个「3」在三篇里指不同的章，
# 若只用章号作键会被后写覆盖（本脚本初版就踩过：第一篇 7 被第三篇 7顶掉）。
# 值为
#   None      = 整章保留（含其下所有三级节）
#   WILDCARD  = 整章保留，但只保留 CHAPTER_ONLY 列出的三级节
#   [..]      = 只保留列表内的三级节
KEEP = {
    # ---- 总纲（篇号 0）：只留「体系是什么、三部分怎么连」 ----
    # 总纲的正文直接挂在「## 0.」这一章下、下面全是 ### 0.x，没有二级子章，
    # 因此用WILDCARD 标记「保留本章下的全部三级节」，再靠 CHAPTER_ONLY 剔除不该留的节。
    "0": WILDCARD,                      # 0.1 体系目的 / 0.2 体系结构 / 0.3 三部分关联
    # 0.4 篇目代码 / 0.5 迭代规则 / 0.6 仓库结构与版本管理 = 内部治理，由 CHAPTER_ONLY 剔除

    # ---- 第一篇 S-01 信源体系 ----
    "1.1": None,                        # 总则
    "1.2": None,                        # 术语与定义
    "1.3": None,                        # 信源分层 T0–T4
    "1.4": ["4.1", "4.2", "4.3"],       # 权威度评分细则 / 动态调整 / 引用规则
    "1.5": None,                        # 信源分类维度
    "1.6": ["6.1", "6.2", "6.3"],       # 准入四标准 / 注册流程 / 注销条件
    "1.7": ["7.1", "7.2"],              # 通道分级 / 自动抓取规范（7.3 人工触发条件为内部流程，丢）
    # 1.8 信源健康监控台账、1.9 附录 B 首批建设原则 = 内部台账，丢

    # ---- 第二篇 R-02 信息资源体系 ----
    "2.1": None,                        # 总则
    "2.2": None,                        # 术语
    "2.3": None,                        # 五节点（分类语义基础）
    "2.4": ["4.1", "4.2"],              # 四维打标 + B 轨封闭词表（删了他人无法正确打标）
    "2.5": None,                        # 信源原始分类 → 节点映射
    "2.6": ["6.1", "6.2", "6.3"],       # 标签冲突判定
    "2.7": None,                        # 信息整理：时间/摘要/标题/去重/事件/实体/重要度/归档/噪声
    "2.8": None,                        # 展现必备要求（对接第三篇）
    # 2.9 附录 A 判例手册 = 逐条增补的判例流水，不适合公开，丢

    # ---- 第三篇 P-03 信息展现体系 ----
    "3.1": ["1.3"],                     # 总则：只留「展现四原则」这条硬约束
    # 3.2 两层信息架构（21.9 KB）整章丢——界面实现规格（按钮位置、色值、动画收尾）
    #    与踩坑记录，代码已表达；2.4 双语层同理由只在此处留一句硬约束（见 PREFACE）
    "3.7": None,                        # 技术形态约束
    "3.8": ["8.1", "8.2"],              # 四层数据流 + VIEW-01 契约（数据与页面的唯一接口）
    "3.9": ["A"],                       # 附录 A：L1 / L2 字段清单
    "3.10": ["10.1", "10.2", "10.7"],   # 最小部署集 + 三类更新 / 一键打包 / 解耦承诺
    # 3.3 视觉风格 / 3.4 交互 / 3.5 可访问性 / 3.6 响应式 = 设计规格，丢；
    # 其中的硬约束（不得为移动端另写页面等）在下方 PREFACE 里以「硬约束」形式给出。
}

# 摘要开头给出的硬约束（原文散落在被丢弃的界面规格章节里，但它们是**规则**不是**样式**）
PREFACE = """### 硬约束（不可妥协）

- **同一套 DOM 与同一份渲染实现**：桌面与移动端共用一份页面代码，控件形态随断点切换。
  **禁止为移动端另写页面或第二份渲染函数。**
- **译文只作附加层，永不替换原文**；机器译文出现处必须标注「机器译文 · 未校对」。
- **无横向滚动**：装饰元素一律以 `min(<设计宽度>, 100%)` 收进容器，不得定宽后居中溢出。
- **触达目标 ≥44px**（移动端）。
- **单一实现原则**：同一口径（如排序编号、窗口合并、归组）在管线中只有一个实现位置，
  上下游消费而不重算。
"""

HEAD1 = re.compile(r"^# (?!#)(.+)$")
HEAD2 = re.compile(r"^## (.+)$")
HEAD3 = re.compile(r"^### (.+)$")
NUM = re.compile(r"^(\d+(?:\.\d+)?)")


def split_parts(lines):
    """按一级标题切成 [(篇号, 标题, [行])]，篇号 0 表示总纲。"""
    parts = []
    cur_part, cur_title, cur = -1, "", []
    for ln in lines:
        m = HEAD1.match(ln)
        if m:
            if cur_part >= 0:
                parts.append((cur_part, cur_title, cur))
            t = m.group(1)
            if t.startswith("第一篇"):
                cur_part = 1
            elif t.startswith("第二篇"):
                cur_part = 2
            elif t.startswith("第三篇"):
                cur_part = 3
            else:
                cur_part = 0
            cur_title, cur = t, []
        else:
            cur.append(ln)
    if cur_part >= 0:
        parts.append((cur_part, cur_title, cur))
    return parts


def split_chapters(body):
    """按二级标题切章，返回 [(编号, 标题, [行])]。编号取标题前导数字。"""
    chaps, cur_num, cur_title, cur = [], "", "", []
    started = False
    for ln in body:
        m = HEAD2.match(ln)
        if m:
            if started:
                chaps.append((cur_num, cur_title, cur))
            t = m.group(1)
            mm = NUM.match(t)
            cur_num = mm.group(1) if mm else t
            cur_title, cur, started = t, [], True
        elif started:
            cur.append(ln)
    if started:
        chaps.append((cur_num, cur_title, cur))
    return chaps


def split_subs(body):
    """按三级标题切节，返回 [(编号, 标题, [行])]；无三级标题时返回单块。

    **标题必须一起回填**：只存编号会丢标题，重建输出时无从写回（本脚本初版就因此
    把总纲的0.1/0.2/0.3 三节合并成了一坨无标题正文）。
    """
    subs, cur_num, cur_title, cur = [], None, "", []
    for ln in body:
        m = HEAD3.match(ln)
        if m:
            if cur_num is not None:
                subs.append((cur_num, cur_title, cur))
            mm = NUM.match(m.group(1))
            cur_num = mm.group(1) if mm else m.group(1)
            cur_title, cur = m.group(1), []
        else:
            cur.append(ln)
    if cur_num is not None:
        subs.append((cur_num, cur_title, cur))
    # 章内首段（若有三级标题之前的引言）作为无编号块返回
    return subs or [(None, "", body)]


def keep_key(part, num):
    """判断某章是否保留；返回 (是否保留, 允许的三级编号 or None)。

    章号在规范里是二级标题的前导数字（第一篇的「3.」取到 "3"，总纲的「0.1」取到 "0.1"），
    统一拼成「篇号.章号」作复合键，避免三篇编号重号。
    """
    if not num:
        return False, None
    if part == 0:
        # 总纲的二级标题是「## 0.」，前导数字取到 "0"；其下已用三级标题 0.1/0.2…
        # 故键就是 "0"（不要拼成 "0.0"）。
        key = num if num == "0" or num.startswith("0.") else "0.%s" % num
    else:
        key = "%s.%s" % (part, num)
    if key in KEEP:
        want = KEEP[key]
        if want == WILDCARD:
            return True, CHAPTER_ONLY.get(key)
        return True, want
    return False, None


def build():
    """生成摘要正文。

    返回 (text, version, kept_bytes)，成功；返回 int 表示失败码。

    **公开仓库模式**：完整规范是内部文档、被 `.gitignore` 排除，因此 clone 后本脚本
    没有源可派生。这是**预期状态**而非缺陷——故此时走「摘要自检」分支：
    校验已入库的摘要是否结构完整（标题、硬约束、三篇齐备），而不是报「找不到完整规范」。
    """
    if not os.path.exists(SPEC):
        return build_public_mode()

    src = open(SPEC, encoding="utf-8").read()
    lines = src.split("\n")

    version = ""
    m = re.search(r"\|\s*AIIS-01\s*\|\s*(v[\d.]+)\s*\|\s*(\S+)\s*\|", src)
    if m:
        version = m.group(1)

    out = []
    today = datetime.date.today().isoformat()
    out.append("# AI 资讯体系规范 · 摘要")
    out.append("")
    out.append("> 本文件是项目完整体系规范的**公开摘要**，由 `脚本/export_spec_summary.py` 按章节白名单自动派生，")
    out.append("> 记录的是**口径与契约**：数据怎么来的、字段什么意思、接口长什么样。")
    out.append("> 请勿手工编辑——规范升版后重跑派生脚本即可同步。")
    out.append(">")
    out.append("> 适用范围：ASYS · AI 资讯日报流水线。摘要对应规范版本 %s。" % version)
    out.append("")
    out.append("---")
    out.append("")
    out.append(PREFACE.rstrip("\n"))
    out.append("")

    kept_bytes = 0
    for part, ptitle, pbody in split_parts(lines):
        # 篇章标题（略去「第一篇 xxx（S-01）」里的编号后缀，改为纯标题）
        short = re.sub(r"^第[一二三]篇\s*", "", ptitle).split("（")[0].strip()
        if part == 0:
            short = "体系总纲"
        emit_head = False
        for num, ctitle, cbody in split_chapters(pbody):
            ok, allowed = keep_key(part, num)
            if not ok:
                continue
            if not emit_head:
                out.append("## %s" % short)
                out.append("")
                emit_head = True
            out.append("### %s" % ctitle)
            out.append("")
            if allowed is None:
                chunk = list(cbody)
            else:
                chunk = []
                for snum, stitle, sbody in split_subs(cbody):
                    if snum is None:
                        # 章内引言（无编号）：若本章有白名单节则丢弃，否则保留
                        if not allowed:
                            chunk.extend(sbody)
                        continue
                    if snum in allowed:
                        chunk.append("#### %s" % stitle)
                        chunk.append("")
                        chunk.extend(sbody)
            # 去掉空行堆叠
            body_txt = "\n".join(chunk).strip("\n")
            out.append(body_txt)
            out.append("")
            kept_bytes += len(body_txt.encode("utf-8"))

    # 收敛空行：最多连续一个空行（抽取过程会留下空行堆叠）
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip("\n") + "\n"

    # ---- 页脚：生成信息与指纹（供 --check 判定是否漂移） ----
    fingerprint = hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
    text += (
        "\n---\n\n"
        "<sub>摘要由 `脚本/export_spec_summary.py` 于 %s 从完整规范派生（约 %.1f KB，"
        "源规范指纹 `%s`）。完整规范升版后重跑该脚本即可同步。</sub>\n"
        % (today, len(text.encode("utf-8")) / 1024.0, fingerprint)
    )
    return text, version, kept_bytes


def build_public_mode():
    """公开仓库模式：无完整规范可派生，只做摘要自检。

    公开仓库收录的是已生成的摘要本身（本脚本的产物），不收录派生源。因此这个模式下
    能做的校验是**结构自检**：摘要存在、有硬约束节、三篇齐备、篇幅合理、指纹在页脚。
    这保证「摘要不是空壳或残缺」——真正的「与规范同步」只能由持有完整规范的一方校验。
    """
    if not os.path.exists(OUT):
        sys.stderr.write(
            "公开仓库模式下没有可派生的源，也没有已生成的摘要。\n"
            "摘要由持有内部完整规范的一方生成后随代码入库；"
            "若你是从公开仓库 clone 的，摘要应已随仓库提供。\n")
        return 2
    cur = open(OUT, encoding="utf-8").read()
    problems = []
    if not cur.lstrip().startswith("# "):
        problems.append("缺文档标题")
    if "硬约束" not in cur:
        problems.append("缺「硬约束」节")
    for part in ("信源体系", "信息资源体系", "信息展现体系"):
        if ("## " + part) not in cur:
            problems.append("缺篇章：%s" % part)
    if "VIEW-01" not in cur:
        problems.append("缺视图契约 VIEW-01")
    size = len(cur.encode("utf-8"))
    if size < 8000:
        problems.append("篇幅异常（%.1f KB），疑似空壳" % (size / 1024.0))
    if problems:
        for p in problems:
            sys.stderr.write("FAIL %s\n" % p)
        return 1
    print("公开仓库模式：未收录派生源（内部完整规范），已对入库摘要做结构自检。")
    print("  摘要 %.1f KB · 硬约束节齐备 · 三篇齐备 · 含 VIEW-01 契约" % (size / 1024.0))
    return None


def main():
    res = build()
    if res is None:
        return 0 if "--check" in sys.argv or True else 0
    if isinstance(res, int):
        return res
    text, version, kept = res

    if "--check" in sys.argv:
        if not os.path.exists(OUT):
            sys.stderr.write("FAIL 摘要不存在，请运行 export_spec_summary.py\n")
            return 1
        cur = open(OUT, encoding="utf-8").read()
        if cur != text:
            sys.stderr.write(
                "FAIL 摘要已过期（完整规范升版后未重跑 export_spec_summary.py）\n")
            return 1
        print("摘要与完整规范同步（源版本 %s，摘要 %.1f KB）"
              % (version, len(text.encode("utf-8")) / 1024.0))
        return 0

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("已生成 %s" % os.path.relpath(OUT, ROOT))
    print("  完整规范 %.1f KB → 摘要 %.1f KB（保留正文 %.1f KB，压缩至 %.0f%%）"
          % (os.path.getsize(SPEC) / 1024.0,
             len(text.encode("utf-8")) / 1024.0,
             kept / 1024.0,
             kept * 100.0 / os.path.getsize(SPEC)))
    print("  源规范版本 %s" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main())