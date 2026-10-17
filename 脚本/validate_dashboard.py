# -*- coding: utf-8 -*-
"""仪表盘终检：结构 / 外部资源 / JS 语法 / 对比度 / 卡片完备性 / 多日期结构。

用法：python validate_dashboard.py
需要已有 仪表盘/ai_news_daily.html 与 数据/视图/；Node 从 PATH 解析（未找到则跳过需Node 的断言）。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "仪表盘" / "ai_news_daily.html"
NODE = shutil.which("node") or shutil.which("node.exe")

if not HTML.exists():
    raise SystemExit("产物不存在：%s（先运行 render_dashboard.py）" % HTML)

html = HTML.read_text(encoding="utf-8")
fails = []


def check(name, ok, detail=""):
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))
    if not ok:
        fails.append(name)




# 0) 期望值：数据集中全部日期的入档条数
daily_files = sorted((ROOT / "数据" / "日报").glob("????-??-??.json"))
expected_days = len(daily_files)
expected_cards = 0
for p in daily_files:
    d = json.loads(p.read_text(encoding="utf-8"))
    expected_cards += sum(1 for it in d["items"] if it.get("route") == "filed")

# 中国热点标注（.hot-cn）的期望值必须与「注入 htmlM 的区块集合」同口径——即逐份 L2
# 投影（24h 与 48h 都算）计数，而不是按 L1 自然日逐日计数。
# 差异来源（2026-10-17 修）：48h 视图是「前一日 + 当日」的合并视图，跨日合并出的事件
# 会让同一个中国热点在相邻两日的 48h 区块里各出现一次（实证 10-16_48h 的 EVT-0013、
# 10-17_48h 的 EVT-0060），按 L1 逐日计数会漏计这两处 → 假 FAIL。
# 期望值取自 L2 投影，与本项目「测试期望值一律取自投影、不另立口径」一致。
expected_cn_hot = 0

# 双视图（自然日 × 24/48h）：页面是「按需渲染」形态，产物内不含烘焙日区块。
# 故先用**前端渲染纯函数**（页面内联的同一实现，即 assets/render_runtime.js）把每份
# 投影渲染成日区块，注入外壳后组装成「完整页面」，再对其做全部结构断言。
ASSETS = ROOT / "脚本" / "assets" / "render_runtime.js"
VIEWS = ROOT / "数据" / "视图"

# 渲染探针：Node 侧加载打包件，用 dayBlock 渲染一份投影并输出到 stdout。
# 用法：node -e <script> <投影文件> <index.json>
PROBE_JS = (
    "const fs=require('fs');"
    "const F=require(process.argv[1]).Fragments;"
    "const v=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
    "const idx=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));"
    "const w=String(v.window_hours),d=(idx.days&&idx.days[v.date])||null;"
    "const c=(d&&d.windows&&d.windows[w])||{};"
    "process.stdout.write(F.dayBlock(v,{winCounts:{'24':(idx.days[v.date]||{}).windows"
    "?idx.days[v.date].windows['24'].filed:null,"
    "'48':(idx.days[v.date]||{}).windows?idx.days[v.date].windows['48'].filed:null}}));"
)


def render_block(f):
    r = subprocess.run([NODE, "-e", PROBE_JS, str(ASSETS), str(f),
                        str(VIEWS / "index.json")],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("渲染探针失败（%s）：\n%s" % (f.name, r.stderr or r.stdout))
    return r.stdout


_blocks = []
for _d in sorted(f.stem.split("_")[0] for f in VIEWS.glob("2026-*_24h.json")):
    for _w in (24, 48):
        _f = VIEWS / ("%s_%dh.json" % (_d, _w))
        if _f.exists():
            _blocks.append(render_block(_f))
            _proj = json.loads(_f.read_text(encoding="utf-8"))
            expected_cn_hot += sum(
                1 for e in _proj.get("hot_events", []) if e.get("china"))
_host = re.search(r'<div class="day" id="dayHost"[^>]*></div>', html)
check("外壳含常驻日期容器（内容按需渲染）", bool(_host))
# html    = 外壳原文（含 <script>）：用于 JS/样式字符串断言
# htmlM   = 外壳去脚本 + 注入渲染区块：用于「结构/计数」断言（避免 JS 模板字面量干扰）
htmlM = re.sub(r"<script>.*?</script>", "<script/>", html, flags=re.S)
if _host:
    _inj = "\n  " + "\n  ".join(_blocks) + "\n  "
    htmlM = htmlM.replace(_host.group(0), _inj, 1)

view_parts = re.split(r'<div class="day" data-date="[\d-]+" data-window="(24|48)"', htmlM)
html24, html48 = view_parts[0], ""
for _i in range(1, len(view_parts), 2):
    if view_parts[_i] == "48":
        html48 += view_parts[_i + 1]
    else:
        html24 += view_parts[_i + 1]
_vw = re.findall(r'class="day" data-date="[\d-]+" data-window="(\d+)"', htmlM)
check("视图区块数 = 天数 × 2（24h/48h）",
      _vw.count("24") == expected_days and _vw.count("48") == expected_days,
      "%s" % _vw)

# 页面内联的渲染打包件必须与磁盘产物逐字节一致（页面与 Node 侧同一份实现）
_pa = html[html.index("/* 前端资产"):html.index("/* ============ 数据源")].rstrip()
check("页面内联渲染打包件 == assets/render_runtime.js",
      _pa.strip() == ASSETS.read_text(encoding="utf-8").strip())

# 数据载荷完整性：内联投影必须与 数据/视图/ 的磁盘文件逐字段一致
_src = re.search(r"const VIEW_SRC = (.*);\n", html)
_srcj = json.loads(_src.group(1)) if _src else {}
_idx_disk = json.loads((VIEWS / "index.json").read_text(encoding="utf-8"))
check("内联索引 == 数据/视图/index.json", _srcj.get("index") == _idx_disk)
_v_disk = {f.name[:-5]: json.loads(f.read_text(encoding="utf-8"))
           for f in VIEWS.glob("2026-*_*h.json")}
check("内联投影 == 磁盘投影（逐份逐字段）",
      _srcj.get("views") == _v_disk,
      "内联 %d 份 / 磁盘 %d 份" % (len(_srcj.get("views") or {}), len(_v_disk)))
check("离线形态标记正确（mode=offline）", _srcj.get("mode") == "offline",
      str(_srcj.get("mode")))

# 1) 占位符残留
check("无占位符残留", "@@" not in html)
check("单文件自包含（内联数据 + 内联渲染器，零网络请求即出首屏）",
      "const VIEW_SRC = " in html and "const FLAG_SVGS = " in html and
      "FRAGMENTS" in html)

# 2) 外部资源
srcs = re.findall(r'src\s*=\s*"([^"]*)"', html)
check("无 src 外部资源", not [s for s in srcs if s.startswith("http")], str(srcs[:3]))
check("无 @import / url() 外链", "@import" not in html and "url(http" not in html)
ext_hrefs = re.findall(r'href="(http[^"]*)"', html)
check("外链均为 https 资讯链接", all(h.startswith("https://") for h in ext_hrefs),
       "%d 个外链" % len(ext_hrefs))
check("原文链接均带 rel", 'target="_blank" rel="noopener noreferrer"' in html)

# 3) ISO 时间不泄露到展示层（published_bj 人话格式）
card_zone = html.split('class="wrap"')[0] + html.split("</main>")[-1]
check("卡片/页脚无 ISO 时间", not re.findall(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', card_zone))

# 4) HTML 结构
VOID = {"meta", "br", "img", "input", "hr", "link", "circle", "path", "rect"}


class Chk(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append("extra </%s>" % tag)
        elif self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append("mismatch expect </%s> got </%s>" % (self.stack[-1], tag))


c = Chk()
c.feed(html)
check("标签配对完整", not c.errors and not c.stack, str((c.errors or c.stack)[:3]))

# 4b) 多日期结构：无重复 id（每日期区块内只用 class/data 选择器）
ids = re.findall(r'id="([^"]+)"', html)
dup_ids = sorted({i for i in ids if ids.count(i) > 1})
pass  # 视图内 id 无重复（在双视图切分后校验）
_cal = re.search(r"const VIEW_SRC = (.*);\n", html)
check("日历数据来源 = L2 索引（天数与索引一致）",
      _cal is not None and len(
          (json.loads(_cal.group(1)).get("index") or {}).get("days") or {}) == expected_days,
      "%s 天" % (len((json.loads(_cal.group(1)).get("index") or {}).get("days") or {})
                 if _cal else "?"))
check("日历面板结构齐备（月导航+周表头+网格+图例）",
      'id="dmGrid" role="listbox"' in html and 'id="dmPrev"' in html and
      'id="dmNext"' in html and 'id="dmToday"' in html and
      'class="dm-week"' in html and 'class="dm-foot"' in html)
check("日历每格含 24h/48h 双窗口读数",
      'class="dc-chip' in html and 'data-window="24"' in html and
      'data-window="48"' in html and "chipHtml(24" in html and "chipHtml(48" in html)

# 5) L1/L2 必备内容
for frag, name in [
    ('data-node="capability"', "节点-能力"), ('data-node="product"', "节点-产品"),
    ('data-node="industry"', "节点-产业"), ('data-node="governance"', "节点-治理"),
    ('data-node="frontier"', "节点-趋势"), ('class="axis-hero"', "价值链主轴（核心）"),
    ('class="axis-mini"', "迷你主轴（滚动常驻）"), ('class="ah-node"', "主轴节点卡"),
    ('class="am-btn"', "迷你主轴按钮"), ('class="hotbar"', "热点横条"),
    ('class="datepicker"', "日期选择器"), ('data-region="china"', "分区切换"),
    ('class="footer"', "信源脚注"), ('id="drawer"', "L2 详情抽屉"),
    ('name="viewport"', "viewport 响应式"), ("prefers-reduced-motion", "动效降级"),
    ("prefers-color-scheme", "跟随系统"), ("localStorage", "主题持久化"),
    # Hero 改版：入档条数为视觉主体 + 五节点分布面板
    ('class="hero-num stat-num"', "Hero 渐变大数字（入档条数）"),
    ('class="hero-dist"', "Hero 分布面板"), ('class="hd-row"', "分布行"),
    ("今日入档 AI 资讯", "Hero 主体文案"),
    # 热点横条：标题右侧统计 + 国旗标注
    ('class="hotbar-stats"', "热点标题右侧统计"), ('class="hs-chip hs-hot"', "交叉热点统计标"),
    ('hr-item hr-cn', "Hero 地域构成-涉及中国（与总条数同行）"),
    ('hr-item hr-global', "Hero 地域构成-全球资讯（地球徽章）"),
    ('class="globe"', "全球地域徽标 SVG"), ('class="flag"', "国旗 SVG 体系"),
    # 迷你主轴文案
    ("AI 价值链 · AI VALUE CHAIN", "迷你主轴 AI 价值链"),
    # 英文体系
    ("CAPABILITY", "英文-能力"), ("PRODUCT", "英文-产品"), ("INDUSTRY", "英文-产业"),
    ("GOVERNANCE", "英文-治理"), ("FRONTIER", "英文-趋势"),
    ("CROSS-SOURCED", "英文-热点"), ("24H 条数（当日）", "月历图例-24H"),
    ("CROSS-SOURCED", "英文-交叉热点"), ("TODAY", "英文-Hero"),
    ("入档资讯总条数", "涉及中国口径提示"),
    ("#DE2910", "国旗红"),
    # 修改项回归
    ("summary_full", "抽屉摘要全文字段"),
    # v1.14：渐进加载取代「查看全部」（不再有 .show-all）
    (".more-bar{", "渐进加载容器"), (".more-btn{", "展开更多按钮"),
    (".card[hidden]{display:none!important}", "渐进加载收起优先于卡片自身 display"),
    ("#navpod", "悬浮导航舱"), ('class="np-ring-bar"', "导航舱进度环"),
    ('class="mprog"', "移动端进度条"), ('id="cmdk"', "命令面板"),
    ('id="biPop"', "双语对照浮层"), ('id="langSwitch"', "语言模式三态"),
    ("UI_TEXT", "界面术语表"), ("--fs, 1", "可读性字号变量"),
]:
    check("L1/L2 含%s" % name, frag in html or frag in htmlM)

# 5a) 首屏去重：交叉热点/涉及中国统计只在热点横条标题右侧出现一次
check("Hero 无四统计卡（旧版已下线）", "stat-card" not in htmlM)
check("主轴无 chips（避免多处重复）", "ah-chip" not in htmlM)
check("热点统计标唯一出处（标题右侧，每视图一处）",
      htmlM.count('class="hotbar-stats"') == expected_days * 2,
      "%d 处 / 期望 %d" % (htmlM.count('class="hotbar-stats"'), expected_days * 2))

# 5b) 主轴五节点中英文 + 计数
for key, zh, en in [("capability", "能力", "CAPABILITY"), ("product", "产品", "PRODUCT"),
                    ("industry", "产业", "INDUSTRY"), ("governance", "治理", "GOVERNANCE"),
                    ("frontier", "趋势", "FRONTIER")]:
    m = re.search(r'<button type="button" class="ah-node" data-node="%s".*?</button>'
                  % key, htmlM, re.S)
    ok = bool(m and zh in m.group(0) and en in m.group(0)
              and re.search(r'ahn-count">\d+ 条<', m.group(0)))
    check("主轴节点[%s]中英文+计数" % zh, ok)

# 5b-2) Hero 渐变大数字 = 各日期入档总数；分布面板五行走档数
hero_nums = [int(x) for x in re.findall(r'hero-num stat-num" data-target="(\d+)"', html24)]
check("Hero 大数字数 = 天数", len(hero_nums) == expected_days, str(hero_nums))
per_day_filed = []
for p in daily_files:
    d = json.loads(p.read_text(encoding="utf-8"))
    per_day_filed.append(sum(1 for it in d["items"] if it.get("route") == "filed"))
check("Hero 大数字 = 当日入档条数", hero_nums == per_day_filed,
      "%s vs %s" % (hero_nums, per_day_filed))
hd_rows = re.findall(r'<div class="hd-row"', html24)
check("分布面板每日期 5 行", len(hd_rows) == expected_days * 5,
      "%d 行" % len(hd_rows))

# 5b-3) 热点横条统计：交叉热点数 = 当日多信源事件数（第四轮起横条只保留此标）
# （统计标带 title 口径提示属性，正则需允许属性）
hs_hot = [int(x) for x in re.findall(r'hs-chip hs-hot"[^>]*><b>(\d+)</b>', html24)]
check("热点横条不再并排涉及中国统计（口径分流）",
      "hs-chip hs-cn" not in html)
per_day_hot, per_day_cn = [], []
for p in daily_files:
    d = json.loads(p.read_text(encoding="utf-8"))
    per_day_hot.append(sum(1 for e in d.get("events", [])
                           if e.get("source_count", 0) >= 2))
    per_day_cn.append(sum(1 for it in d["items"]
                          if it.get("route") == "filed" and it.get("region") == "china"))
check("热点统计标：交叉热数正确", hs_hot == per_day_hot, "%s vs %s" % (hs_hot, per_day_hot))
hm_cn = [int(x) for x in re.findall(r'hr-item hr-cn"[^>]*>.*?<b>(\d+)</b>', html24, re.S)]
check("(双视图口径) 24h 涉及中国 = 数据", hm_cn == per_day_cn,
      "%s vs %s" % (hm_cn, per_day_cn))
check("Hero 涉及中国数 = 当日入档中国条数", hm_cn == per_day_cn,
      "%s vs %s" % (hm_cn, per_day_cn))

# 5b-4) 48h 视图：大数字 = 前一日 + 当日合并入档数（按 URL 去重）
def _u(u):
    return (u or "").split("?")[0].rstrip("/")
nums48 = [int(x) for x in re.findall(
    r'hero-num stat-num" data-target="(\d+)"', html48)]
import sys as _sys2
_sys2.path.insert(0, str(ROOT / "脚本"))
import view_projection as _vp   # 48h 合并口径的唯一实现在 L2
exp48 = []
for _i, p in enumerate(daily_files):
    d = json.loads(p.read_text(encoding="utf-8"))
    prev = (json.loads(daily_files[_i - 1].read_text(encoding="utf-8"))
            if _i > 0 else None)
    merged, _ev = _vp.merge_day_items(prev, d)
    exp48.append(sum(1 for it in merged if it.get("route") == "filed"))
check("48h 视图大数字 = 前一日+当日合并数", nums48 == exp48,
      "%s vs %s" % (nums48, exp48))
check("视图内 id 无重复（24h；48h 跨视图共享条目属设计）",
      len(set(re.findall(r'data-id="([^"]+)"', html24)))
      == len(re.findall(r'data-id="([^"]+)"', html24)))

# 5c) 中国国旗标注数 = 涉及中国的交叉事件数
check("热点中国国旗标签数正确",
      htmlM.count('class="hot-cn"') == expected_cn_hot,
      "%d 个（期望 %d）" % (htmlM.count('class="hot-cn"'), expected_cn_hot))

# 5c-2) 来源国旗标：每张卡片 chip-src 至少一个旗标（有 country 的信源）
flag_cards = len(re.findall(r'chip chip-src"[^>]*><svg class="flag"', htmlM))
check("卡片来源旗标已渲染", flag_cards > 0, "%d 处 chip-src 带旗标" % flag_cards)
# 日报数据中出现的来源国，其旗样必须在页面国旗库中定义
import sys as _sys
_sys.path.insert(0, str(ROOT / "脚本"))
from render_dashboard import FLAG_SVGS  # noqa: E402
used_countries = set()
for p in daily_files:
    d = json.loads(p.read_text(encoding="utf-8"))
    used_countries |= {it.get("country") for it in d["items"] if it.get("country")}
missing_flags = sorted(c for c in used_countries if c not in FLAG_SVGS)
check("国旗库覆盖全部现有来源国", not missing_flags,
      "缺失: %s" % (missing_flags or "无"))

# 5c-3) 第三轮改版回归（用户 2026-10-14 九项反馈）
check("交叉热点统计标=深橙实底白字", ".hs-hot{background:var(--hot-deep);color:#fff" in html)
check("Hero 地域构成：涉及中国=国旗+无框成对（第六轮：与总条数同行）",
      ".hero-region{display:inline-flex;align-items:center;gap:16px" in html and
      ".hr-sep{width:1px;height:34px" in html and
      re.search(r'hr-item hr-cn"[^>]*><svg class="flag"[^>]*width="16"', htmlM) is not None)
check("地域构成含全球资讯配对（地球徽章+无边框）",
      "hr-item hr-global" in html and "全球资讯" in html and
      '<svg class="globe"' in html and
      "border-radius:999px;font-size:12.5px;font-weight:600;cursor:help" not in html)
check("全球徽章与数字=国际蓝（globe-blue 三主题变量）",
      html.count("--globe-blue:#5B9BD5") == 1 and
      html.count("--globe-blue:#2E75B6") == 2)
check("全球项徽章与数字均用国际蓝变量",
      ".hr-global b{color:var(--globe-blue)}" in html and
      ".hr-global .globe{color:var(--globe-blue)}" in html)
check("涉及中国/全球资讯文字粗体",
      ".hr-item{display:inline-flex;align-items:center;gap:7px;font-size:13px;\n"
      "  font-weight:700;" in html)
check("地域构成与英文标签底齐平（align-self:flex-end+微调）",
      ".hero-region{display:inline-flex;align-items:center;gap:16px;margin-left:14px;\n"
      "  align-self:flex-end;margin-bottom:7px}" in html)
# 地域构成与总条数在同一行（hero-figure 内联，非单独一行）
check("地域构成在 hero-figure 行内（与总条数同行）",
      re.search(r'hero-figure">.*?hero-region.*?</div>', html, re.S) is not None)
# 地域构成两数之和 = 当日入档总数
hr_sum = []
for p in daily_files:
    d = json.loads(p.read_text(encoding="utf-8"))
    f2 = [it for it in d["items"] if it.get("route") == "filed"]
    hr_sum.append(len(f2))
hr_pairs = re.findall(r'hr-item hr-cn"[^>]*>.*?<b>(\d+)</b>.*?hr-item hr-global"[^>]*>.*?<b>(\d+)</b>', htmlM, re.S)
check("涉及中国 + 全球 = 当日入档总数（24h 视图）",
      [int(a) + int(b) for a, b in hr_pairs[0::2]] == hr_sum,
      "%s vs %s" % (hr_pairs, hr_sum))
check("涉及中国统计含口径提示 title",
      htmlM.count("入档资讯总条数") >= expected_days)
check("窗口切换器含口径 title（24h=当日整日 / 48h=前一日+当日）",
      htmlM.count("当日整日（") >= expected_days * 2 and
      htmlM.count("前一日 + 当日整日（48 小时）") >= expected_days * 2)
check("Hero meta 行内嵌窗口切换器（胶囊轨道 + 滑动指示块）",
      htmlM.count('class="hw-switch') >= expected_days * 2 and
      ".hw-thumb{position:absolute" in html and
      ".hw-switch.on-48 .hw-thumb{transform:translateX(100%)}" in html and
      'v.window_hours === 48 ? " on-48" : ""' in html)
check("Hero 晨报标题与日期同一行、日期靠右（唯一 row 规则，无 column 残留）",
      ".hero-topline{display:flex;flex-direction:row;align-items:baseline;" in html and
      html.count(".hero-topline{") == 1 and
      "48H 条数（前日 + 当日）" in html)
check("生成时间与日期格式呼应（生成时间 · MM.DD HH:MM，不加粗不改色）",
      htmlM.count("生成时间 · ") >= expected_days * 2 and
      re.search(r'生成时间 · <span class="hm-tval">\d{2}\.\d{2} \d{2}:\d{2}</span>',
                htmlM) is not None and
      ".hm-tval{color:var(--text-muted);font-weight:400" in html)
check("数据集为自然日归档（24h 口径）",
      all(d.get("window_hours") == 24 and d.get("day_kind") == "natural"
          for d in (json.loads(p.read_text(encoding="utf-8")) for p in daily_files)))
check("深色主题 hot-deep token", "--hot-deep:#C2410C" in html)
check("橙底徽标字色=纯黑（hot-solid-fg #000）",
      html.count("--hot-solid-fg:#000") == 3)
check("迷你导航计数不受徽标字色覆盖（em:not 修复）",
      ".am-btn em:not(.am-flag){" in html)
check("顶栏品牌英文名 ASYS · AI NEWS DAILY（小于中文）",
      "ASYS · AI NEWS DAILY" in html and "AIIS-01</small>" not in html and
      ".brand small{font-weight:600;color:var(--text-muted);font-size:10.5px" in html)
check("品牌英文与中文底部齐平（flex-end）",
      ".brand{display:flex;align-items:flex-end" in html and
      ".brand-text{display:inline-flex;align-items:flex-end" in html and
      '<span class="brand-zh">' in html)
check("搜索框宽度 220px（聚焦 280px）",
      ".searchbox input{\n  width:220px" in html and
      ".searchbox input:focus{width:280px" in html)
check("热点统计标字体已缩小（15.5px）", ".hs-chip b{font-size:15.5px" in html)
check("统计标含口径提示（6事件≠7条中国）",
      htmlM.count("多信源交叉报道的事件数") >= expected_days and
      htmlM.count("入档资讯总条数") >= expected_days)
check("Hero 日期强调（18px+主色下划线）",
      ".hero-date-mini b{font-size:18px;font-weight:800" in html and
      "border-bottom:2px solid var(--accent-capability)" in html)
check("Hero meta 数字与规范号强调（强调色+加粗）",
      ".hm-fact b{font-weight:800;font-size:14px;color:var(--accent-capability)" in html and
      htmlM.count('信源 · <b>') >= expected_days * 2 and
      htmlM.count("规范 · <b>AIIS-01</b>") >= expected_days * 2)
check("Hero 左列顶对齐（分布面板不动）",
      ".hero{display:flex;align-items:flex-start" in html)
check("分布面板条数按节点色", ".hd-num b{font-size:13.5px;font-weight:800;color:var(--nc)}" in html)
check("分布面板百分比中性", ".hd-num em{font-style:normal;font-size:10px;color:var(--text-muted)}" in html)
check("重要徽标金色实底重点化", "badge-imp{" in html and "var(--imp-bg)" in html)
check("头条徽章深色字橙底（对比度）", "badge-hot{" in html and "var(--hot-solid-fg)" in html)
# 规范版本号：页面显示值须与投影内的 spec_version（L1 加工层单一来源）一致——
# 不写死版本串，规范一升版这里不再需要改（避免「改了规范忘了改断言」的假失败）
_spec = json.loads((VIEWS / "index.json").read_text(encoding="utf-8")).get("spec_version", "")
check("规范版本与投影内 spec_version 一致（%s）" % _spec, bool(_spec) and _spec in html)
# 热点条目名称后国旗：**一信源一旗**（同国多旗保留），与「N 信源」读数同口径。
# Event 的 sources 是逐条报道明细，同一信源可能就同一事件收录多条（实证 EVT-0001：
# AI HOT 收录 x.com/arena 与 artificialanalysis.ai 两条）——国旗与明细行按信源去重，
# 其余收录以 .hot-more（附域名）链接保留在所属信源行内。
exp_flags = exp_rows = exp_more = 0
for p in daily_files:
    d = json.loads(p.read_text(encoding="utf-8"))
    im = {it["id"]: it for it in d["items"]}
    for e in d.get("events", []):
        if e.get("source_count", 0) < 2:
            continue
        groups = {}
        for s in e.get("sources") or []:
            si = im.get(s.get("item_id"), {})
            key = si.get("source_id") or s.get("source_name") or s.get("item_id")
            groups[key] = groups.get(key, 0) + 1
        exp_flags += len(groups)
        exp_rows += len(groups)
        exp_more += sum(v - 1 for v in groups.values())
hot_flag_n = len(re.findall(r'<span class="hot-flag"', html24))
hot_row_n = sum(len(re.findall(r'<li>', tl)) for tl in re.findall(
    r'<ul class="hot-timeline" hidden>(.*?)</ul>', html24, re.S))
hot_more_n = len(re.findall(r'class="hot-more"', html24))
dup_ev = 0
for _item in re.findall(r'<div class="hot-item">.*?</div>', html24, re.S):
    _ts = re.findall(r'<span class="hot-flag" title="([^"]*)"', _item)
    if len(_ts) != len(set(_ts)):
        dup_ev += 1
check("热点国旗数 = 独立信源数（一信源一旗）", hot_flag_n == exp_flags,
      "%d 个（期望 %d）" % (hot_flag_n, exp_flags))
check("热点明细行数 = 独立信源数（一信源一行）", hot_row_n == exp_rows,
      "%d 行（期望 %d）" % (hot_row_n, exp_rows))
check("同源多条收录以域名链接保留（hot-more）", hot_more_n == exp_more,
      "%d 个（期望 %d）" % (hot_more_n, exp_more))
check("热点国旗无同源重复", dup_ev == 0, "%d 个事件有重复" % dup_ev)
check("热点旗标紧贴标题后（非行尾）",
      ".hot-title{flex:0 1 auto" in html and ".hot-flags{flex:none;display:inline-flex;align-items:center;gap:5px;margin-left:10px}" in html)
check("热点旗标尺寸 16px（与卡片统一）",
      'width="16" height="11"' in htmlM)
# 五面板：条数读数行末化（大数字+分隔线，不再与行首编号相像）
node_count_badges = re.findall(
    r'<span class="node-count" data-total="\d+"><b>\d+</b><i>条</i></span>', htmlM)
check("五面板条数读数结构（双视图 ×2）", len(node_count_badges) == expected_days * 10,
      "%d 个（期望 %d）" % (len(node_count_badges), expected_days * 10))
check("条数读数样式（24px节点色+左分隔线）",
      ".node-count b{font-size:24px;font-weight:800;color:var(--nc)" in html and
      "border-left:1px solid var(--border)" in html)
check("节点描述移入标题行（单行省略号）",
      htmlM.count('<p class="node-desc">') == expected_days * 10 and
      ".node-desc{flex:1;min-width:0;text-align:right" in html and
      "white-space:nowrap;overflow:hidden;text-overflow:ellipsis" in html)
check("版面紧凑化：Hero 顶距 26px", "flex-wrap:wrap;padding:26px 0 12px" in html)
check("版面紧凑化：节点面板间距 20px", "margin-top:20px;padding:18px 20px 16px" in html)

# 6) 卡片完备性（序号/标题/摘要/来源chip/时间/原文链接/≤3 属性chip）
_idx_src = re.search(r"const VIEW_SRC = (.*);\n", html)
_IDX = (json.loads(_idx_src.group(1)).get("index") or {}) if _idx_src else {}
_counts_all = {d: {"24": (((v.get("windows") or {}).get("24") or {}).get("filed", 0)),
                   "48": (((v.get("windows") or {}).get("48") or {}).get("filed", 0))}
               for d, v in (_IDX.get("days") or {}).items()}
cards = re.findall(r'<article class="card".*?</article>', htmlM, re.S)
check("卡片总数 = 入档数（24h 视图 + 48h 视图）",
      len(cards) == sum(v["24"] + v["48"] for v in _counts_all.values()),
      "%d 张（期望 %d）" % (len(cards), sum(v["24"] + v["48"] for v in _counts_all.values())))
# 6a) 卡片底部两行结构（来源+时间 / 原文+镜像），保证各卡底部对齐
two_row = sum(1 for cd in cards
              if 'class="card-meta-row"' in cd and 'class="card-links"' in cd)
check("卡片底部两行结构齐全", two_row == len(cards),
       "%d/%d" % (two_row, len(cards)))
check("链接行时间左/链接右对应+细分隔线样式",
      ".card-links{display:flex;justify-content:space-between" in html and
      ".cl-links{display:inline-flex" in html and
      "border-top:1px solid var(--border)" in html)
bad = []
for cd in cards:
    if not re.search(r'card-num">\d+<', cd):
        bad.append("序号")
    if "card-title" not in cd:
        bad.append("标题")
    if "card-summary" not in cd:
        bad.append("摘要")
    if "chip-src" not in cd:
        bad.append("来源")
    if "card-time" not in cd:
        bad.append("时间")
    if not re.search(r'card-link" href="https://', cd):
        bad.append("原文链接")
    if len(re.findall(r'chip chip-b', cd)) > 3:
        bad.append("chip超3")
check("单卡七要素齐全", not bad, str(set(bad)))
# 编号在每个日期区块内连续（多日期各自 01 起）
for date_str, block in zip(
        re.findall(r'<div class="day" data-date="([\d-]+)" data-window="(\d+)"', html),
        re.split(r'<div class="day" data-date="[\d-]+" data-window="\d+"[^>]*>', html)[1:]):
    nums = re.findall(r'card-num">(\d+)<', block)
    check("编号连续[%s/%s]" % (date_str, block and "24h" or ""),
          nums == ["%02d" % i for i in range(1, len(nums) + 1)],
          "%s..%s 共%d" % (nums[0] if nums else "-", nums[-1] if nums else "-", len(nums)))

# 7) JS 语法（提取 <script> 交 node --check）
m = re.search(r"<script>(.*?)</script>", html, re.S)
js = m.group(1)
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(js)
    js_path = f.name
r = subprocess.run([NODE, "--check", js_path], capture_output=True, text=True)
check("内联 JS 语法正确", r.returncode == 0, r.stderr[:200])

# 8) 对比度（WCAG）：两套主题关键 token 对
def lum(hexs):
    hexs = hexs.lstrip("#")
    r, g, b = (int(hexs[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


pairs_dark = [
    ("正文/卡面", "#F1F5F9", "#111827"), ("次级/卡面", "#94A3B8", "#111827"),
    ("弱化/卡面", "#7D8DA3", "#111827"), ("弱化/页底", "#7D8DA3", "#0A0E17"),
    ("能力青/卡面", "#22D3EE", "#111827"), ("热点橙/浮层", "#F97316", "#1A2332"),
    ("成功绿/卡面", "#34D399", "#111827"), ("主轴名/页底", "#94A3B8", "#0A0E17"),
    ("主按钮字/青", "#04121A", "#22D3EE"), ("国旗白字/红旗", "#FFFFFF", "#DE2910"),
    ("交叉热点白字/深橙实底", "#FFFFFF", "#C2410C"),
    ("重要徽标深字/金底", "#1A1208", "#FBBF24"),
]
pairs_light = [
    ("正文/卡面", "#1A1A1A", "#FFFFFF"), ("次级/卡面", "#5C5C5C", "#FFFFFF"),
    ("弱化/卡面", "#6E6A63", "#FFFFFF"), ("弱化/页底", "#6E6A63", "#FAF7F2"),
    ("能力青/卡面", "#0E7490", "#FFFFFF"), ("热点橙/浮层", "#C2410C", "#F5EFE6"),
    ("成功绿/卡面", "#047857", "#FFFFFF"), ("主轴名/页底", "#5C5C5C", "#FAF7F2"),
    ("主按钮字/青", "#FFFFFF", "#0E7490"), ("国旗白字/红旗", "#FFFFFF", "#DE2910"),
    ("交叉热点白字/深橙实底", "#FFFFFF", "#C2410C"),
]
for label, fg, bg in pairs_dark + pairs_light:
    theme = "深色" if (fg, bg) in [p[1:] for p in pairs_dark] else "浅色"
    check("对比度[%s·%s]≥4.5" % (theme, label), ratio(fg, bg) >= 4.5,
          "%.2f:1" % ratio(fg, bg))

# ---- 发布包结构 ----
# zip 必须平铺：若全部文件套在「<包名>/」子目录里，顶层没有 index.html，
# 站点根文档不存在 → 整站 404。这里锁住：ASCII 候选根存在 + zip 平铺（若已有 zip）。
# 离线版数据全内联、不发取数请求；只有运行态薄壳需要探测数据根，故断言落在薄壳上。
_shell = ROOT / "仪表盘" / "runtime_shell.html"
_shell_html = _shell.read_text(encoding="utf-8") if _shell.exists() else ""
check("运行态：数据根候选含 ASCII 路径（静态托管可用）",
      "BASE_CANDIDATES" in _shell_html and "data/views/" in _shell_html,
      "离线版数据全内联、不发取数请求，不适用此断言")
_release_dir = ROOT / "发布"
_zips = sorted(_release_dir.glob("*.zip")) if _release_dir.exists() else []
if _zips:
    import zipfile
    _z = zipfile.ZipFile(_zips[-1])
    _names = _z.namelist()
    _nested = [n for n in _names if n.split("/")[0].endswith("日报-2026")]
    check("发布 zip：顶层含 index.html", "index.html" in _names,
          _zips[-1].name)
    check("发布 zip：文件未套在子目录内", not _nested,
          ("嵌套 " + _nested[0]) if _nested else "平铺")
    _cn = [n for n in _names if "数据" in n]
    check("发布 zip：数据目录为纯 ASCII（托管环境取数更稳）", not _cn,
          _names[0] if _names else "")

print()
if fails:
    print("终检失败 %d 项：%s" % (len(fails), fails))
    sys.exit(1)
print("全部终检通过")
