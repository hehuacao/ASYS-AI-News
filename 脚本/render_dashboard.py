#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 展现层装配器 —— 外壳 + 样式 + 数据通道，内容由前端渲染纯函数产出。

架构：
- **渲染逻辑的唯一实现**是 `render_fragments.js`（前端纯函数，只吃视图投影）；
  本脚本不写任何内容模板，只负责「外壳 + 样式 + 数据载荷 + 落地」。
- 两种形态同一份代码，只有数据通道不同：
    --mode offline（默认）  离线单文件：索引与全部投影内联 → 自包含、零请求
    --mode runtime          运行态薄壳：索引与首屏投影内联兜底，其余按需fetch
                            （**须经HTTP 访问**——浏览器禁止 file:// 页面读取本地
                              数据文件；不可达时按设计降级为内联首屏快照并在页首
                              说明原因与替代方案，浏览器内的降级不是构建缺陷）
- 表现层「定义型资产」（国旗画法 / 地球徽标 / 国家名 / 节点元数据 / 小图标 /
  Python 语义的百分比格式化）以本文件常量为单一来源，由 `gen_runtime_assets.py`
  导出为 `assets/render_runtime.js`（= 资产 + 渲染纯函数的打包件，页面内联与
  Node 侧校验共用）。

用法：
    python render_dashboard.py                 # 离线单文件（默认）
    python render_dashboard.py --mode runtime  # 运行态薄壳
    python render_dashboard.py --out <目录>
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "仪表盘"

# L2 视图投影层：本层只读它的产物（依赖方向 L3 → L2，只向下）
from view_projection import VIEW_ROOT, spec_version  # noqa: E402

# 规范版本号单一来源 = L1 加工层（classify.SPEC_VERSION，经 view_projection 转发）。
# 投影与页面因此不可能出现「数据写着 vN、页脚写着 vM」的口径漂移。
SPEC_VERSION = spec_version()

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 五节点主轴：key / 中文名 / 英文名 / 分区定义（长）/ 主轴定义（短）/ 深色色 / 浅色色
NODES = [
    ("capability", "能力", "CAPABILITY",
     "模型、算法、算力的前沿进展——AI 能做什么的证据",
     "模型、算法、算力的前沿进展", "#22D3EE", "#0E7490"),
    ("product", "产品", "PRODUCT",
     "能力转化为用户可用的产品、工具与开源项目",
     "能力转化为可用的产品与工具", "#3B82F6", "#1D4ED8"),
    ("industry", "产业", "INDUSTRY",
     "资本、市场与组织——谁在投钱、谁在赚钱",
     "资本、市场与组织动向", "#8B5CF6", "#6D28D9"),
    ("governance", "治理", "GOVERNANCE",
     "规则、监管、安全与伦理——社会对 AI 的回应",
     "规则、监管、安全与伦理", "#F59E0B", "#B45309"),
    ("frontier", "趋势", "FRONTIER",
     "方向性信号——正在发生的下一步",
     "方向性信号与前瞻观点", "#EC4899", "#BE185D"),
]
NODE_ORDER = [n[0] for n in NODES]
NODE_META = {n[0]: {"name": n[1], "en": n[2], "desc": n[3], "short": n[4],
                    "dark": n[5], "light": n[6]} for n in NODES}
TIER_NAMES = {
    "T0": "官方一手", "T1": "学术基准", "T2": "专业媒体",
    "T3": "聚合策展", "T4": "社区观点",
}

# 界面术语表（中英对照的**唯一来源**）——供「悬停显示另一语种」与「对照模式」消费。
# 只收界面文案（chrome），不收资讯内容：内容译文由 L1.5 译文流水线产出并随投影下发。
# 键 = 语义 key（稳定，不随文案改动）；值 = (中文, English)。
UI_TEXT = {
    # Hero
    "briefing": ("每日晨报", "DAILY BRIEFING"),
    "filed": ("今日入档 AI 资讯", "TODAY'S FILED ITEMS"),
    "china": ("涉及中国", "CHINA-RELATED"),
    "global": ("全球资讯", "GLOBAL"),
    "window": ("时间窗口", "WINDOW"),
    "sources": ("信源", "SOURCES"),
    "spec": ("规范", "SPEC"),
    "generated": ("生成时间", "GENERATED"),
    "live": ("进行中", "LIVE"),
    "distribution": ("当日分布", "BY VALUE-CHAIN NODE"),
    # 主轴
    "chain": ("AI 产业化价值链", "AI INDUSTRIALIZATION VALUE CHAIN"),
    "headline": ("头条", "HEADLINE"),
    "important": ("重要", "KEY"),
    # 热点
    "hot": ("今日热点", "CROSS-SOURCED"),
    "cross": ("交叉热点", "CROSS-SOURCED"),
    "notfiled": ("未入档", "NOT FILED"),
    # 筛选
    "region": ("分区", "REGION"),
    "tags": ("属性", "TAGS"),
    "all": ("全部", "ALL"),
    "clear": ("清除筛选", "CLEAR FILTERS"),
    "noresult": ("没有匹配的资讯", "NO MATCHING ITEMS"),
    # 卡片与分区
    "items": ("条", "ITEMS"),
    "origin": ("原文", "SOURCE"),
    "mirror": ("镜像", "MIRROR"),
    "showmore": ("展开更多", "LOAD MORE"),
    "collapse": ("收起", "COLLAPSE"),
    "nodeempty": ("今日该环节无重要动态", "NO MATERIAL MOVEMENT TODAY"),
    # 抽屉
    "source": ("信源", "SOURCE"),
    "time": ("时间", "TIME"),
    "path": ("主线归属", "VALUE-CHAIN PATH"),
    "labels": ("标签", "LABELS"),
    "related": ("相关报道", "RELATED"),
    "readorigin": ("阅读原文", "READ ORIGINAL"),
    "country": ("来源国家/地区", "COUNTRY / REGION"),
    "tier": ("信源分层", "SOURCE TIER"),
    "authority": ("权威度", "AUTHORITY"),
    "published": ("发布时间", "PUBLISHED"),
    "timebasis": ("时间口径", "TIME BASIS"),
    "node": ("所属环节", "NODE"),
    "subcat": ("子类", "SUBCATEGORY"),
    # 脚注
    "srcmix": ("当日信源", "SOURCE MIX"),
    "scope": ("数据口径", "DATA SCOPE"),
    "origin2": ("数据来源", "ORIGIN"),
    # 新增控件
    "totop": ("回到顶部", "BACK TO TOP"),
    "tobottom": ("回到底部", "JUMP TO END"),
    "cmd": ("命令面板", "COMMAND PALETTE"),
    "langmode": ("语言模式", "LANGUAGE MODE"),
    "origmode": ("原文", "ORIGINAL"),
    "bothmode": ("对照", "BILINGUAL"),
    "tgtmode": ("目标语", "TRANSLATED"),
    "mt": ("机器译文 · 未校对", "MACHINE TRANSLATION · UNREVIEWED"),
    "srcorig": ("信源原文", "SOURCE ORIGINAL"),
    "translate": ("译", "TRANSLATE"),
    "showalt": ("译文对照", "BILINGUAL"),
    "hidealt": ("收起对照", "HIDE"),
    "shown": ("已展开", "SHOWN"),
    "of": ("共", "OF"),
    "export": ("复制今日清单", "COPY TODAY'S LIST"),
    "density": ("密度", "DENSITY"),
    "fontsize": ("字号", "TEXT SIZE"),
    "resume": ("继续上次阅读位置", "RESUME LAST POSITION"),
    # 主题
    "theme": ("主题", "THEME"),
    "dark": ("深色", "DARK"),
    "light": ("浅色", "LIGHT"),
    "auto": ("系统", "SYSTEM"),
    "search": ("搜索标题 / 摘要", "SEARCH TITLE / SUMMARY"),
    "brand": ("月生 · AI 资讯日报", "ASYS · AI NEWS DAILY"),
    "pickdate": ("选择日期", "PICK A DATE"),
    "latest": ("最新", "LATEST"),
    # 悬浮导航舱：日期跳转 + 可读性设置
    "dates": ("日期跳转", "JUMP TO DATE"),
    "godate": ("跳到指定日期", "GO TO A DATE"),
    "dateph": ("YYYY-MM-DD，例如 2026-10-14", "YYYY-MM-DD, e.g. 2026-10-14"),
    "datebad": ("格式应为 YYYY-MM-DD，例如 2026-10-14", "Use YYYY-MM-DD, e.g. 2026-10-14"),
    "datenone": ("该日暂无数据", "NO DATA FOR THAT DAY"),
    "daterange": ("现有数据范围", "AVAILABLE RANGE"),
    "dateok": ("回车跳转", "PRESS ENTER TO JUMP"),
    "allDates": ("在命令面板查看全部日期", "ALL DATES IN COMMAND PALETTE"),
    "read": ("阅读设置", "READING"),
    "std": ("标准", "STANDARD"),
    "big": ("大", "LARGE"),
    "xbig": ("特大", "EXTRA LARGE"),
    "normal": ("标准", "NORMAL"),
    "compact": ("紧凑", "COMPACT"),
}

# 国家/地区中文名（与 classify.COUNTRY_NAMES 一致；新增信源国家时同步）
COUNTRY_NAMES = {
    "CN": "中国", "US": "美国", "GB": "英国", "FR": "法国", "DE": "德国",
    "EU": "欧盟", "JP": "日本", "KR": "韩国", "CH": "瑞士", "CA": "加拿大",
    "AU": "澳大利亚", "IL": "以色列", "IN": "印度", "SG": "新加坡",
    "NL": "荷兰", "SE": "瑞典", "RU": "俄罗斯", "UA": "乌克兰",
    "IT": "意大利", "ES": "西班牙", "FI": "芬兰", "NO": "挪威",
    "DK": "丹麦", "BR": "巴西",
}

# 国旗库：viewBox 0 0 24 16（3:2），11–13px 徽标尺寸下的简化但可识别画法。
# 覆盖现有信源全部来源国 + AI 领域主要国家；新增国家在此追加即可。
FLAG_SVGS = {
    "CN": '<rect width="24" height="16" fill="#DE2910"/>'
          '<path d="M7.2 5.1l.78 1.78 1.97.11-1.52 1.21.55 1.97-1.78-1.05'
          '-1.78 1.05.55-1.97-1.52-1.21 1.97-.11z" fill="#FFDE00"/>'
          '<circle cx="11.8" cy="4.3" r=".58" fill="#FFDE00"/>'
          '<circle cx="13.7" cy="5.5" r=".58" fill="#FFDE00"/>'
          '<circle cx="13.7" cy="7.2" r=".58" fill="#FFDE00"/>'
          '<circle cx="11.8" cy="8.4" r=".58" fill="#FFDE00"/>',
    "US": '<rect width="24" height="16" fill="#fff"/>'
          '<g fill="#B22234"><rect width="24" height="1.24"/>'
          '<rect y="2.47" width="24" height="1.24"/><rect y="4.94" width="24" height="1.24"/>'
          '<rect y="7.41" width="24" height="1.24"/><rect y="9.88" width="24" height="1.24"/>'
          '<rect y="12.35" width="24" height="1.24"/>'
          '<rect y="14.82" width="24" height="1.24"/></g>'
          '<rect width="10.4" height="8.66" fill="#3C3B6E"/>'
          '<g fill="#fff"><circle cx="1.5" cy="1.5" r=".52"/><circle cx="3.7" cy="1.5" r=".52"/>'
          '<circle cx="5.9" cy="1.5" r=".52"/><circle cx="8.1" cy="1.5" r=".52"/>'
          '<circle cx="1.5" cy="4.3" r=".52"/><circle cx="3.7" cy="4.3" r=".52"/>'
          '<circle cx="5.9" cy="4.3" r=".52"/><circle cx="8.1" cy="4.3" r=".52"/>'
          '<circle cx="1.5" cy="7.1" r=".52"/><circle cx="3.7" cy="7.1" r=".52"/>'
          '<circle cx="5.9" cy="7.1" r=".52"/><circle cx="8.1" cy="7.1" r=".52"/></g>',
    "GB": '<rect width="24" height="16" fill="#012169"/>'
          '<path d="M0 0l24 16M24 0L0 16" stroke="#fff" stroke-width="3.6"/>'
          '<path d="M0 0l24 16M24 0L0 16" stroke="#C8102E" stroke-width="1.9"/>'
          '<path d="M12 0v16M0 8h24" stroke="#fff" stroke-width="5.2"/>'
          '<path d="M12 0v16M0 8h24" stroke="#C8102E" stroke-width="2.8"/>',
    "FR": '<rect width="8" height="16" fill="#002654"/>'
          '<rect x="8" width="8" height="16" fill="#F1F2F1"/>'
          '<rect x="16" width="8" height="16" fill="#CE1126"/>',
    "DE": '<rect width="24" height="16" fill="#FFCE00"/>'
          '<rect width="24" height="10.67" fill="#D00"/>'
          '<rect width="24" height="5.33" fill="#111"/>',
    "JP": '<rect width="24" height="16" fill="#F1F2F1"/>'
          '<circle cx="12" cy="8" r="4.4" fill="#BC002D"/>',
    "KR": '<rect width="24" height="16" fill="#fff"/>'
          '<circle cx="12" cy="8" r="3.1" fill="#CD2E3A"/>'
          '<path d="M8.9 8a3.1 3.1 0 0 1 6.2 0z" fill="#0047A0"/>'
          '<g fill="#111">'
          '<g transform="rotate(-26 4.2 3.8)"><rect x="3.1" y="3.5" width="2.2" height=".5"/>'
          '<rect x="3.1" y="4.35" width="2.2" height=".5"/><rect x="3.1" y="5.2" width="2.2" height=".5"/></g>'
          '<g transform="rotate(26 19.8 3.8)"><rect x="18.7" y="3.5" width="2.2" height=".5"/>'
          '<rect x="18.7" y="4.35" width="2.2" height=".5"/><rect x="18.7" y="5.2" width="2.2" height=".5"/></g>'
          '<g transform="rotate(26 4.2 12.2)"><rect x="3.1" y="11.9" width="2.2" height=".5"/>'
          '<rect x="3.1" y="12.75" width="2.2" height=".5"/><rect x="3.1" y="13.6" width="2.2" height=".5"/></g>'
          '<g transform="rotate(-26 19.8 12.2)"><rect x="18.7" y="11.9" width="2.2" height=".5"/>'
          '<rect x="18.7" y="12.75" width="2.2" height=".5"/><rect x="18.7" y="13.6" width="2.2" height=".5"/></g>'
          '</g>',
    "CH": '<rect width="24" height="16" fill="#DA291C"/>'
          '<rect x="10.8" y="2.6" width="2.4" height="10.8" fill="#fff"/>'
          '<rect x="6.6" y="6.8" width="10.8" height="2.4" fill="#fff"/>',
    "CA": '<rect width="24" height="16" fill="#F1F2F1"/>'
          '<rect width="6" height="16" fill="#D52B1E"/>'
          '<rect x="18" width="6" height="16" fill="#D52B1E"/>'
          '<path d="M12 3.1l.95 2.3 2.5.2-1.9 1.6.6 2.5-2.15-1.35'
          '-2.15 1.35.6-2.5-1.9-1.6 2.5-.2z" fill="#D52B1E"/>',
    "EU": '<rect width="24" height="16" fill="#039"/><g fill="#FFCC00">'
          '<circle cx="16.7" cy="8" r=".58"/><circle cx="16.07" cy="10.35" r=".58"/>'
          '<circle cx="14.35" cy="12.07" r=".58"/><circle cx="12" cy="12.7" r=".58"/>'
          '<circle cx="9.65" cy="12.07" r=".58"/><circle cx="7.93" cy="10.35" r=".58"/>'
          '<circle cx="7.3" cy="8" r=".58"/><circle cx="7.93" cy="5.65" r=".58"/>'
          '<circle cx="9.65" cy="3.93" r=".58"/><circle cx="12" cy="3.3" r=".58"/>'
          '<circle cx="14.35" cy="3.93" r=".58"/><circle cx="16.07" cy="5.65" r=".58"/>'
          '</g>',
    "IL": '<rect width="24" height="16" fill="#F1F2F1"/>'
          '<rect width="24" height="1.8" fill="#0038B8"/>'
          '<rect y="14.2" width="24" height="1.8" fill="#0038B8"/>'
          '<path d="M12 3.7l2.45 4.25h-4.9z" fill="#0038B8"/>'
          '<path d="M12 12.3l-2.45-4.25h4.9z" fill="#0038B8"/>',
    "IN": '<rect width="24" height="16" fill="#138808"/>'
          '<rect width="24" height="5.34" fill="#FF9933"/>'
          '<rect y="5.33" width="24" height="5.34" fill="#F1F2F1"/>'
          '<circle cx="12" cy="8" r="2.15" fill="none" stroke="#000080" stroke-width=".55"/>'
          '<circle cx="12" cy="8" r=".5" fill="#000080"/>',
    "SG": '<rect width="24" height="16" fill="#F1F2F1"/>'
          '<rect width="24" height="8" fill="#EF3340"/>'
          '<circle cx="4.9" cy="4" r="1.95" fill="#F1F2F1"/>'
          '<circle cx="5.85" cy="4" r="1.65" fill="#EF3340"/>'
          '<g fill="#F1F2F1"><circle cx="7.6" cy="2.1" r=".5"/>'
          '<circle cx="8.7" cy="3.3" r=".5"/><circle cx="8.5" cy="5" r=".5"/>'
          '<circle cx="7.2" cy="6.1" r=".5"/><circle cx="5.6" cy="6.4" r=".5"/></g>',
    "NL": '<rect width="24" height="16" fill="#F1F2F1"/>'
          '<rect width="24" height="5.34" fill="#AE1C28"/>'
          '<rect y="10.66" width="24" height="5.34" fill="#21468B"/>',
    "SE": '<rect width="24" height="16" fill="#006AA7"/>'
          '<rect x="9.6" width="3.2" height="16" fill="#FECC00"/>'
          '<rect y="6.4" width="24" height="3.2" fill="#FECC00"/>',
    "RU": '<rect width="24" height="16" fill="#F1F2F1"/>'
          '<rect width="24" height="5.34" fill="#0039A6"/>'
          '<rect y="10.66" width="24" height="5.34" fill="#D52B1E"/>',
    "UA": '<rect width="24" height="8" fill="#005BBB"/>'
          '<rect y="8" width="24" height="8" fill="#FFD500"/>',
    "IT": '<rect width="8" height="16" fill="#009246"/>'
          '<rect x="8" width="8" height="16" fill="#F1F2F1"/>'
          '<rect x="16" width="8" height="16" fill="#CE2B37"/>',
    "ES": '<rect width="24" height="16" fill="#F1BF00"/>'
          '<rect width="24" height="4" fill="#AA151B"/>'
          '<rect y="12" width="24" height="4" fill="#AA151B"/>',
    "FI": '<rect width="24" height="16" fill="#F1F2F1"/>'
          '<rect x="7.6" width="3.2" height="16" fill="#003580"/>'
          '<rect y="6.4" width="24" height="3.2" fill="#003580"/>',
    "NO": '<rect width="24" height="16" fill="#BA0C2F"/>'
          '<rect x="7.2" width="5.6" height="16" fill="#F1F2F1"/>'
          '<rect y="5.2" width="24" height="5.6" fill="#F1F2F1"/>'
          '<rect x="8.8" width="2.4" height="16" fill="#00205B"/>'
          '<rect y="6.8" width="24" height="2.4" fill="#00205B"/>',
    "DK": '<rect width="24" height="16" fill="#C8102E"/>'
          '<rect x="8" width="2.8" height="16" fill="#F1F2F1"/>'
          '<rect y="6.6" width="24" height="2.8" fill="#F1F2F1"/>',
    "BR": '<rect width="24" height="16" fill="#009B3A"/>'
          '<path d="M12 2.4l9.6 5.6L12 13.6 2.4 8z" fill="#FEDF00"/>'
          '<circle cx="12" cy="8" r="2.7" fill="#002776"/>'
          '<path d="M9.6 7.1a4.6 4.6 0 0 1 5 .9" stroke="#F1F2F1" '
          'stroke-width=".6" fill="none"/>',
    "AU": '<rect width="24" height="16" fill="#00247D"/>'
          '<path d="M0 0l8.6 5.4M8.6 0L0 5.4" stroke="#F1F2F1" stroke-width="1.1"/>'
          '<path d="M4.3 0v5.4M0 2.7h8.6" stroke="#F1F2F1" stroke-width="1.7"/>'
          '<path d="M4.3 0v5.4M0 2.7h8.6" stroke="#C8102E" stroke-width=".85"/>'
          '<g fill="#F1F2F1"><circle cx="6.2" cy="11.4" r=".85"/>'
          '<circle cx="14.6" cy="3.4" r=".55"/><circle cx="17.6" cy="7.4" r=".55"/>'
          '<circle cx="19.4" cy="11.8" r=".55"/>'
          '<circle cx="14.9" cy="14.2" r=".55"/></g>',
}


def flag_svg(code, size=12):
    """国家/地区旗标 SVG（未知代码返回空串）。"""
    body = FLAG_SVGS.get(code or "")
    if not body:
        return ""
    h = int(round(size * 2.0 / 3.0))
    return ('<svg class="flag" viewBox="0 0 24 16" width="%d" height="%d" '
            'aria-hidden="true" focusable="false">%s</svg>' % (size, h, body))


def globe_svg(size=16):
    """全球地域徽标 SVG：线性地球（圆 + 经纬线），随主题文字色。"""
    return ('<svg class="globe" viewBox="0 0 24 24" width="%d" height="%d" '
            'fill="none" stroke="currentColor" stroke-width="1.5" '
            'stroke-linecap="round" aria-hidden="true" focusable="false">'
            '<circle cx="12" cy="12" r="8.6"/>'
            '<ellipse cx="12" cy="12" rx="8.6" ry="3.6"/>'
            '<path d="M12 3.4c-2.6 3.4-2.6 13.8 0 17.2'
            'M12 3.4c2.6 3.4 2.6 13.8 0 17.2"/>'
            '</svg>' % (size, size))


ICON_SOURCE = ('<svg class="hm-ico" viewBox="0 0 24 24" width="13" height="13" '
               'fill="none" stroke="currentColor" stroke-width="1.9" '
               'stroke-linecap="round" aria-hidden="true">'
               '<circle cx="5.6" cy="18.4" r="1.5" fill="currentColor" stroke="none"/>'
               '<path d="M4.2 11.4a8.4 8.4 0 0 1 8.4 8.4"/>'
               '<path d="M4.2 5.6a14.2 14.2 0 0 1 14.2 14.2"/></svg>')
ICON_SPEC = ('<svg class="hm-ico" viewBox="0 0 24 24" width="13" height="13" '
             'fill="none" stroke="currentColor" stroke-width="1.9" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
             '<path d="M13.5 3H7a1.6 1.6 0 0 0-1.6 1.6v14.8A1.6 1.6 0 0 0 7 21h10a1.6 '
             '1.6 0 0 0 1.6-1.6V8.1z"/><path d="M13.4 3.1v5h5.1"/>'
             '<path d="M9.2 14.6l1.9 1.9 3.7-3.7"/></svg>')
ICON_CLOCK = ('<svg class="hm-ico" viewBox="0 0 24 24" width="13" height="13" '
              'fill="none" stroke="currentColor" stroke-width="1.9" '
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
              '<circle cx="12" cy="12" r="8.6"/>'
              '<path d="M12 7.4V12l3.1 1.9"/></svg>')


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark light">
<title>月生 · AI 资讯日报</title>
<style>
/* ============ 主题 token：深空编辑风（默认）/ 暖纸编辑风 ============ */
:root, html[data-theme="dark"]{
  --bg-base:#0A0E17; --bg-surface:#111827; --bg-elevated:#1A2332;
  --border:#233044; --border-glow:rgba(56,189,248,.25);
  --text-primary:#F1F5F9; --text-secondary:#94A3B8; --text-muted:#7D8DA3;
  /* 中性灰：界面控件里需要「高级灰但不偏色相」的场合（如详情页「译文对照」按钮）——
     正文色板是蓝灰系，直接拿它做控件会带上蓝味，与环节彩色一起显得杂乱。 */
  --neutral-ink:#9AA0AA;
  --accent-capability:#22D3EE; --accent-product:#3B82F6; --accent-industry:#8B5CF6;
  --accent-governance:#F59E0B; --accent-frontier:#EC4899;
  --hot:#F97316; --success:#34D399;
  --hot-solid:#F97316; --hot-solid-fg:#000; --hot-deep:#C2410C;
  --cn-num:#F87171; --globe-blue:#5B9BD5;
  /* 月历窗口条数：24H 能力青 → 48H 同族冷蓝（同一冷色域的色相梯度，
     既一眼可辨又明显同属一套；48H 略深，示意「更宽的窗口」） */
  --win24:#22D3EE; --win48:#5B8FF9;
  --imp-bg:#FBBF24; --imp-fg:#1A1208; --imp-border:#F59E0B;
  --shadow-card:0 1px 0 rgba(255,255,255,.02);
  --shadow-pop:0 16px 48px rgba(0,0,0,.5);
  --mark-bg:rgba(249,115,22,.28); --mark-text:#FDBA74;
  --axis-line:#233044; --topbar-h:62px; --axismini-h:46px; --filters-h:49px;
}
html[data-theme="light"]{
  --bg-base:#FAF7F2; --bg-surface:#FFFFFF; --bg-elevated:#F5EFE6;
  --border:#E8DFD0; --border-glow:rgba(13,116,144,.18);
  --text-primary:#1A1A1A; --text-secondary:#5C5C5C; --text-muted:#6E6A63;
  --neutral-ink:#5F646D;
  --accent-capability:#0E7490; --accent-product:#1D4ED8; --accent-industry:#6D28D9;
  --accent-governance:#B45309; --accent-frontier:#BE185D;
  --hot:#C2410C; --success:#047857;
  --hot-solid:#EA580C; --hot-solid-fg:#000; --hot-deep:#C2410C;
  --cn-num:#DE2910; --globe-blue:#2E75B6;
  /* 月历窗口条数：24H 能力青 → 48H 同族冷蓝（同一冷色域的色相梯度，
     既一眼可辨又明显同属一套；48H 略深，示意「更宽的窗口」） */
  --win24:#0E7490; --win48:#2563EB;
  --imp-bg:#FBBF24; --imp-fg:#1A1208; --imp-border:#D97706;
  --shadow-card:0 2px 12px rgba(0,0,0,.06);
  --shadow-pop:0 16px 48px rgba(0,0,0,.14);
  --mark-bg:rgba(194,65,12,.16); --mark-text:#9A3412;
  --axis-line:#E0D6C4; --topbar-h:62px; --axismini-h:46px; --filters-h:49px;
}
@media (prefers-color-scheme: light){
  html[data-theme="auto"]{
    --bg-base:#FAF7F2; --bg-surface:#FFFFFF; --bg-elevated:#F5EFE6;
    --border:#E8DFD0; --border-glow:rgba(13,116,144,.18);
    --text-primary:#1A1A1A; --text-secondary:#5C5C5C; --text-muted:#6E6A63;
  --neutral-ink:#5F646D;
    --accent-capability:#0E7490; --accent-product:#1D4ED8; --accent-industry:#6D28D9;
    --accent-governance:#B45309; --accent-frontier:#BE185D;
    --hot:#C2410C; --success:#047857;
    --hot-solid:#EA580C; --hot-solid-fg:#000; --hot-deep:#C2410C;
  --cn-num:#DE2910; --globe-blue:#2E75B6;
    --win24:#0E7490; --win48:#2563EB;
    --imp-bg:#FBBF24; --imp-fg:#1A1208; --imp-border:#D97706;
    --shadow-card:0 2px 12px rgba(0,0,0,.06);
    --shadow-pop:0 16px 48px rgba(0,0,0,.14);
    --mark-bg:rgba(194,65,12,.16); --mark-text:#9A3412;
    --axis-line:#E0D6C4; --topbar-h:62px; --axismini-h:46px; --filters-h:49px;
  }
}
@media (prefers-color-scheme: dark){
  html[data-theme="auto"]{
    --bg-base:#0A0E17; --bg-surface:#111827; --bg-elevated:#1A2332;
    --border:#233044; --border-glow:rgba(56,189,248,.25);
    --text-primary:#F1F5F9; --text-secondary:#94A3B8; --text-muted:#7D8DA3;
  /* 中性灰：界面控件里需要「高级灰但不偏色相」的场合（如详情页「译文对照」按钮）——
     正文色板是蓝灰系，直接拿它做控件会带上蓝味，与环节彩色一起显得杂乱。 */
  --neutral-ink:#9AA0AA;
    --accent-capability:#22D3EE; --accent-product:#3B82F6; --accent-industry:#8B5CF6;
    --accent-governance:#F59E0B; --accent-frontier:#EC4899;
    --hot:#F97316; --success:#34D399;
    --shadow-card:0 1px 0 rgba(255,255,255,.02);
    --shadow-pop:0 16px 48px rgba(0,0,0,.5);
    --mark-bg:rgba(249,115,22,.28); --mark-text:#FDBA74;
    --axis-line:#233044; --topbar-h:62px; --axismini-h:46px; --filters-h:49px;
  }
}
/* ============ 基础形制 ============ */
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  background:var(--bg-base);color:var(--text-primary);
  font-family:"PingFang SC","HarmonyOS Sans SC","Source Han Sans SC",
    "Noto Sans CJK SC","Microsoft YaHei",Inter,system-ui,sans-serif;
  /* 正文字号受「可读性设置」控制（--fs 默认 1，三档 1 / 1.08 / 1.16） */
  font-size:calc(15px * var(--fs, 1));line-height:1.65;-webkit-font-smoothing:antialiased;
  transition:background .25s ease-out,color .25s ease-out;
}
::selection{background:var(--border-glow)}
a{color:inherit}
button{font:inherit;color:inherit;background:none;border:none;cursor:pointer}
:focus-visible{outline:2px solid var(--accent-capability);outline-offset:2px;border-radius:6px}
.wrap{max-width:1280px;margin:0 auto;padding:0 24px}
.src-notice{margin:10px 0 0;padding:9px 14px;border-radius:10px;
  font-size:12.5px;color:var(--text-secondary);background:var(--bg-elevated);
  border:1px solid color-mix(in srgb,var(--hot) 35%,var(--border))}
svg{flex:none}
.flag{flex:none}
.day[hidden]{display:none}

/* ============ 顶栏 ============ */
.topbar{
  position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:14px;
  padding:10px 24px;background:var(--bg-base);
  background:color-mix(in srgb,var(--bg-base) 88%,transparent);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--border);
  transition:transform .28s cubic-bezier(.16,.84,.44,1);
}
/* 移动端向下阅读时收起顶栏（内容优先），向上滚动立刻出现 */
.topbar.tuck{transform:translateY(-100%)}
.brand{display:flex;align-items:flex-end;gap:9px;font-weight:700;font-size:16px;
  letter-spacing:.02em;white-space:nowrap}
.brand svg{color:var(--accent-capability)}
/* 英文名：小于中文、与中文基线（底部）对齐 */
.brand-text{display:inline-flex;align-items:flex-end;gap:7px}
.brand small{font-weight:600;color:var(--text-muted);font-size:10.5px;
  letter-spacing:.16em;text-transform:uppercase;white-space:nowrap}
.topbar .spacer{flex:1}

/* 日期选择器：按钮 */
.datepicker{position:relative}
.date-btn{display:flex;align-items:center;gap:9px;padding:5px 11px;border-radius:11px;
  border:1px solid var(--border);background:var(--bg-surface);transition:border-color .15s}
.date-btn:hover{border-color:var(--accent-capability)}
.date-btn>svg{color:var(--text-muted)}
.date-btn-text{display:flex;flex-direction:column;align-items:flex-start;line-height:1.25}
/* 上行：短日期 + 双窗口条数，flex 同行紧贴 */
.date-btn-top{display:flex;align-items:center;gap:7px}
.date-btn-text b{font-size:13px;font-weight:650;font-variant-numeric:tabular-nums}
.date-btn-text i{font-style:normal;font-size:10.5px;color:var(--text-muted);
  white-space:nowrap}
/* 收起态双条数：与月历格内同款（仅条数，不用文字标签），高亮即当前窗口 */
.date-btn-counts{display:inline-flex;align-items:center;gap:7px;flex:none;
  padding-left:7px;border-left:1px solid var(--border)}
.date-btn-counts .dc-chip{padding:1px 4px}
.date-caret{transition:transform .2s ease-out}
.date-btn[aria-expanded="true"] .date-caret{transform:rotate(180deg)}

/* 日期选择器：月历面板（日期 + 24h/48h 双窗口条数） */
.dm{position:absolute;top:calc(100% + 10px);left:0;z-index:80;width:344px;
  padding:12px 12px 9px;border-radius:16px;background:var(--bg-surface);
  border:1px solid var(--border);box-shadow:var(--shadow-pop);
  animation:dm-in .18s cubic-bezier(.16,.84,.44,1)}
.dm[hidden]{display:none}
@keyframes dm-in{from{opacity:0;transform:translateY(-6px) scale(.985)}
  to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.dm{animation:none}}
.dm::before{content:"";position:absolute;left:1px;right:1px;top:0;height:1px;
  border-radius:16px 16px 0 0;pointer-events:none;
  background:linear-gradient(90deg,transparent,
    color-mix(in srgb,var(--accent-capability) 42%,transparent),transparent)}
.dm-head{display:flex;align-items:center;gap:6px;margin-bottom:9px}
.dm-title{flex:1;display:flex;flex-direction:column;align-items:center;line-height:1.25}
.dm-title b{font-size:13.5px;font-weight:700;letter-spacing:.02em;
  font-variant-numeric:tabular-nums}
.dm-title i{font-style:normal;font-size:9.5px;color:var(--text-muted);
  letter-spacing:.06em;text-transform:uppercase}
.dm-nav{flex:none;width:26px;height:26px;border-radius:9px;border:1px solid transparent;
  background:var(--bg-elevated);color:var(--text-secondary);cursor:pointer;
  display:grid;place-items:center;transition:all .14s ease-out}
.dm-nav:hover:not(:disabled){color:var(--text-primary);
  background:color-mix(in srgb,var(--accent-capability) 14%,transparent);
  border-color:color-mix(in srgb,var(--accent-capability) 34%,transparent)}
.dm-nav:disabled{opacity:.26;cursor:not-allowed}
.dm-today{flex:none;padding:4px 8px;border-radius:8px;font-size:10px;font-weight:700;
  letter-spacing:.04em;border:1px solid var(--border);background:var(--bg-elevated);
  color:var(--text-secondary);cursor:pointer;transition:all .14s ease-out}
.dm-today:hover{color:var(--text-primary);border-color:var(--accent-capability)}
.dm-week{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;margin-bottom:3px}
.dm-week span{text-align:center;font-size:10px;font-weight:600;color:var(--text-muted)}
.dm-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
/* 月初空位占位（维持与星期表头对齐） */
.dm-pad{height:54px}
/* 格内几何：空日与有数据日共用同一条规则（同高、同内边距、同间隙、
   日号顶部定距），保证两种格子的日号与条数行位置逐像素一致 */
.dm-cell,.date-opt{height:54px;display:flex;flex-direction:column;align-items:center;
  justify-content:flex-start;gap:3px;padding:7px 2px 0;
  border:1px solid transparent;border-radius:11px}
.dm-cell{background:none}
.dm-cell.is-empty .dc-day{color:var(--text-muted);opacity:.42}
.date-opt.is-off{cursor:not-allowed}
/* 单日格：日期 + 24H/48H 条数（颜色区分，含义见图例） */
.date-opt{position:relative;background:none;cursor:pointer;
  transition:background .14s ease-out,border-color .14s ease-out,transform .14s ease-out}
.date-opt:hover:not(:disabled){background:var(--bg-elevated);transform:translateY(-1px)}
.date-opt:focus-visible{outline:2px solid var(--accent-capability);outline-offset:1px}
.dc-day{font-size:13px;font-weight:700;line-height:1;color:var(--text-secondary);
  font-variant-numeric:tabular-nums}
.date-opt[aria-selected="true"]{
  background:color-mix(in srgb,var(--accent-capability) 15%,transparent);
  border-color:color-mix(in srgb,var(--accent-capability) 42%,transparent)}
.date-opt[aria-selected="true"] .dc-day{color:var(--accent-capability)}
/* 最新完整日报日：底部红条，绝对定位不参与排版 */
.date-opt.is-latest::after{content:"";position:absolute;left:50%;bottom:2px;
  transform:translateX(-50%);width:12px;height:2px;border-radius:1px;
  background:var(--hot)}
/* 进行中的当天：日号右侧琥珀圆点（行内元素，不改变行高） */
.date-opt.is-live .dc-day::after{content:"";display:inline-block;width:4px;height:4px;
  margin-left:3px;border-radius:50%;background:var(--accent-industry);
  vertical-align:super}
/* 条数行：高度固定 + 条数不换行不收缩，保证每个格子一行、两格同构 */
.dc-n{display:flex;align-items:center;justify-content:center;gap:2px;height:12px}
.dc-chip{display:inline-flex;align-items:center;flex:none;white-space:nowrap;
  padding:0 1px;border-radius:4px;font-size:9.5px;font-weight:800;line-height:1;
  font-variant-numeric:tabular-nums;
  transition:background .13s ease-out,color .13s ease-out}
.dc-chip.c24{color:var(--win24)}
.dc-chip.c48{color:var(--win48)}
.dc-chip:hover{background:color-mix(in srgb,currentColor 16%,transparent)}
.dc-chip.is-on{background:color-mix(in srgb,currentColor 22%,transparent);
  box-shadow:0 0 0 1px color-mix(in srgb,currentColor 34%,transparent)}
.dm-foot{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  margin-top:9px;padding-top:8px;border-top:1px solid var(--border)}
.dm-lg{display:inline-flex;align-items:center;gap:5px;font-size:9.5px;color:var(--text-muted)}
.dm-lg i{width:14px;height:3px;border-radius:2px;flex:none}
.dm-lg .lg24{background:var(--win24)}
.dm-lg .lg48{background:var(--win48)}
.dm-tip{margin-left:auto;font-size:9.5px;color:var(--text-muted);letter-spacing:.02em}

/* 搜索框是顶栏里唯一允许伸缩的控件：宽度收缩时不得挤压相邻控件。
   flex 布局下默认 min-width:auto 会让 input 顶住内在宽度，必须显式归零。 */
.searchbox{position:relative;display:flex;align-items:center;flex:0 1 auto;min-width:0}
.searchbox svg{position:absolute;left:10px;color:var(--text-muted);pointer-events:none}
.searchbox input{
  width:220px;min-width:0;padding:7px 12px 7px 32px;border-radius:10px;
  border:1px solid var(--border);background:var(--bg-surface);
  color:var(--text-primary);font-size:13.5px;transition:width .2s ease-out,border-color .2s;
}
.searchbox input:focus{width:280px;border-color:var(--accent-capability);outline:none}
.searchbox input::placeholder{color:var(--text-muted)}
/* 色系三态：宽度固定（flex:none）+ 按钮文字不换行 —— 搜索框变长时不得被压缩
   （曾被压到每字一行，竖排显示）。 */
.theme-switch{display:flex;flex:none;border:1px solid var(--border);border-radius:10px;
  overflow:hidden;background:var(--bg-surface)}
.theme-switch button{padding:6px 11px;font-size:12.5px;color:var(--text-muted);
  display:flex;align-items:center;gap:5px;white-space:nowrap;transition:all .15s ease-out}
.theme-switch button[aria-pressed="true"]{background:var(--bg-elevated);color:var(--text-primary)}
.theme-switch button svg{width:13px;height:13px}

/* ============ Hero：入档条数为视觉主体（编辑风） ============ */
/* 左列顶对齐（整体上移），右侧分布面板位置不变 */
.hero{display:flex;align-items:flex-start;justify-content:space-between;gap:36px;
  flex-wrap:wrap;padding:26px 0 12px;position:relative}
/* 光晕定宽 900px + 居中：窄屏会把文档撑宽 248px（横向可滑动），
   故收成 min(900px,100%)——宽屏保持原尺寸，窄屏收进容器，不必裁切。 */
.hero::before{content:"";position:absolute;left:50%;top:-26px;width:min(900px,100%);
  height:260px;
  transform:translateX(-50%);pointer-events:none;
  background:radial-gradient(50% 50% at 50% 50%,
    color-mix(in srgb,var(--accent-capability) 7%,transparent),transparent 70%)}
.hero-main{position:relative;flex:1;min-width:300px}
.hero-eyebrow{font-size:11.5px;letter-spacing:.18em;color:var(--text-muted);
  text-transform:uppercase;font-weight:600;display:flex;align-items:center;gap:8px}
.hero-pulse{width:7px;height:7px;border-radius:50%;background:var(--hot);flex:none;
  animation:pulse 2.6s ease-out infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--hot) 55%,transparent)}
  70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
.hero-date-mini{display:flex;align-items:baseline;gap:10px}
/* 日期为重点信息：大号 + 加重 + 主色下划线 */
.hero-date-mini b{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums;
  letter-spacing:.01em;color:var(--text-primary);line-height:1;
  padding-bottom:3px;border-bottom:2px solid var(--accent-capability)}
.hero-date-mini span{font-size:12px;color:var(--text-muted);white-space:nowrap}
/* 进行中徽标：该自然日尚未结束（数据未覆盖到 24:00） */
.live-badge{display:inline-flex;align-items:center;gap:5px;align-self:center;flex:none;
  padding:2px 8px 3px;border-radius:999px;font-size:10.5px;font-weight:700;
  letter-spacing:.01em;color:var(--accent-industry);
  background:color-mix(in srgb,var(--accent-industry) 12%,transparent);
  border:1px solid color-mix(in srgb,var(--accent-industry) 32%,transparent);
  cursor:help}
.live-badge::before{content:"";width:5px;height:5px;border-radius:50%;flex:none;
  background:currentColor;animation:pulse 2.6s ease-out infinite}
@media (prefers-reduced-motion:reduce){.live-badge::before{animation:none}}
/* 晨报标题 + 日期同一行，日期贴最右（与 meta 行右侧三项事实同一右边缘） */
.hero-topline{display:flex;flex-direction:row;align-items:baseline;
  justify-content:space-between;gap:14px;flex-wrap:wrap;
  margin-top:-8px;padding-bottom:11px;border-bottom:1px solid var(--border)}
/* meta 行内「时间窗口」切换器：胶囊轨道 + 滑动指示块（48h 时为次级色） */
.hm-win{display:inline-flex;align-items:center;gap:7px}
.hw-label{font-size:12px;color:var(--text-muted)}
.hw-switch{position:relative;display:inline-flex;align-items:center;padding:2px;
  border-radius:999px;background:var(--bg-elevated);border:1px solid var(--border);
  flex:none}
.hw-thumb{position:absolute;top:2px;left:2px;width:calc(50% - 2px);
  height:calc(100% - 4px);border-radius:999px;
  background:linear-gradient(118deg,var(--accent-capability),
    color-mix(in srgb,var(--accent-product) 52%,var(--accent-capability)));
  box-shadow:0 1px 6px color-mix(in srgb,var(--accent-capability) 36%,transparent);
  transition:transform .3s cubic-bezier(.34,.9,.3,1)}
.hw-switch.on-48 .hw-thumb{transform:translateX(100%)}
.hw-btn{position:relative;z-index:1;min-width:40px;padding:2.5px 0;border:none;
  background:none;font-family:inherit;font-size:11px;font-weight:700;
  letter-spacing:.02em;color:var(--text-muted);cursor:pointer;
  transition:color .18s ease-out}
.hw-btn small{font-size:9px;font-weight:700;opacity:.66;margin-left:.5px}
.hw-btn:hover{color:var(--text-primary)}
.hw-btn.is-on{color:#04121A}
html[data-theme="light"] .hw-btn.is-on{color:#fff}
@media (prefers-reduced-motion:reduce){.hw-thumb{transition:none}}
/* meta 行右端：信源 · 规范 · 生成时间三项事实（图标随语义，仅数字与规范号用强调色） */
.hm-right{display:inline-flex;align-items:center;gap:9px;margin-left:auto;
  flex-wrap:wrap;justify-content:flex-end}
.hm-fact{display:inline-flex;align-items:center;gap:5px;font-size:12px;
  color:var(--text-muted);white-space:nowrap;cursor:help}
.hm-ico{flex:none;color:var(--accent-capability)}
.hm-fact b{font-weight:800;font-size:14px;color:var(--accent-capability);
  font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.hm-tval{color:var(--text-muted);font-weight:400;font-variant-numeric:tabular-nums}
.hero-figure{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
  padding:22px 0 2px}
/* 地域构成：与总条数同行（hero-figure 行内右端），成对呈现、不用边框框起 */
.hero-region{display:inline-flex;align-items:center;gap:16px;margin-left:14px;
  align-self:flex-end;margin-bottom:7px}
.hr-sep{width:1px;height:34px;flex:none;
  background:linear-gradient(180deg,transparent,
    color-mix(in srgb,var(--text-muted) 55%,transparent),transparent)}
.hr-item{display:inline-flex;align-items:center;gap:7px;font-size:13px;
  font-weight:700;color:var(--text-secondary);white-space:nowrap;cursor:help}
.hr-item b{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;
  letter-spacing:-.01em;line-height:1}
.hr-item .flag,.hr-item .globe{flex:none}
.hr-cn b{color:var(--cn-num)}
.hr-global b{color:var(--globe-blue)}
.hr-global .globe{color:var(--globe-blue)}
.hero-num{font-size:clamp(78px,10vw,116px);font-weight:800;line-height:.9;
  letter-spacing:-.035em;font-variant-numeric:tabular-nums;
  background:linear-gradient(122deg,var(--text-primary) 24%,
    color-mix(in srgb,var(--accent-capability) 75%,var(--text-primary)));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.hero-unit{font-size:27px;font-weight:700;color:var(--text-secondary)}
.hero-fig-label{display:flex;flex-direction:column;gap:3px;padding-bottom:7px}
.hero-fig-label b{font-size:16.5px;font-weight:700;letter-spacing:.01em}
.hero-fig-label i{font-style:normal;font-size:9.5px;font-weight:600;
  letter-spacing:.16em;color:var(--text-muted);text-transform:uppercase}
.hero-meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  font-size:12.5px;color:var(--text-muted);padding-top:8px}
.hero-meta i{width:1px;height:12px;background:var(--border);flex:none}
.hm-item{display:inline-flex;align-items:center;gap:6px}
/* Hero 右：当日五环节分布面板 */
.hero-dist{flex:none;width:336px;padding:13px 16px 11px;border-radius:16px;
  background:var(--bg-surface);border:1px solid var(--border);
  box-shadow:var(--shadow-card)}
.hd-title{display:flex;align-items:baseline;gap:8px;font-size:12.5px;
  font-weight:700;margin-bottom:10px}
.hd-title i{font-style:normal;font-size:9px;font-weight:600;letter-spacing:.12em;
  color:var(--text-muted);text-transform:uppercase}
.hd-row{display:flex;align-items:center;gap:10px;padding:5.5px 0}
.hd-name{flex:none;width:36px;font-size:12px;color:var(--text-secondary);
  font-weight:600}
.hd-bar{flex:1;height:6px;border-radius:3px;background:var(--bg-elevated);
  overflow:hidden}
.hd-bar i{display:block;height:100%;border-radius:3px;background:var(--nc);
  min-width:2px}
.hd-num{flex:none;width:64px;text-align:right;font-variant-numeric:tabular-nums;
  display:flex;align-items:baseline;justify-content:flex-end;gap:5px}
/* 条数按节点色突出，百分比保持中性 */
.hd-num b{font-size:13.5px;font-weight:800;color:var(--nc)}
.hd-num em{font-style:normal;font-size:10px;color:var(--text-muted)}

/* ============ 价值链主轴（L1 核心看点） ============ */
.axis-hero{
  margin:16px 0 13px;padding:16px 20px 14px;border-radius:20px;position:relative;
  background:
    radial-gradient(130% 150% at 50% -40%,
      color-mix(in srgb,var(--accent-capability) 8%,transparent),transparent 62%),
    var(--bg-surface);
  border:1px solid var(--border);box-shadow:var(--shadow-card);
}
.ah-head{display:flex;align-items:center;justify-content:space-between;gap:14px;
  flex-wrap:wrap;margin-bottom:11px}
.ah-title{display:flex;align-items:center;gap:11px}
.ah-icon{display:flex;align-items:center;justify-content:center;width:34px;height:34px;
  border-radius:10px;color:var(--accent-capability);
  background:color-mix(in srgb,var(--accent-capability) 12%,transparent);
  border:1px solid color-mix(in srgb,var(--accent-capability) 30%,transparent)}
.ah-title-text{display:flex;flex-direction:column;line-height:1.3}
.ah-title-text b{font-size:16.5px;font-weight:700;letter-spacing:.01em}
.ah-title-text i{font-style:normal;font-size:10px;font-weight:600;letter-spacing:.14em;
  color:var(--text-muted);text-transform:uppercase}
/* 热点横条：标题右侧统计标（交叉热点，首屏唯一醒目出处）
   颜色规则（用户 2026-10-14 定）：交叉热点=深橙实底 + 白字（白字对比度达标
   需用 #C2410C 深橙，亮橙 #F97316 上白字仅 2.8:1）；
   「涉及中国」为入档总条数口径，已移至 Hero meta 行（hm-cn），不在此并排 */
.hotbar-stats{display:flex;align-items:center;gap:8px;margin-left:auto;flex:none}
.hs-chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px 4px;
  border-radius:10px;line-height:1.25;cursor:help}
.hs-chip b{font-size:15.5px;font-weight:800;font-variant-numeric:tabular-nums;
  letter-spacing:-.01em}
.hs-t{display:flex;flex-direction:column;font-size:9.5px;font-weight:600}
.hs-t i{font-style:normal;font-size:8px;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;opacity:.72}
.hs-hot{background:var(--hot-deep);color:#fff}
.hs-hot .hs-t i{opacity:.78}
.ah-track{position:relative;display:flex;gap:12px;padding:6px 0 0}
.ah-flow{position:absolute;left:7%;right:7%;top:32px;height:2px;border-radius:1px;
  background:linear-gradient(90deg,var(--accent-capability),var(--accent-product),
    var(--accent-industry),var(--accent-governance),var(--accent-frontier));
  background-size:220% 100%;opacity:.45;animation:ahflow 10s linear infinite}
@keyframes ahflow{to{background-position:-220% 0}}
.ah-node{
  flex:1;min-width:0;display:flex;flex-direction:column;gap:7px;align-items:flex-start;
  padding:14px 14px 13px;border-radius:14px;position:relative;z-index:1;text-align:left;
  background:var(--bg-surface);border:1px solid var(--border);
  transition:transform .2s ease-out,border-color .2s ease-out,box-shadow .2s ease-out,
    background .2s ease-out;
}
.ah-node:hover{transform:translateY(-2px);
  border-color:color-mix(in srgb,var(--nc) 50%,var(--border))}
.ah-node[aria-current="true"]{
  transform:translateY(-3px);border-color:var(--nc);
  background:linear-gradient(180deg,
    color-mix(in srgb,var(--nc) 11%,var(--bg-surface)),var(--bg-surface));
  box-shadow:0 0 0 1px color-mix(in srgb,var(--nc) 35%,transparent),
    0 10px 26px color-mix(in srgb,var(--nc) 14%,transparent);
}
.ahn-top{display:flex;align-items:center;justify-content:space-between;width:100%;gap:8px}
.ahn-index{font-size:22px;font-weight:800;color:var(--nc);line-height:1;
  font-variant-numeric:tabular-nums;letter-spacing:.02em}
.ahn-count{font-size:11px;font-weight:700;color:var(--nc);
  background:color-mix(in srgb,var(--nc) 12%,transparent);
  border:1px solid color-mix(in srgb,var(--nc) 32%,transparent);
  padding:1px 8px;border-radius:6px;font-variant-numeric:tabular-nums;white-space:nowrap}
.ahn-names{display:flex;flex-direction:column;gap:1px}
.ahn-names b{font-size:16.5px;font-weight:700;letter-spacing:.01em}
.ahn-names i{font-style:normal;font-size:9.5px;font-weight:600;letter-spacing:.16em;
  color:var(--text-muted);text-transform:uppercase}
.ahn-desc{font-size:11.5px;color:var(--text-secondary);line-height:1.5;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ahn-flag{position:absolute;top:-9px;right:10px;font-size:10px;font-weight:800;
  color:var(--hot-solid-fg);background:var(--hot-solid);padding:1.5px 8px;border-radius:999px;
  letter-spacing:.06em;
  box-shadow:0 2px 8px color-mix(in srgb,var(--hot-solid) 45%,transparent)}

/* ============ 迷你主轴（滚动常驻） ============ */
.axis-mini{
  position:fixed;left:0;right:0;top:var(--topbar-h);z-index:30;
  background:color-mix(in srgb,var(--bg-base) 88%,transparent);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--border);
  opacity:0;pointer-events:none;transform:translateY(-6px);
  transition:opacity .2s ease-out,transform .2s ease-out;
}
.axis-mini.show{opacity:1;pointer-events:auto;transform:none}
.am-inner{max-width:1280px;margin:0 auto;display:flex;align-items:center;gap:4px;
  padding:7px 24px;overflow-x:auto;scrollbar-width:none}
.am-inner::-webkit-scrollbar{display:none}
.am-brand{font-size:10.5px;font-weight:700;letter-spacing:.12em;color:var(--text-secondary);
  margin-right:10px;white-space:nowrap}
.am-btn{display:flex;align-items:center;gap:7px;padding:5px 11px;border-radius:9px;
  font-size:12.5px;color:var(--text-primary);white-space:nowrap;
  transition:all .15s ease-out}
.am-btn i{width:8px;height:8px;border-radius:50%;background:var(--nc);opacity:.5;
  transition:all .15s ease-out;flex:none}
.am-btn em:not(.am-flag){font-style:normal;font-size:11px;color:var(--text-primary);
  font-variant-numeric:tabular-nums;opacity:.78}
.am-btn:hover{background:var(--bg-elevated)}
.am-btn[aria-current="true"]{background:color-mix(in srgb,var(--nc) 13%,transparent);
  color:var(--text-primary);font-weight:600}
.am-btn[aria-current="true"] i{opacity:1;
  box-shadow:0 0 0 3px color-mix(in srgb,var(--nc) 25%,transparent)}
.am-flag{font-style:normal;font-size:9.5px;font-weight:800;color:var(--hot-solid-fg);
  background:var(--hot-solid);border-radius:999px;padding:1px 6px;letter-spacing:.04em}

/* ============ 热点横条 ============ */
.hotbar{margin:12px 0 4px;border-radius:14px;border:1px solid var(--border);
  background:var(--bg-elevated);overflow:hidden}
.hotbar-head{display:flex;align-items:center;gap:9px 14px;flex-wrap:wrap;
  padding:10px 16px;font-size:13.5px;font-weight:650;color:var(--text-primary)}
.hotbar-head svg{color:var(--hot)}
.hotbar-title{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.hotbar-title i{font-style:normal;font-size:10px;font-weight:600;letter-spacing:.1em;
  color:var(--text-muted);text-transform:uppercase}
.hot-item{border-top:1px solid var(--border)}
.hot-head{display:flex;align-items:center;gap:12px;width:100%;padding:9px 16px;
  text-align:left;transition:background .15s ease-out}
.hot-head:hover{background:color-mix(in srgb,var(--bg-surface) 60%,transparent)}
.hot-count{
  flex:none;font-size:11px;font-weight:700;padding:2px 9px;border-radius:999px;
  color:var(--hot);border:1px solid color-mix(in srgb,var(--hot) 45%,transparent);
  background:color-mix(in srgb,var(--hot) 12%,transparent);
  font-variant-numeric:tabular-nums;
}
.hot-title{flex:0 1 auto;min-width:0;font-size:13.5px;color:var(--text-primary);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* 名称后来源国旗（紧贴标题，与字保持间距；一信源一旗，同国多旗保留） */
.hot-flags{flex:none;display:inline-flex;align-items:center;gap:5px;margin-left:10px}
.hot-flag{display:inline-flex;align-items:center;border-radius:2px;
  box-shadow:0 0 0 1px color-mix(in srgb,var(--border) 80%,transparent)}
.hot-flag .flag{display:block}
/* 热点条上的「涉及中国」标记：**与卡片 .card-region 同一套视觉**（中性成功色描边），
   不再自造红底实心标徽——红色国旗在深色底上过于刺眼，且与卡片标注不同源。
   判定口径与卡片一致（见 view_projection.project_hot_events：取面板落点条目的region）。 */
.hot-cn{flex:none;display:inline-flex;align-items:center;gap:5px;font-size:10.5px;
  font-weight:600;padding:1.5px 8px;border-radius:999px;
  color:var(--success);border:1px solid color-mix(in srgb,var(--success) 45%,transparent);
  background:color-mix(in srgb,var(--success) 10%,transparent)}
.hot-cn .flag{flex:none}
.hot-arrow{margin-left:auto}
.hot-arrow{color:var(--text-muted);transition:transform .2s ease-out;flex:none}
.hot-head[aria-expanded="true"] .hot-arrow{transform:rotate(180deg)}
.hot-timeline{list-style:none;padding:2px 18px 12px 18px}
.hot-timeline li{display:flex;align-items:center;gap:8px;padding:5px 0;
  font-size:12.5px;color:var(--text-secondary)}
.hot-timeline .flag{flex:none;border-radius:1px}
.hot-timeline a{color:var(--accent-capability);text-decoration:none;
  border-bottom:1px dotted color-mix(in srgb,var(--accent-capability) 50%,transparent)}
.hot-timeline a:hover{border-bottom-style:solid}
.hot-src-meta{color:var(--text-muted);font-size:11.5px;white-space:nowrap}
/* 同一信源的其余收录（附域名，弱化处理）：与独立信源行区分，链接不丢 */
.hot-timeline .hot-more{font-size:11px;color:var(--text-secondary);opacity:.85;
  border-bottom-style:dotted}
.hot-empty{padding:6px 18px 14px;font-size:12.5px;color:var(--text-muted)}

/* ============ 分区与属性筛选栏 ============
   吸顶栈只有三层：顶栏 → 快捷栏(.axis-mini) → 本筛选栏，层间零缝隙。
   **环节节头(.node-head)不吸顶**——它是小节标题，跟着正文滚走才对；
   让它吸顶会与筛选栏争夺同一段视口顶部空间，是历次叠字/缝隙故障的根源。

   【本筛选栏为什么必须吸在快捷栏下方，而不是紧贴顶栏】
   `.axis-mini`（迷你主轴快捷栏）是 `position:fixed; top:var(--topbar-h)`，
   恒定占据「顶栏下沿往下约 46px」这一段，**不随 .filters 的 top 变化而让位**。
   早先 `.filters` 写成 `top:var(--topbar-h)`（=62px），与快捷栏的停靠位置
   完全相同 —— 实测（无头 Chrome + CDP，1440×900）滚动全程 31 个停靠样本
   **100% 竖直区间相交**，两层控件的文字直接叠在一起。
   故本栏吸顶位置 = 顶栏实测高 + **快捷栏实测高**（--axismini-h），
   恰好落在快捷栏下沿，层间不夹margin，缝隙恒为 0。

   【实测过的安全性】快捷栏由 `.show` 控制显隐（滚过主轴区才出现），
   但 .filters 停靠时快捷栏**必定已show**（实测未 show 的停靠样本 0 个）——
   因为快捷栏的显现阈值（主轴区底部 < 64px）必然早于筛选栏触顶。
   若日后改了这个阈值，必须重跑 `validate_sticky.js` 复核。

   --axismini-h 由 syncAxisMiniH() 实测写入；窄屏快捷栏 display:none 时写 0，
   本栏自动退回「紧贴顶栏」。 */
.filters{
  display:flex;align-items:center;flex-wrap:wrap;gap:10px;
  padding:10px 0 4px;
  position:sticky;
  top:calc(var(--topbar-h,62px) + var(--axismini-h,46px));
  z-index:22;
  background:var(--bg-base);
  background:color-mix(in srgb,var(--bg-base) 92%,transparent);backdrop-filter:blur(12px);
}
.seg{display:flex;border:1px solid var(--border);border-radius:10px;overflow:hidden;
  background:var(--bg-surface)}
.seg button{padding:6px 14px;font-size:12.5px;color:var(--text-muted);transition:all .15s ease-out}
.seg button[aria-pressed="true"]{background:var(--bg-elevated);color:var(--text-primary);font-weight:600}
.filter-label{font-size:12px;color:var(--text-muted);display:inline-flex;
  align-items:baseline;gap:5px}
.filter-label i{font-style:normal;font-size:9px;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;opacity:.75}
.tagchip{
  padding:4px 12px;border-radius:999px;font-size:12px;color:var(--text-secondary);
  border:1px solid var(--border);background:var(--bg-surface);transition:all .15s ease-out;
}
.tagchip[aria-pressed="true"]{
  color:var(--accent-capability);border-color:color-mix(in srgb,var(--accent-capability) 55%,transparent);
  background:color-mix(in srgb,var(--accent-capability) 10%,transparent);font-weight:600;
}
.filter-reset{margin-left:auto;font-size:12px;color:var(--text-muted);text-decoration:underline;
  text-underline-offset:3px}
.filter-reset:hover{color:var(--text-primary)}

/* ============ 五节点正文（分区容器与主轴同色系） ============ */
main{padding-bottom:28px}
.node{
  margin-top:20px;padding:18px 20px 16px;border-radius:18px;
  scroll-margin-top:calc(var(--topbar-h,62px) + var(--axismini-h,46px)
                        + var(--filters-h,49px) + 14px);
  background:linear-gradient(180deg,
    color-mix(in srgb,var(--nc) 4.5%,transparent),transparent 42%),var(--bg-base);
  border:1px solid color-mix(in srgb,var(--nc) 15%,var(--border));
}
/* 环节节头：**不吸顶**。
   它是小节标题，本就该随正文滚走。吸顶会让它与筛选栏争夺同一段视口顶部空间，
   是历次「叠字」与「透明缝隙」故障的共同根源（实测记录见上方「分区与属性筛选栏」）。
   因此这里没有 position:sticky、没有 top、没有 z-index；
   随之失效的还有 .is-stuck 补底机制与下缘渐隐伪元素——它们只在吸顶时有触发条件，
   已一并移除，不留死代码。
   底色保持透明，与所在面板底色一致，不会出现「标题后面一个矩形色块」。
   【通用通则】吸顶层之间的间距一律用 padding，禁用 margin——margin 不属背景盒，
   是「层间恒定透明缝隙」的根因；非吸顶元素不受此限。 */
.node-head{
  position:relative;
  padding:9px 0 15px;background:transparent;
}
.node-head-bar{height:3px;width:64px;border-radius:2px;margin-bottom:10px;
  background:linear-gradient(90deg,var(--nc),color-mix(in srgb,var(--nc) 12%,transparent))}
.node-title-row{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.node-index{
  font-size:12px;font-weight:700;font-variant-numeric:tabular-nums;
  color:var(--nc);border:1px solid color-mix(in srgb,var(--nc) 45%,transparent);
  padding:2px 8px;border-radius:6px;background:color-mix(in srgb,var(--nc) 10%,transparent);
}
.node-names{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.node h2{font-size:clamp(19px,2.2vw,23px);font-weight:700;letter-spacing:.01em}
.node-names i{font-style:normal;font-size:10.5px;font-weight:600;letter-spacing:.16em;
  color:var(--text-muted);text-transform:uppercase}
/* 节点描述：标题行中部右对齐、强制单行（省略号收尾），填充标题右侧空间 */
.node-desc{flex:1;min-width:0;text-align:right;margin:0 6px;
  font-size:calc(12.5px * var(--fs, 1));color:var(--text-secondary);line-height:1.5;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.node-desc::before{content:"";display:inline-block;width:22px;height:1px;
  vertical-align:middle;margin-right:9px;
  background:linear-gradient(90deg,transparent,var(--nc))}
/* 条数：行末统计读数（大数字 + 分隔线），与行首编号形成明确区隔，不再相像 */
.node-count{flex:none;display:inline-flex;align-items:baseline;gap:4px;
  margin-left:12px;padding-left:16px;border-left:1px solid var(--border)}
.node-count b{font-size:24px;font-weight:800;color:var(--nc);line-height:1;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.node-count i{font-style:normal;font-size:11.5px;font-weight:700;
  color:var(--text-muted)}
.node-empty{
  padding:26px 22px;border-radius:14px;border:1px dashed var(--border);
  color:var(--text-muted);font-size:13.5px;text-align:center;
  background:color-mix(in srgb,var(--bg-surface) 45%,transparent);
}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
/* 渐进加载：超出「已展开」的卡片用 hidden 收起（`.card` 自带 display:flex，
   必须显式覆盖，否则 UA 的 [hidden]{display:none} 优先级不够）。
   取代原先的「查看全部」——100+ 条一次铺开，收起时文档高度骤减、视口必然乱跳。 */
.card[hidden]{display:none!important}
.more-bar{
  display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;
  margin-top:15px;padding-top:13px;border-top:1px dashed var(--border);
}
.mb-count{font-size:12px;color:var(--text-muted);font-variant-numeric:tabular-nums}
.mb-count b{font-size:16px;font-weight:800;color:var(--nc);
  font-variant-numeric:tabular-nums;padding:0 1px}
.more-btn{
  padding:8px 22px;border-radius:10px;border:1px solid var(--border);
  color:var(--text-secondary);font-size:13px;background:var(--bg-surface);
  transition:color .15s ease-out,border-color .15s ease-out,background .15s ease-out;
}
.more-btn:hover{color:var(--text-primary);background:var(--bg-elevated);
  border-color:color-mix(in srgb,var(--nc) 55%,var(--border))}
/* 紧凑密度：同一屏多看到约三分之一条目——标题压到 2 行、摘要压到 2 行、标签行隐藏、
   卡片内边距与行距收紧（可读性设置，桌面两档，选择持久化）。 */
.grid.dense{gap:10px}
.grid.dense .card{padding:12px 14px 11px;gap:6px}
.grid.dense .card-title{
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.grid.dense .card-summary{
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.grid.dense .card-chips{display:none}
.grid.dense .card-meta{gap:4px;padding-top:2px}
.grid.dense .card-meta-row{gap:6px}

/* ============ 卡片（顶边节点色 accent） ============ */
.card{
  display:flex;flex-direction:column;gap:9px;padding:16px 17px 15px;border-radius:14px;
  background:var(--bg-surface);border:1px solid var(--border);
  border-top:2px solid color-mix(in srgb,var(--nc) 38%,var(--border));
  box-shadow:var(--shadow-card);
  cursor:pointer;transition:transform .18s ease-out,border-color .18s ease-out,
    box-shadow .18s ease-out;
  animation:rise .3s ease-out both;animation-delay:calc(min(var(--i,0),12) * 28ms);
}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.card:hover{transform:translateY(-2px);
  border-color:color-mix(in srgb,var(--nc) 55%,var(--border));
  border-top-color:var(--nc)}
.card.kb-focus{border-color:var(--nc);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--nc) 20%,transparent)}
.card[data-importance="头条"]{
  border-top-color:var(--hot);
  box-shadow:0 0 0 1px color-mix(in srgb,var(--hot) 30%,transparent),var(--shadow-card);
}
.card-top{display:flex;align-items:center;gap:8px}
.card-num{
  font-size:12px;font-weight:700;font-variant-numeric:tabular-nums;
  color:var(--text-muted);letter-spacing:.04em;
}
.badge-hot{
  font-size:10.5px;font-weight:800;padding:1.5px 9px;border-radius:999px;
  color:var(--hot-solid-fg);background:var(--hot-solid);letter-spacing:.06em;
  box-shadow:0 1px 6px color-mix(in srgb,var(--hot-solid) 45%,transparent);
}
/* 重要：金色实底徽标（次于头条的第二级强调） */
.badge-imp{
  font-size:10.5px;font-weight:800;padding:1.5px 9px;border-radius:999px;
  color:var(--imp-fg);background:var(--imp-bg);
  border:1px solid var(--imp-border);letter-spacing:.06em;
  box-shadow:0 1px 6px color-mix(in srgb,var(--imp-bg) 45%,transparent);
}
.card-region{
  display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:600;
  padding:1.5px 8px;border-radius:999px;
  color:var(--success);border:1px solid color-mix(in srgb,var(--success) 45%,transparent);
  background:color-mix(in srgb,var(--success) 10%,transparent);
}
/* ============ 热点 ↔ 面板 ============ */
/* 热点条目行尾的「环节 · 序号」定位按钮：一条热点落在哪个环节、第几条，一眼可见 */
.hot-row{display:flex;align-items:center;gap:4px;padding-right:14px}
.hot-row .hot-head{width:auto;flex:1;min-width:0}
.hot-jump{
  flex:none;display:inline-flex;align-items:center;gap:6px;padding:4px 10px;
  border-radius:8px;font-size:11.5px;font-weight:700;cursor:pointer;
  color:var(--nc);border:1px solid color-mix(in srgb,var(--nc) 42%,var(--border));
  background:color-mix(in srgb,var(--nc) 10%,transparent);
  font-variant-numeric:tabular-nums;
}
.hot-jump i{width:7px;height:7px;border-radius:50%;background:var(--nc);flex:none}
.hot-jump b{font-weight:800;margin-left:1px}
.hot-jump:hover{background:color-mix(in srgb,var(--nc) 22%,transparent)}
.hot-jump:focus-visible{outline:2px solid var(--nc);outline-offset:2px}
.hot-nopanel{
  flex:none;padding:4px 10px;border-radius:8px;font-size:11px;font-weight:600;
  color:var(--text-muted);border:1px dashed var(--border);
}
/* 卡片顶部：交叉热点标记 + 所属环节（环节置右） */
.card-top{flex-wrap:wrap;row-gap:6px}
.card-hot{
  flex:none;padding:1.5px 9px;border-radius:999px;border:none;cursor:pointer;
  font-size:10.5px;font-weight:800;letter-spacing:.04em;white-space:nowrap;
  color:var(--hot-solid-fg);background:var(--hot-solid);
}
.card-hot:hover{filter:brightness(1.08)}
.card-hot:focus-visible{outline:2px solid var(--hot);outline-offset:2px}
.card-node{
  flex:none;display:inline-flex;align-items:center;gap:5px;margin-left:auto;
  font-size:11px;font-weight:700;color:var(--nc);white-space:nowrap;
}
.card-node i{width:6px;height:6px;border-radius:50%;background:var(--nc);flex:none}
/* 定位高亮：滚动到位后闪两下（reduced-motion 降级为静态描边） */
.is-target{animation:targetFlash 1.1s ease-out 2}
@keyframes targetFlash{
  0%,100%{box-shadow:0 0 0 0 transparent}
  40%{box-shadow:0 0 0 3px color-mix(in srgb,var(--hot) 50%,transparent)}
}
@media (prefers-reduced-motion: reduce){
  .is-target{animation:none;outline:2px solid var(--hot);outline-offset:2px}
}

/* 正文级字号统一乘 --fs（可读性设置）。原先只有 body 用 calc、卡片与抽屉写死 px，
   结果「字号」开关几乎看不出效果——这里把承载阅读量的几处全部纳入同一比例尺。 */
.card-title{font-size:calc(15px * var(--fs, 1));font-weight:650;line-height:1.5;letter-spacing:.01em}
.card-title mark{background:var(--mark-bg);color:var(--mark-text);border-radius:3px;padding:0 1px}
.card-summary{
  font-size:calc(13px * var(--fs, 1));color:var(--text-secondary);line-height:1.6;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
}
.card-chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:11px;padding:2px 9px;border-radius:999px;white-space:nowrap}
.chip-b{color:var(--text-secondary);border:1px solid var(--border);background:var(--bg-elevated)}
/* 卡片底部两行结构：第一行 来源+时间；第二行 原文/镜像（右对齐+细分隔线），
   保证每张卡片底部结构一致、横向对齐 */
.card-meta{display:flex;flex-direction:column;gap:6px;margin-top:auto;padding-top:4px}
.card-meta-row{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
/* 第二行：发布时间在左、原文/镜像链接在右，左右形成对应 */
.card-links{display:flex;justify-content:space-between;align-items:center;gap:10px;
  padding-top:7px;border-top:1px solid var(--border)}
.cl-links{display:inline-flex;align-items:center;gap:12px;flex:none}
.chip-src{
  display:inline-flex;align-items:center;gap:6px;color:var(--text-secondary);
  border:1px solid var(--border);background:var(--bg-elevated);
  padding:3px 10px;max-width:100%;
}
.chip-src .flag{flex:none}
.chip-src .tier{
  font-style:normal;font-size:10px;font-weight:700;color:var(--nc);
  opacity:.9;
}
.card-time{font-size:11.5px;color:var(--text-muted);font-variant-numeric:tabular-nums;
  display:inline-flex;align-items:center;gap:4px}
.card-time i{font-style:normal;font-size:10px;opacity:.75}
.card-link{
  display:inline-flex;align-items:center;gap:4px;font-size:12px;
  font-weight:600;color:var(--nc);text-decoration:none;
  transition:all .15s ease-out;
}
.card-link:hover{text-decoration:underline;text-underline-offset:3px}
.card-link svg{transition:transform .15s ease-out}
.card-link:hover svg{transform:translate(1px,-1px)}
.card-mirror{font-size:11px;color:var(--text-muted);text-decoration:none;
  padding:2px 8px;border-radius:999px;border:1px solid var(--border);
  transition:all .15s ease-out;white-space:nowrap}
.card-mirror:hover{color:var(--text-secondary);
  border-color:color-mix(in srgb,var(--nc) 45%,var(--border))}

/* ============ L2 详情抽屉 ============ */
.overlay{
  position:fixed;inset:0;z-index:50;background:rgba(2,6,17,.55);
  opacity:0;pointer-events:none;transition:opacity .2s ease-out;
}
html[data-theme="light"] .overlay,html[data-theme="auto"] .overlay{
  background:rgba(60,50,35,.32);
}
.overlay.open{opacity:1;pointer-events:auto}
.drawer{
  position:fixed;top:0;right:0;bottom:0;z-index:51;width:min(560px,100vw);
  background:var(--bg-surface);border-left:1px solid var(--border);
  box-shadow:var(--shadow-pop);display:flex;flex-direction:column;
  transform:translateX(102%);transition:transform .25s ease-out;
}
.drawer[hidden]{display:none}
.drawer.open{transform:none}
/* 抽屉顶栏重排：左（环节 › 子类）· 中（语言三态）· 右（上一条/下一条/复制/关闭）。
   左侧面包屑**最多两行紧凑显示**（`-webkit-line-clamp:2` + 收紧行高），并 `flex:1;min-width:0`；
   语言三态与动作键组 `flex:none` + `white-space:nowrap`——旧版左侧标题一长就把三态挤到换行，
   「原文」两字被压成竖排（每行一字），完全读不出来。窄屏改为两行布局：三态独占第二行左端。 */
.drawer-head{
  display:flex;align-items:center;gap:10px;padding:14px 20px;
  border-bottom:1px solid var(--border);flex:none;
}
.drawer-crumb{
  flex:1;min-width:0;font-size:12px;color:var(--text-muted);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  line-height:1.45;
}
.drawer-crumb b{color:var(--nc,var(--accent-capability));font-weight:650;
  display:inline;white-space:nowrap}
.drawer-crumb i{font-style:normal;font-size:9.5px;font-weight:600;letter-spacing:.12em;
  text-transform:uppercase;opacity:.85;white-space:nowrap}
.drawer-actions{margin-left:auto;display:flex;gap:6px;flex:none}
.icon-btn{
  display:flex;align-items:center;justify-content:center;width:32px;height:32px;
  border-radius:9px;border:1px solid var(--border);color:var(--text-secondary);
  transition:all .15s ease-out;
}
.icon-btn:hover{color:var(--text-primary);border-color:var(--accent-capability)}
.icon-btn:disabled{opacity:.35;cursor:not-allowed}
.drawer-body{flex:1;overflow-y:auto;padding:22px 24px 30px;overscroll-behavior:contain}
/* 详情页的译文交互：标题行 + 显式「译」按钮 + 语言三态（就地切换，不必回顶栏） */
.drawer-lang{flex:none;margin-right:2px;white-space:nowrap}
.drawer-lang button{padding:4px 8px;font-size:11px;white-space:nowrap}
.drawer-trow{display:flex;align-items:flex-start;gap:10px;margin:12px 0 10px}
.drawer-trow .drawer-title{flex:1;min-width:0;margin:0}
/* 「译」按钮：要比默认态醒目，但**不跳色**——用中性高级灰（灰底 + 灰描边 + 亮字），
   亮起时反转为「实心浅灰 + 深字」。环节彩色留给语义，不在这里抢。 */
.dr-bi{
  flex:none;display:inline-flex;align-items:center;gap:5px;margin-top:3px;
  padding:5px 12px;border-radius:8px;font-size:11px;font-weight:700;letter-spacing:.02em;
  color:var(--neutral-ink);
  border:1px solid color-mix(in srgb,var(--neutral-ink) 46%,transparent);
  background:color-mix(in srgb,var(--neutral-ink) 11%,var(--bg-surface));
  box-shadow:0 1px 2px rgba(0,0,0,.14);
  transition:color .15s ease-out,background .15s ease-out,border-color .15s ease-out;
}
.dr-bi:hover{color:var(--text-primary);
  border-color:color-mix(in srgb,var(--neutral-ink) 70%,transparent);
  background:color-mix(in srgb,var(--neutral-ink) 20%,var(--bg-surface))}
.dr-bi[aria-pressed="true"]{
  color:var(--bg-base);
  border-color:color-mix(in srgb,var(--neutral-ink) 84%,transparent);
  background:color-mix(in srgb,var(--neutral-ink) 88%,var(--bg-surface));
}
/* 目标语模式：原文退为附注块，与译文上下分栏 */
.drawer-orig{
  margin:10px 0 0;padding:8px 0 8px 13px;
  font-size:calc(12.5px * var(--fs, 1));line-height:1.75;color:var(--text-muted);
  border-left:2px solid var(--border);
}
.drawer-orig b{display:block;font-weight:650;color:var(--text-secondary);margin-bottom:3px}
.drawer-title{font-size:calc(19px * var(--fs, 1));font-weight:700;line-height:1.5;margin:12px 0 10px}
.drawer-summary{font-size:calc(14px * var(--fs, 1));color:var(--text-secondary);line-height:1.8}
/* 抽屉译文（对照 / 目标语模式）：按「块」与原文一一对应，不把标题与摘要拼成一段，
   读者才能对上号；左侧竖线标示「这是译文」。 */
.drawer-alt{
  margin:10px 0 0;padding:9px 0 9px 13px;font-size:calc(13.5px * var(--fs, 1));line-height:1.8;
  color:var(--text-secondary);border-left:2px solid color-mix(in srgb,var(--text-muted) 55%,transparent);
}
.drawer-alt:empty{display:none}
.drawer-alt .da-tag{
  display:block;margin-bottom:5px;font-size:9.5px;font-weight:700;letter-spacing:.1em;
  color:var(--text-muted);
}
.drawer-alt b{display:block;font-weight:700;color:var(--text-primary)}
.drawer-alt b + .da-sum{margin-top:8px}
.drawer-alt .da-sum{font-weight:400}
.drawer-note{font-size:11.5px;color:var(--text-muted);margin-top:8px;line-height:1.6}
.drawer-meta{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
/* 抽屉里的「交叉热点」说明盒：默认只占一行——
   「交叉热点 · N 信源」+「回到上方热点条目」，说明正文收起；
   点这一行（除右侧跳转按钮外）才展开说明，避免说明盒抢占视觉重心。 */
.drawer-hotbox{
  margin:12px 0 0;padding:8px 12px;border-radius:11px;
  background:color-mix(in srgb,var(--hot) 8%,transparent);
  border:1px solid color-mix(in srgb,var(--hot) 26%,var(--border));
}
.dhb-top{display:flex;align-items:center;gap:10px}
.dhb-toggle{
  flex:1;min-width:0;display:inline-flex;align-items:center;gap:8px;
  padding:0;background:none;border:none;cursor:pointer;text-align:left;
  color:inherit;font:inherit;font-size:11.5px;font-weight:700;
}
.dhb-toggle:focus-visible{outline:2px solid var(--hot);outline-offset:2px;border-radius:6px}
.dhb-badge{
  flex:none;font-size:11.5px;font-weight:800;padding:2px 10px;border-radius:999px;
  color:var(--hot-solid-fg);background:var(--hot-solid);
}
.dhb-caret{flex:none;color:var(--hot);transition:transform .18s ease-out}
.dhb-toggle[aria-expanded="true"] .dhb-caret{transform:rotate(180deg)}
.dhb-jump{
  flex:none;padding:4px 10px;border-radius:8px;font-size:11.5px;
  font-weight:700;cursor:pointer;color:var(--hot);background:transparent;
  border:1px solid color-mix(in srgb,var(--hot) 40%,var(--border));
  white-space:nowrap;
}
.dhb-jump:hover{background:color-mix(in srgb,var(--hot) 14%,transparent)}
.dhb-note{
  margin:9px 0 0;padding-top:9px;font-size:12.5px;line-height:1.65;
  color:var(--text-secondary);
  border-top:1px dashed color-mix(in srgb,var(--hot) 26%,var(--border));
}
.dhb-note[hidden]{display:none}

.drawer-section{margin-top:20px}
.drawer-section h4{font-size:12px;color:var(--text-muted);font-weight:600;
  letter-spacing:.08em;margin-bottom:9px;display:flex;align-items:baseline;gap:7px}
.drawer-section h4 i{font-style:normal;font-size:9px;letter-spacing:.12em;
  text-transform:uppercase;opacity:.8}
.kv{display:flex;gap:12px;font-size:13px;padding:6px 0;
  border-bottom:1px dashed var(--border)}
.kv:last-child{border-bottom:none}
/* 字段名列：宽度容得下最长字段名（来源国家/地区），右对齐以区别于左对齐的区块标题 */
.kv span{flex:none;width:96px;text-align:right;color:var(--text-muted);
  font-size:12.5px;line-height:1.5}
.kv b{flex:1;min-width:0;font-weight:500;color:var(--text-primary)}
.verified{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600}
.verified.ok{color:var(--success)}
.verified.no{color:var(--hot)}
.rel-list{list-style:none}
.rel-list li{display:flex;align-items:center;gap:9px;padding:7px 0;font-size:13px;
  border-bottom:1px dashed var(--border)}
.rel-list li:last-child{border-bottom:none}
.rel-list a{color:var(--accent-capability);text-decoration:none;font-weight:500}
.rel-list a:hover{text-decoration:underline}
.rel-list .rel-auth{color:var(--text-muted);font-size:11.5px;margin-left:auto;white-space:nowrap}
/* 同一信源的其余收录（附域名，弱化）：与独立信源行区分，链接不丢 */
.rel-list .rel-more{font-size:11.5px;color:var(--text-muted);font-weight:400;
  border-bottom:1px dotted color-mix(in srgb,var(--text-muted) 55%,transparent)}
.rel-list .rel-more:hover{text-decoration:none;border-bottom-style:solid}
.drawer-links{display:flex;gap:10px;margin-top:22px;flex-wrap:wrap}
.btn{
  display:inline-flex;align-items:center;gap:7px;padding:9px 18px;border-radius:10px;
  font-size:13px;font-weight:600;text-decoration:none;transition:all .15s ease-out;
}
.btn-primary{color:#04121A;background:var(--accent-capability)}
html[data-theme="light"] .btn-primary,html[data-theme="auto"] .btn-primary{color:#fff}
.btn-primary:hover{filter:brightness(1.1)}
.btn-ghost{border:1px solid var(--border);color:var(--text-secondary)}
.btn-ghost:hover{color:var(--text-primary);border-color:var(--accent-capability)}

/* ============ 页脚 / Toast ============ */
/* 脚注三列版式：① 中文标签 ② 英文标签 ③ 内容。
   列宽固定，四行严格对齐、三列一律左对齐。基准：中文列 = 4 个汉字（12px × 4 = 48px，留 2px 余量 → 50px）；
   英文列 = 10 个英文大写字符（实测 9px + .1em 字距下 10 字符 ≈ 66–68px，取 68px）。
   **三列按基线对齐**（align-items:baseline）：英文标签字号小、行盒矮，若按顶对齐会整体高出中文标签一截。
   窄屏不堆叠（保持同一套三列版式），只收窄列间距，故移动端与桌面结构一致。 */
.footer{
  --fw-zh:50px;--fw-en:68px;--fw-gap:8px;
  border-top:1px solid var(--border);padding:26px 0 40px;
  display:flex;flex-direction:column;gap:9px;
}
.foot-row{
  display:grid;grid-template-columns:var(--fw-zh) var(--fw-en) 1fr;
  column-gap:var(--fw-gap);align-items:baseline;
  font-size:12px;line-height:1.7;
}
.foot-label{color:var(--text-muted);white-space:nowrap;text-align:left}
.foot-en{
  font-style:normal;font-size:9px;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;opacity:.8;color:var(--text-muted);
  white-space:nowrap;text-align:left;
}
.foot-val{color:var(--text-secondary);min-width:0;text-align:left}
.toast{
  position:fixed;left:50%;bottom:34px;transform:translate(-50%,16px);z-index:60;
  padding:9px 20px;border-radius:999px;font-size:13px;font-weight:500;
  background:var(--bg-elevated);border:1px solid var(--border);color:var(--text-primary);
  box-shadow:var(--shadow-pop);opacity:0;pointer-events:none;
  transition:opacity .2s ease-out,transform .2s ease-out;
}
.toast.show{opacity:1;transform:translate(-50%,0)}
.no-result{display:none;padding:40px 0;text-align:center;color:var(--text-muted);font-size:14px}
.day.searching .no-result{display:block}

/* ============ 阅读控制：悬浮导航舱（桌面）/ 底部操作条（移动） ============
   一个控件承担三件事：**我在哪**（进度环 + 当前环节高亮）、**我能去哪**（回顶 / 回底 /
   环节跳转）、**快捷动作**（命令面板）。滚动停止 1.2s 后降到 40% 不透明度——控件
   不该比内容抢眼。移动端：改为底部横条 + 顶部 2px 进度条，触达目标 ≥44px（iOS HIG），
   向下滚动自动收起、向上滚动出现。 */
.navpod{
  position:fixed;right:22px;bottom:22px;z-index:45;
  display:flex;flex-direction:column;align-items:flex-end;gap:10px;
  transition:opacity .25s ease-out,transform .28s cubic-bezier(.16,.84,.44,1);
}
.navpod.idle{opacity:.4}
.navpod:hover,.navpod:focus-within{opacity:1}
.navpod.tuck{transform:translateY(140%)}
.np-bar{display:flex;flex-direction:column;align-items:center;gap:8px}
.np-ring,.np-btn{
  position:relative;display:grid;place-items:center;flex:none;
  width:44px;height:44px;border-radius:50%;
  background:color-mix(in srgb,var(--bg-surface) 94%,transparent);
  border:1px solid var(--border);color:var(--text-secondary);
  backdrop-filter:blur(10px);box-shadow:0 6px 20px rgba(0,0,0,.16);
  transition:color .16s ease-out,border-color .16s ease-out,transform .16s ease-out;
}
.np-ring:hover,.np-btn:hover{color:var(--accent-capability);
  border-color:color-mix(in srgb,var(--accent-capability) 58%,var(--border));
  transform:translateY(-1px)}
.np-btn.is-on{color:var(--accent-capability);
  border-color:color-mix(in srgb,var(--accent-capability) 58%,var(--border));
  background:color-mix(in srgb,var(--accent-capability) 12%,var(--bg-surface))}
/* 进度环：r=19 → 周长 119.38；由脚本按滚动比例写 stroke-dashoffset */
.np-ring-svg{position:absolute;inset:0;width:44px;height:44px;transform:rotate(-90deg)}
.np-ring-track{fill:none;stroke:var(--border);stroke-width:2.4}
.np-ring-bar{fill:none;stroke:var(--accent-capability);stroke-width:2.4;
  stroke-linecap:round;stroke-dasharray:119.38;stroke-dashoffset:119.38;
  transition:stroke-dashoffset .1s linear}
.np-ring-ico{position:relative;display:grid;place-items:center}
/* 环节面板：与 的日期 / 阅读设置面板同一套壳（绝对定位，默认吊在舱上方，
   打开时由脚本 anchorPanel() 改为贴按钮定位并收紧高度，保证顶部一行也在视口内）。 */
.np-list{
  position:absolute;right:0;bottom:calc(100% + 10px);
  width:238px;max-height:min(64vh,470px);overflow-y:auto;overscroll-behavior:contain;
  padding:8px;border-radius:14px;
  background:var(--bg-surface);
  border:1px solid var(--border);box-shadow:var(--shadow-pop);
  backdrop-filter:blur(14px);
}
.np-list[hidden]{display:none}
.np-item{
  display:flex;align-items:center;gap:9px;width:100%;
  padding:8px 10px;border-radius:9px;text-align:left;font-size:13px;
  color:var(--text-secondary);transition:background .14s ease-out,color .14s ease-out;
}
.np-item:hover{background:var(--bg-elevated);color:var(--text-primary)}
.np-item i{width:8px;height:8px;border-radius:50%;background:var(--nc);flex:none}
.np-item b{margin-left:auto;font-size:12px;font-variant-numeric:tabular-nums;
  color:var(--text-muted)}
.np-item[aria-current="true"]{background:color-mix(in srgb,var(--nc) 12%,transparent);
  color:var(--text-primary);font-weight:600}
/* 面板统一壳（环节 / 日期 / 阅读设置共用，只换内容）：
   三个面板都绝对定位在导航舱上方，互斥打开——一次只让读者看一件事。 */
.np-panel{
  position:absolute;right:0;bottom:calc(100% + 10px);
  width:238px;max-height:min(64vh,470px);overflow-y:auto;overscroll-behavior:contain;
  padding:8px;border-radius:14px;
  /* 面板底色必须**不透明**：半透明时下方卡片会透上来与日期、条数叠字，乱到读不了。
     backdrop-filter 只作边缘过渡的增强，不承担可读性。 */
  background:var(--bg-surface);
  border:1px solid var(--border);box-shadow:var(--shadow-pop);backdrop-filter:blur(14px);
}
.np-panel[hidden]{display:none}
.np-cap{
  display:flex;align-items:baseline;gap:8px;margin-bottom:6px;padding:3px 8px 7px;
  border-bottom:1px solid var(--border);
  font-size:10.5px;font-weight:700;letter-spacing:.14em;color:var(--text-muted);
}
.np-cap em{font-style:normal;font-size:10px;font-weight:600;letter-spacing:.08em;opacity:.85}
/* 日期行：左「月.日 + 星期」· 右「24H/48H 条数」 */
.np-date{
  display:flex;align-items:center;gap:9px;width:100%;
  padding:8px 10px;border-radius:9px;text-align:left;font-size:13px;
  color:var(--text-secondary);font-variant-numeric:tabular-nums;
  transition:background .14s ease-out,color .14s ease-out;
}
.np-date:hover{background:var(--bg-elevated);color:var(--text-primary)}
.np-date i{width:7px;height:7px;border-radius:50%;background:var(--border);flex:none}
.np-date small{font-size:11px;color:var(--text-muted);margin-left:-3px}
.np-date b{margin-left:auto;font-size:12px;font-weight:600;color:var(--text-muted)}
.np-date.is-latest b{color:var(--accent-capability)}
.np-date[aria-current="true"]{background:var(--bg-elevated);color:var(--text-primary);font-weight:650}
.np-date[aria-current="true"] i{background:var(--accent-capability)}
/* 指定日期输入行：格式提示 + 实时校验反馈 */
.np-jump{margin-top:6px;padding:9px 8px 3px;border-top:1px solid var(--border)}
.np-jump label{display:block;margin-bottom:6px;font-size:10.5px;font-weight:700;
  letter-spacing:.12em;color:var(--text-muted)}
.np-jump input{
  width:100%;padding:8px 9px;border-radius:8px;font:inherit;font-size:13px;
  border:1px solid var(--border);background:var(--bg-base);color:var(--text-primary);
  outline:none;font-variant-numeric:tabular-nums;letter-spacing:.02em;
}
.np-jump input:focus{border-color:var(--accent-capability);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--accent-capability) 15%,transparent)}
.np-jump input::placeholder{color:var(--text-muted);letter-spacing:0}
.np-hint{margin-top:6px;font-size:10.5px;line-height:1.5;color:var(--text-muted)}
.np-hint.is-bad{color:var(--hot)}
.np-hint.is-ok{color:var(--accent-capability)}
/* 阅读设置面板：字号三档 + 密度两档 */
.np-grp{padding:3px 2px 7px}
.np-grp-t{padding:6px 8px 5px;font-size:10.5px;font-weight:700;letter-spacing:.12em;
  color:var(--text-muted)}
.np-seg{display:flex;gap:4px;padding:0 4px}
.np-seg button{
  flex:1;padding:8px 3px;border-radius:8px;font-size:12.5px;font-weight:600;
  color:var(--text-secondary);border:1px solid var(--border);background:var(--bg-base);
  transition:color .15s ease-out,border-color .15s ease-out,background .15s ease-out;
}
.np-seg button:hover{color:var(--text-primary);
  border-color:color-mix(in srgb,var(--accent-capability) 50%,var(--border))}
.np-seg button[aria-pressed="true"]{color:var(--accent-capability);font-weight:700;
  border-color:color-mix(in srgb,var(--accent-capability) 58%,var(--border));
  background:color-mix(in srgb,var(--accent-capability) 12%,var(--bg-base))}
/* 移动端顶部细进度条 */
.mprog{position:fixed;left:0;top:0;height:2px;width:100%;z-index:50;display:none}
.mprog i{display:block;height:100%;width:0;border-radius:0 2px 2px 0;
  background:linear-gradient(90deg,var(--accent-capability),var(--accent-product));
  transition:width .1s linear}

/* ============ 双语对照层 ============
   标题 = 信源原标题（规范 R-02 硬约束），故译文只能作为**附加层**，且标注机器翻译。
   三种触发：① 桌面悬停浮层（position:fixed，不占文档流 → 绝不会引起上下跳动）
   ② 触屏无 hover → 卡片上的「译」图标点开就地对照 ③ 顶栏三态全局开关。 */
/* 三行定式：① 提示徽标（机器译文 · 未校对）② 标题译文 ③ 摘要译文（≤60 汉字）。
   配色一律**中性灰阶**——五环节的彩色是本站的语义色，浮层若带环节色会与之打架，
   读者会误以为浮层颜色代表某个环节。宽度取 330px：摘要译文 ≤60 汉字在 13px 下约
   3 行（每行 18 字），330px 内标题最多 2 行、摘要最多 3 行，正好收在三行定式里；
   原 400px 在中文长标题下会拉成一条横幅，显得笨重。 */
.bi-pop{
  position:fixed;z-index:80;width:min(330px,calc(100vw - 24px));
  padding:11px 13px 12px;border-radius:12px;
  font-size:calc(13px * var(--fs, 1));line-height:1.62;
  background:color-mix(in srgb,var(--bg-surface) 98%,var(--text-muted) 2%);
  border:1px solid color-mix(in srgb,var(--text-muted) 30%,var(--border));
  box-shadow:0 10px 30px rgba(0,0,0,.22),0 2px 6px rgba(0,0,0,.10);
  backdrop-filter:blur(14px);color:var(--text-secondary);pointer-events:none;
  animation:bi-in .14s ease-out;
}
.bi-pop[hidden]{display:none}
@keyframes bi-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
/* 行① 提示徽标：灰阶药丸，与五环节色无关 */
.bi-pop .bi-tag{
  display:block;margin-bottom:7px;padding:0;border-radius:0;
  font-size:9.5px;font-weight:700;letter-spacing:.1em;
  color:var(--text-muted);
}
/* 行② 标题译文：主文本色，最多 2 行 */
.bi-pop .bi-title{
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  font-size:calc(13.5px * var(--fs, 1));font-weight:650;line-height:1.5;
  color:var(--text-primary);
}
/* 行③ 摘要译文：次级色，最多 3 行 */
.bi-pop .bi-sum{
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
  margin-top:5px;font-size:calc(12.5px * var(--fs, 1));line-height:1.62;
  color:var(--text-secondary);
}
.bi-pop .bi-sum:empty,.bi-pop .bi-title:empty{display:none}
/* 术语浮层（界面文案）单行即可 */
.bi-pop .bi-term{display:block;font-weight:600;color:var(--text-primary)}
/* 触屏「译」图标（无 hover 环境才出现） */
.card-bi{
  flex:none;display:none;align-items:center;gap:3px;padding:2px 8px;
  border-radius:999px;font-size:10.5px;font-weight:700;color:var(--accent-capability);
  border:1px solid color-mix(in srgb,var(--accent-capability) 45%,var(--border));
  background:color-mix(in srgb,var(--accent-capability) 10%,transparent);
}
html.touch .card-bi[data-has-alt="1"]{display:inline-flex}
/* 全局三态：原文（默认）/ 对照（原文下附译文一行）/ 目标语（译文为主、原文降权）。
   DOM 顺序由脚本按模式给出（目标语模式把译文明文放在前面），此处只管样式。 */
.card-alt{margin:1px 0 0;font-size:calc(12.5px * var(--fs, 1));line-height:1.6;color:var(--text-muted)}
.card-alt::before{content:"译";display:inline-block;margin-right:6px;padding:0 5px;
  border-radius:4px;font-size:9.5px;font-weight:800;vertical-align:1px;
  color:var(--text-muted);background:var(--bg-elevated);border:1px solid var(--border)}
.card-title .ct-alt,.card-summary .cs-alt{color:var(--text-muted)}
html[data-langmode="both"] .ct-alt,html[data-langmode="both"] .cs-alt{
  display:block;margin-top:3px}
html[data-langmode="tgt"] .ct-alt,html[data-langmode="tgt"] .cs-alt{
  color:var(--text-primary)}
html[data-langmode="tgt"] .ct-zh,html[data-langmode="tgt"] .cs-zh{
  display:block;margin-top:2px;font-size:12px;font-weight:400;color:var(--text-muted)}
/* 语言模式切换（顶栏）：三态分段控件。与色系控件同一条规则——
   宽度固定（flex:none）+ 文字不换行，搜索框变长时不被压缩。 */
.lang-switch{display:inline-flex;align-items:center;gap:2px;padding:2px;flex:none;
  border-radius:9px;background:var(--bg-elevated);border:1px solid var(--border)}
.lang-switch button{padding:5px 9px;border-radius:7px;font-size:11.5px;font-weight:600;
  white-space:nowrap;color:var(--text-muted);transition:all .15s ease-out}
.lang-switch button[aria-pressed="true"]{background:var(--bg-surface);
  color:var(--accent-capability)}

/* ============ 命令面板（⌘K / Ctrl+K） ============
   一个输入框容纳「跳日期 / 跳环节 / 搜标题 / 切窗口 / 切主题 / 回热点 / 复制清单」，
   替代层层菜单——现有切日、筛选、搜索逻辑可直接复用。 */
.cmdk{position:fixed;inset:0;z-index:90;display:grid;place-items:start center;
  padding:12vh 16px 16px;background:color-mix(in srgb,var(--bg-base) 62%,transparent);
  backdrop-filter:blur(4px)}
.cmdk[hidden]{display:none}
.cmdk-panel{
  width:min(560px,100%);border-radius:16px;overflow:hidden;
  background:var(--bg-surface);border:1px solid var(--border);
  box-shadow:var(--shadow-pop);animation:cmd-in .16s cubic-bezier(.16,.84,.44,1);
}
@keyframes cmd-in{from{opacity:0;transform:translateY(-8px) scale(.99)}
  to{opacity:1;transform:none}}
.cmdk-input{display:flex;align-items:center;gap:9px;padding:12px 14px;
  border-bottom:1px solid var(--border)}
.cmdk-input svg{color:var(--text-muted);flex:none}
.cmdk-input input{flex:1;min-width:0;border:none;outline:none;background:none;
  font:inherit;font-size:15px;color:var(--text-primary)}
.cmdk-input kbd{flex:none;font-family:inherit;font-size:10.5px;color:var(--text-muted);
  padding:2px 6px;border-radius:5px;border:1px solid var(--border);
  background:var(--bg-elevated)}
.cmdk-list{max-height:min(52vh,420px);overflow:auto;padding:6px}
.cmdk-empty{padding:18px;text-align:center;font-size:13px;color:var(--text-muted)}
.cmdk-group{padding:7px 9px 3px;font-size:10.5px;font-weight:700;letter-spacing:.12em;
  color:var(--text-muted);text-transform:uppercase}
.cmdk-item{display:flex;align-items:center;gap:10px;width:100%;padding:9px 10px;
  border-radius:9px;text-align:left;font-size:13.5px;color:var(--text-secondary)}
.cmdk-item i{width:7px;height:7px;border-radius:50%;background:var(--nc,var(--border));
  flex:none}
.cmdk-item em{margin-left:auto;font-style:normal;font-size:11.5px;color:var(--text-muted)}
.cmdk-item.is-cursor{background:var(--bg-elevated);color:var(--text-primary)}
.cmdk-item.is-cursor em{color:var(--accent-capability)}

/* ============ 骨架屏（运行态取数等高占位，避免内容跳变） ============ */
.skel{padding:0}
.skel-h{height:26px;width:38%;border-radius:8px;margin:6px 0 18px}
.skel-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:14px;margin-bottom:14px}
.skel-card{height:116px;border-radius:14px;border:1px solid var(--border);
  background:var(--bg-surface)}
.skel-h,.skel-card{
  background:linear-gradient(100deg,var(--bg-surface) 30%,var(--bg-elevated) 50%,
    var(--bg-surface) 70%);
  background-size:220% 100%;animation:skel 1.15s ease-in-out infinite;
}
@keyframes skel{to{background-position:-120% 0}}
@media (prefers-reduced-motion:reduce){.skel-h,.skel-card{animation:none}}

/* ============ 继续上次阅读（重访提示） ============ */
.resume{
  position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(12px);
  z-index:46;display:flex;align-items:center;gap:10px;padding:9px 14px;
  border-radius:999px;background:color-mix(in srgb,var(--bg-surface) 96%,transparent);
  border:1px solid var(--border);box-shadow:var(--shadow-pop);
  backdrop-filter:blur(12px);font-size:12.5px;color:var(--text-secondary);
  opacity:0;pointer-events:none;transition:opacity .2s ease-out,transform .2s ease-out;
}
.resume.show{opacity:1;transform:translateX(-50%) translateY(0);pointer-events:auto}
.resume button{font-size:12.5px;font-weight:700;color:var(--accent-capability)}
.resume .resume-x{color:var(--text-muted);font-size:15px;line-height:1;padding:0 2px}

/* ============ 打印：今日清单可直接出纸面版 ============ */
@media print{
  .topbar,.navpod,.cmdk,.mprog,.resume,.filters,.searchbox,.lang-switch,
  .theme-switch,.datepicker,.more-bar,.drawer,.overlay,.toast,.src-notice,
  .axis-mini,.hotbar{display:none!important}
  html{scroll-behavior:auto}
  body{font-size:11pt;background:#fff;color:#000}
  .wrap{max-width:none;padding:0}
  .node{break-inside:avoid;margin-top:12px;border:1px solid #ccc;border-radius:6px}
  .node-head{position:static}
  .grid{grid-template-columns:1fr 1fr;gap:8px}
  /* 打印输出全部条目：渐进加载的收起状态不参与纸面输出 */
  .card{break-inside:avoid;box-shadow:none;animation:none;border:1px solid #ddd}
  .card[hidden]{display:flex!important}
  .card-link::after{content:" → " attr(href);font-size:8pt;color:#777;word-break:break-all}
  .footer{border-top:1px solid #999;margin-top:16px}
}

/* ============ 响应式：三档 ============ */
@media (max-width:1279px){
  .wrap{padding:0 20px}
  .searchbox input{width:200px}
  .searchbox input:focus{width:240px}
  .hero-dist{width:300px}
  .node-desc{max-width:300px}
}
@media (max-width:767px){
  /* 顶栏多行：① 品牌 + 日期 ② 语言 + 搜索 + 主题（不删任何内容，只改排序与留白）。
     --topbar-h 由脚本按实测高度写入（顶栏会换行，写死会算错吸顶位置）；
     向下阅读时顶栏整体收起（.tuck），所以顶部多占几行不与内容抢空间。 */
  .topbar{flex-wrap:wrap;gap:6px 8px;padding:6px 12px}
  .topbar .spacer{display:none}
  .brand svg{width:18px;height:18px}
  .date-btn{padding:4px 8px;gap:7px}
  .searchbox{order:3;flex:1;min-width:0}
  .searchbox input,.searchbox input:focus{width:100%;padding:8px 11px 8px 30px}
  .lang-switch{order:4}
  .lang-switch button{padding:5px 8px;min-height:34px}
  .theme-switch{order:5}
  .theme-switch button{padding:6px 9px;min-height:34px}
  /* 触达目标：HIG 建议 ≥44px，小控件在窄屏至少拉到 34–38px 并加大内边距 */
  .hw-switch{padding:3px}
  .hw-btn{min-width:48px;padding:7px 0;font-size:12px}
  .hw-btn small{font-size:9.5px}
  .seg button{padding:9px 16px;min-height:36px}
  .tagchip{padding:8px 15px;min-height:34px}
  .filter-reset{padding:6px 2px;min-height:34px}
  .hot-jump{padding:7px 12px;min-height:34px}
  .more-btn{padding:10px 26px;min-height:40px}
  .date-btn{padding:5px 9px}
  /* 悬浮导航舱 → 底部横条（居中、安全区上方），顶部细进度条接管「我在哪」 */
  .mprog{display:block}
  .navpod{right:auto;left:50%;bottom:calc(12px + env(safe-area-inset-bottom,0px));
    flex-direction:row;align-items:center;gap:0;transform:translateX(-50%)}
  .navpod.tuck{transform:translateX(-50%) translateY(180%)}
  .navpod:hover,.navpod:focus-within{opacity:1}
  .np-bar{flex-direction:row;gap:10px}
  .np-ring,.np-btn{width:46px;height:46px}
  .np-ring-svg{width:46px;height:46px}
  /* 面板从底部横条上方升起（bottom sheet 观感）；位置由脚本按按钮实测锚定 */
  .np-list{position:absolute;bottom:calc(100% + 10px);right:auto;left:50%;
    width:min(320px,calc(100vw - 24px));
    padding:8px;box-shadow:var(--shadow-pop)}
  .np-item{padding:11px 12px;min-height:44px;font-size:14px}
  /* 日期 / 阅读设置面板：与环节面板同一形态，宽度放宽到 320px 便于日期与输入 */
  .np-panel{position:absolute;bottom:calc(100% + 10px);right:auto;left:50%;
    width:min(320px,calc(100vw - 24px));max-height:min(66vh,520px)}
  .np-date{padding:11px 12px;min-height:44px;font-size:14px}
  .np-jump input{padding:10px 11px;font-size:14px;min-height:42px}
  .np-seg button{padding:11px 4px;font-size:13.5px;min-height:44px}
  /* 抽屉头在窄屏允许换行：面包屑 + 语言三态 + 动作键不挤在一行 */
  .drawer-head{flex-wrap:wrap;padding:12px 16px}
  .drawer-lang{order:3;margin:8px 0 0}
  .drawer-actions{margin-left:auto}
  /* 详情页「译」按钮在窄屏要够 finger 高度（抽屉内空间紧张，取 34px） */
  .dr-bi{min-height:34px;padding:6px 13px;font-size:11.5px;margin-top:1px}
  /* 抽屉与命令面板：贴满可用宽度 */
  .cmdk{padding:8vh 10px 10px}
  .cmdk-list{max-height:60vh}
  .resume{bottom:calc(78px + env(safe-area-inset-bottom,0px));font-size:12px;
    padding:8px 12px}
  .hero{padding:30px 0 8px;gap:22px}
  .hero-dist{width:100%}
  .hero-figure{padding:22px 0 4px}
  /* 窄屏：地域构成换行至第二行，分隔线改矮、去掉左距 */
  .hero-region{margin-left:0;padding-top:14px;gap:12px;
    align-self:auto;margin-bottom:0}
  .hr-sep{height:22px}
  .hr-item b{font-size:18px}
  .hero-date-mini span{white-space:normal}
  .hotbar-stats{margin-left:0;width:100%}
  .hs-chip{padding:3px 10px 4px}
  .hs-chip b{font-size:16px}
  .axis-mini{display:none}
  .filters{top:auto;position:static;backdrop-filter:none}
  .node{scroll-margin-top:20px;margin-top:26px;padding:20px 16px 16px;border-radius:16px}
  /* 窄屏：节点描述独占一行左对齐，条数读数跟随标题行右侧 */
  .node-desc{flex-basis:100%;text-align:left;margin:6px 0 0}
  .node-desc::before{display:none}
  .node-count{margin-left:auto;padding-left:12px}
  .node-count b{font-size:19px}
  .hot-title{white-space:normal}
  .hot-flags{margin-left:2px}
  /* 主轴转纵向 */
  .axis-hero{padding:16px 14px 14px;border-radius:16px}
  .ah-track{flex-direction:column;gap:10px;padding:4px 0 0}
  .ah-flow{left:23px;right:auto;top:10%;bottom:10%;width:2px;height:auto;
    background:linear-gradient(180deg,var(--accent-capability),var(--accent-product),
      var(--accent-industry),var(--accent-governance),var(--accent-frontier));
    background-size:100% 220%;animation:ahflowv 10s linear infinite}
  @keyframes ahflowv{to{background-position:0 -220%}}
  .ah-node{flex-direction:row;align-items:center;gap:12px;padding:11px 12px;
    margin-left:14px}
  .ahn-top{width:auto;flex:none}
  .ahn-names{flex:1;min-width:0}
  .ahn-desc{display:none}
  .ahn-flag{position:static;margin-left:2px}
  .grid{grid-template-columns:1fr}
  .drawer{width:100vw;border-left:none}
  /* 窄屏脚注仍是同一套三列版式，只收窄列间距（列宽基准不变，避免与桌面两种结构） */
  .footer{--fw-gap:6px}
}
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation:none!important;transition:none!important}
  html{scroll-behavior:auto}
}
</style>
</head>
<body>

<!-- 移动端阅读进度条（桌面由导航舱的进度环承担） -->
<div class="mprog" id="mprog" aria-hidden="true"><i></i></div>

<header class="topbar">
  <div class="brand">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.8" stroke-linecap="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3
      M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>
      <circle cx="12" cy="12" r="3.2"/></svg>
    <span class="brand-text"><span class="brand-zh">月生 · AI 资讯日报</span><small>ASYS · AI NEWS DAILY</small></span>
  </div>
  <div class="datepicker">
    <button class="date-btn" id="dateBtn" type="button" aria-expanded="false"
      aria-haspopup="listbox" aria-label="选择日期">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.8"><rect x="3" y="5" width="18" height="16" rx="2"/>
        <path d="M16 3v4M8 3v4M3 10h18"/></svg>
      <span class="date-btn-text">
        <!-- 上行：短日期 + 双窗口条数（归属同一行，紧贴日期）；
             下行：完整日期 + 星期。两行分列，控件整体更紧凑。 -->
        <span class="date-btn-top"><b id="dateBtnMd">@@MD@@</b>
          <span class="date-btn-counts" aria-label="该日 24H / 48H 入档条数（高亮为当前窗口）">
            <span class="dc-chip c24 is-on" id="dateBtnC24" title="24H 条数（当日）"
              >@@C24@@</span>
            <span class="dc-chip c48" id="dateBtnC48" title="48H 条数（前日 + 当日）"
              >@@C48@@</span>
          </span></span>
        <i id="dateBtnFull">@@DATE_FULL@@</i></span>
      <svg class="date-caret" width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
    </button>
    <div class="dm" id="dateMenu" hidden>
      <div class="dm-head">
        <button class="dm-nav" id="dmPrev" type="button" aria-label="上一个月">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M15 5l-7 7 7 7"/></svg></button>
        <div class="dm-title"><b id="dmMonth">—</b><i id="dmHint"></i></div>
        <button class="dm-nav" id="dmNext" type="button" aria-label="下一个月">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 5l7 7-7 7"/></svg></button>
        <button class="dm-today" id="dmToday" type="button" title="跳到最新一期日报">最新</button>
      </div>
      <div class="dm-week" aria-hidden="true"><span>一</span><span>二</span><span>三</span>
        <span>四</span><span>五</span><span>六</span><span>日</span></div>
      <div class="dm-grid" id="dmGrid" role="listbox" aria-label="日期网格"></div>
      <div class="dm-foot">
        <span class="dm-lg"><i class="lg24"></i>24H 条数（当日）</span>
        <span class="dm-lg"><i class="lg48"></i>48H 条数（前日 + 当日）</span>
        <span class="dm-tip">← → 切日 · ↑ ↓ 切周 · PgUp/PgDn 翻月 · ESC 关闭</span>
      </div>
    </div>
  </div>
  <div class="spacer"></div>
  <div class="searchbox">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
    <input id="search" type="search" placeholder="搜索标题 / 摘要（/）" aria-label="搜索资讯">
  </div>
  <!-- 语言模式三态：原文（默认） / 对照（原文下附译文） / 目标语（译文为主） -->
  <div class="lang-switch" id="langSwitch" role="group" aria-label="语言模式">
    <button type="button" data-lang-mode="orig" aria-pressed="true"
      title="只显示信源原文（规范：标题不改写）">原文</button>
    <button type="button" data-lang-mode="both" aria-pressed="false"
      title="原文为主，其下附一行对照译文">对照</button>
    <button type="button" data-lang-mode="tgt" aria-pressed="false"
      title="以对照译文为主，原文降权附于其下">目标语</button>
  </div>
  <div class="theme-switch" role="group" aria-label="主题模式">
    <button type="button" data-theme-btn="dark" aria-pressed="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>深色</button>
    <button type="button" data-theme-btn="light" aria-pressed="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>浅色</button>
    <button type="button" data-theme-btn="auto" aria-pressed="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>系统</button>
  </div>
</header>

<div class="wrap">
  <p class="src-notice" id="srcNotice" role="status" hidden></p>
  <!-- 日期区块容器：内容由前端渲染函数按投影生成（离线内联 / 运行态 fetch 同一份代码） -->
  <div class="day" id="dayHost" data-date="" data-window="24"></div>
</div>

<!-- L2 · 详情抽屉 -->
<div class="overlay" id="overlay"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="drawerTitle" hidden>
  <div class="drawer-head">
    <div class="drawer-crumb" id="drawerCrumb"></div>
    <!-- 详情页就地切语言（与顶栏双向同步） -->
    <div class="lang-switch drawer-lang" id="drawerLang" role="group" aria-label="语言模式">
      <button type="button" data-lang-mode="orig" aria-pressed="true"
        title="只显示信源原文（规范：标题不改写）">原文</button>
      <button type="button" data-lang-mode="both" aria-pressed="false"
        title="原文为主，其下附对照译文">对照</button>
      <button type="button" data-lang-mode="tgt" aria-pressed="false"
        title="以对照译文为主，原文降权附于其下">目标语</button>
    </div>
    <div class="drawer-actions">
      <button type="button" class="icon-btn" id="prevItem" title="上一条（k）" aria-label="上一条">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg></button>
      <button type="button" class="icon-btn" id="nextItem" title="下一条（j）" aria-label="下一条">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg></button>
      <button type="button" class="icon-btn" id="copyLink" title="复制原文链接" aria-label="复制原文链接">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
      <button type="button" class="icon-btn" id="closeDrawer" title="关闭（Esc）" aria-label="关闭详情">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button>
    </div>
  </div>
  <div class="drawer-body" id="drawerBody"></div>
</aside>
<!-- 悬浮导航舱：整页进度 + 回顶 / 回底 / 环节 / 日期 / 阅读设置 / 命令面板
     （移动端形态见响应式段） -->
<nav class="navpod" id="navpod" aria-label="阅读定位与导航">
  <div class="np-list" id="npList" role="menu" aria-label="环节导航" hidden></div>
  <!-- 日期跳转面板：最近 10 天直达 + 指定日期输入（格式 YYYY-MM-DD，实时校验） -->
  <div class="np-panel" id="npDate" role="menu" aria-label="日期跳转" hidden>
    <div class="np-cap"><span data-ui="dates">日期跳转</span><em>DATES</em></div>
    <div id="npDateRows"></div>
    <div class="np-jump">
      <label for="npDateInput" data-ui="godate">跳到指定日期</label>
      <input id="npDateInput" type="text" inputmode="numeric" autocomplete="off"
        placeholder="YYYY-MM-DD" aria-describedby="npDateHint">
      <p class="np-hint" id="npDateHint"></p>
    </div>
  </div>
  <!-- 阅读设置面板：字号三档 + 密度两档（原来只藏在命令面板里，等于没有） -->
  <div class="np-panel" id="npRead" role="group" aria-label="阅读设置" hidden>
    <div class="np-cap"><span data-ui="read">阅读设置</span><em>READING</em></div>
    <div class="np-grp">
      <div class="np-grp-t" data-ui="fontsize">字号</div>
      <div class="np-seg" id="npFs" role="group" aria-label="字号">
        <button type="button" data-fs="1" aria-pressed="true">标准</button>
        <button type="button" data-fs="1.08" aria-pressed="false">大</button>
        <button type="button" data-fs="1.16" aria-pressed="false">特大</button>
      </div>
    </div>
    <div class="np-grp">
      <div class="np-grp-t" data-ui="density">密度</div>
      <div class="np-seg" id="npDensity" role="group" aria-label="密度">
        <button type="button" data-dense="0" aria-pressed="true">标准</button>
        <button type="button" data-dense="1" aria-pressed="false">紧凑</button>
      </div>
    </div>
  </div>
  <div class="np-bar">
    <button type="button" class="np-ring" id="npTop" title="回到顶部（Home）"
      aria-label="回到顶部">
      <svg class="np-ring-svg" viewBox="0 0 44 44" aria-hidden="true">
        <circle class="np-ring-track" cx="22" cy="22" r="19"/>
        <circle class="np-ring-bar" id="npRingBar" cx="22" cy="22" r="19"/>
      </svg>
      <span class="np-ring-ico" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
          stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 19V6M6 12l6-6 6 6"/></svg></span>
    </button>
    <button type="button" class="np-btn" id="npBottom" title="回到底部（End）"
      aria-label="回到底部">
      <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
        stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 5v13M6 12l6 6 6-6"/></svg></button>
    <button type="button" class="np-btn" id="npNodes" aria-expanded="false"
      aria-controls="npList" title="环节导航（1–5）" aria-label="环节导航">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
    </button>
    <button type="button" class="np-btn" id="npDates" aria-expanded="false"
      aria-controls="npDate" title="日期跳转（最近 10 天 / 指定日期）" aria-label="日期跳转">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round"><rect x="3" y="5" width="18" height="16" rx="2"/>
        <path d="M8 3v4M16 3v4M3 10h18"/></svg>
    </button>
    <button type="button" class="np-btn" id="npReadBtn" aria-expanded="false"
      aria-controls="npRead" title="阅读设置（字号 / 密度）" aria-label="阅读设置">
      <span aria-hidden="true" style="font-size:13px;font-weight:700;letter-spacing:.02em">Aa</span>
    </button>
    <button type="button" class="np-btn" id="npCmd" title="命令面板（⌘K / Ctrl+K）"
      aria-label="命令面板">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg></button>
  </div>
</nav>

<!-- 命令面板 -->
<div class="cmdk" id="cmdk" hidden>
  <div class="cmdk-panel" role="dialog" aria-modal="true" aria-label="命令面板">
    <div class="cmdk-input">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
      <input id="cmdkInput" type="text" placeholder="跳日期 / 跳环节 / 搜标题 / 切窗口 / 切主题…"
        autocomplete="off" aria-label="命令输入">
      <kbd>ESC</kbd>
    </div>
    <div class="cmdk-list" id="cmdkList" role="listbox" aria-label="命令结果"></div>
  </div>
</div>

<!-- 双语对照浮层（悬停/点按共用；position:fixed 不占文档流） -->
<div class="bi-pop" id="biPop" role="tooltip" hidden></div>

<!-- 继续上次阅读（重访时提示，可关闭） -->
<div class="resume" id="resume" hidden>
  <span data-ui="resume">上次读到 <b id="resumeNode">—</b></span>
  <button type="button" id="resumeGo">继续</button>
  <button type="button" class="resume-x" id="resumeX" aria-label="关闭">×</button>
</div>

<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script>
"use strict";
/* ============ 前端资产（由 Python 单一实现生成，勿手改） ============ */
@@RUNTIME_ASSETS@@

/* ============ 数据源（两形态同源：离线内联 / 运行态 fetch） ============
   mode = "offline"：全部投影内联（自包含单文件、零网络请求）
   mode = "runtime"：索引与首屏投影内联兜底，其余日期按需 fetch（表源不可读时降级）
*/
const VIEW_SRC = @@VIEW_SRC_JSON@@;
let INDEX = null;              // L2 索引：各日双窗口条数 + 最近完整日
const VIEW_CACHE = {};         // "<日期>_<窗口>h" → 投影（内存缓存，不重复请求）
let FALLBACK = false;          // 数据源不可读 → 内联首屏兜底 + 提示条
/* 当前视图状态（渲染函数驱动，取代原先的预烘焙区块） */
const DATA = { current: null, latest: null, newest: null, window: 24 };
const COUNTS = {};             // "<日期>" → {24, 48, live}（来自索引）

const viewKey = (d, w) => d + "_" + w + "h";
const inlineView = (d, w) => (VIEW_SRC.views || {})[viewKey(d, w)] || null;

const IS_FILE = location.protocol === "file:";   // file:// 下浏览器禁止页面读本地 JSON
/* 数据根候选：页面可能落在不同根下（项目根 / 仪表盘/ / 服务根 / 静态托管根）。
   逐个探测 index.json，取第一个返回合法索引的作为数据根，成功后固定，后续视图请求复用同一根。
   `data/views/` 是 ASCII 候选：部分静态托管平台对中文目录名会做 URL 编码，
   路径形态可能与本地不一致；发布包同时提供 ASCII 目录以保证托管环境取得到数。 */
const BASE_CANDIDATES = (function(){
  const first = VIEW_SRC.base || "../数据/视图/";
  return [first, "数据/视图/", "./数据/视图/", "/数据/视图/",
          "data/views/", "./data/views/", "/data/views/"]
    .filter((x, i, a) => a.indexOf(x) === i);
})();
let VIEW_BASE = null;
/* 某「日期 × 窗口」当前是否可取数：有内联兜底 → 可取；否则取决于数据根是否连通 */
const viewable = (d, w) => !!inlineView(d, w) || !!VIEW_BASE;

async function fetchJSON(url){
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return await r.json();
}
async function loadIndex(){
  // 离线形态数据全内联、file:// 形态读不到本地文件：两种都不发请求
  if (VIEW_SRC.mode === "offline" || IS_FILE) return VIEW_SRC.index;
  for (const base of BASE_CANDIDATES){
    try {
      const idx = await fetchJSON(base + "index.json");
      if (idx && idx.schema){ VIEW_BASE = base; return idx; }
    } catch (e){ /* 该候选根不可用：试下一个 */ }
  }
  FALLBACK = true;
  return VIEW_SRC.index;
}
async function loadView(d, w){
  const key = viewKey(d, w);
  if (VIEW_CACHE[key]) return VIEW_CACHE[key];
  let v = inlineView(d, w);
  if (!v && VIEW_BASE){
    try {
      v = await fetchJSON(VIEW_BASE + key + ".json");
    } catch (e){
      FALLBACK = true;
      v = inlineView(d, w);
    }
  }
  if (v) VIEW_CACHE[key] = v;
  return v;
}

/* ============ 工具 ============ */
const $ = (s, p) => (p || document).querySelector(s);
const $$ = (s, p) => Array.from((p || document).querySelectorAll(s));
const escHtml = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const safeScrollTo = opt => { try { window.scrollTo(opt); } catch (e) {} };
const safeIntoView = (el, opt) => { try { el.scrollIntoView(opt); } catch (e) {} };

/* ============ 主题三态（深色默认 / 浅色可选 / 跟随系统；手动优先） ============
   localStorage 在不受信任环境会直接抛 SecurityError（file:// 等不透明源、隐私模式、
   禁用站点数据）——一旦抛在顶层整页脚本就中断（白屏），故一律经 store 兜底访问。 */
const store = {
  get(k){ try { return localStorage.getItem(k); } catch (e){ return null; } },
  set(k, v){ try { localStorage.setItem(k, v); } catch (e){ /* 不可持久化则仅本次生效 */ } },
};
(function initTheme(){
  const saved = store.get("yuesheng-theme") || "dark";
  applyTheme(saved);
  $$("[data-theme-btn]").forEach(b => b.addEventListener("click", () => {
    applyTheme(b.dataset.themeBtn, true);
  }));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if ((store.get("yuesheng-theme") || "dark") === "auto") applyTheme("auto");
  });
})();
function applyTheme(mode, persist){
  document.documentElement.dataset.theme = mode;
  if (persist) store.set("yuesheng-theme", mode);
  $$("[data-theme-btn]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.themeBtn === mode)));
}

/* ============ 当前日期状态 ============ */
const state = { region: "all", tags: new Set(), q: "" };
const dayEl = $("#dayHost");
let booted = false;                                  // 首屏渲染完成前不提示「继续上次」
let curData = null, curIdx = -1, lastFocus = null;   // curData = 当前投影（items + hot_events）
const dayCards = () => $$(".card", dayEl);
const daySections = () => $$(".node", dayEl);

/* ============ 日期选择器：月历（日期 + 24h/48h 双窗口条数） ============ */
const dateBtn = $("#dateBtn"), dateMenu = $("#dateMenu");
const WD = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const pad2 = n => String(n).padStart(2, "0");
const dsOf = (y, m, d) => y + "-" + pad2(m + 1) + "-" + pad2(d);
const ymKey = ds => { const p = ds.split("-").map(Number); return p[0] * 12 + p[1] - 1; };
function dateInfo(ds){
  const p = ds.split("-").map(Number);
  return { md: pad2(p[1]) + "." + pad2(p[2]),
    full: p[0] + " 年 " + p[1] + " 月 " + p[2] + " 日",
    weekday: WD[new Date(p[0], p[1] - 1, p[2]).getDay()] };
}
let DATES = [], LATEST = null, MIN_YM = 0, MAX_YM = 0;
let calYM = 0, calCursor = null;

/* 索引 → 运行态状态：条数表 / 可选日期 / 最近完整日 / 月历边界
   （一律取自 L2 索引，前端不自行推算数据范围） */
function applyIndex(){
  Object.keys(COUNTS).forEach(k => delete COUNTS[k]);
  const days = (INDEX && INDEX.days) || {};
  Object.keys(days).forEach(ds => {
    const w = days[ds].windows || {};
    COUNTS[ds] = { "24": w["24"] ? w["24"].filed : null,
                   "48": w["48"] ? w["48"].filed : null,
                   live: !!days[ds].live };
  });
  DATES = Object.keys(COUNTS).sort();
  DATA.latest = (INDEX && INDEX.latest) || (DATES.length ? DATES[DATES.length - 1] : null);
  DATA.newest = (INDEX && INDEX.newest) || DATA.latest;
  LATEST = DATA.latest;
  DATA.current = DATA.current || LATEST;
  DATA.window = +DATA.window || 24;
  if (!COUNTS[DATA.current]) DATA.current = LATEST;
  MIN_YM = DATES.length ? ymKey(DATES[0]) : 0;
  MAX_YM = DATES.length ? ymKey(LATEST) : 0;
  calYM = ymKey(DATA.current); calCursor = DATA.current;
}

/* 投影 → 日期区块内容（装配在渲染纯函数里，页面只负责插入容器） */
function renderViewInner(v, ctx){
  return FRAGMENTS.dayInner(v, ctx);
}
function winCountsOf(ds){
  const c = COUNTS[ds] || {};
  return { "24": c["24"], "48": c["48"] };
}

function stepMonth(n){
  const t = calYM + n;
  if (t < MIN_YM || t > MAX_YM) return false;
  calYM = t;
  return true;
}
/* 格内只显示条数：青=24H 当日整日、紫=48H（前一日 + 当日），颜色含义见图例 */
function chipHtml(w, n, ds){
  const on = (ds === DATA.current && +DATA.window === +w);
  return '<span class="dc-chip c' + w + (on ? " is-on" : "") + '" data-window="' + w
    + '" data-date="' + ds + '" title="以 ' + w + ' 小时窗口打开 ' + ds
    + '（共 ' + n + ' 条）">' + n + '</span>';
}
function renderCal(){
  const y = Math.floor(calYM / 12), m = calYM % 12;
  const lead = (new Date(y, m, 1).getDay() + 6) % 7;   // 周一首列
  const days = new Date(y, m + 1, 0).getDate();
  let html = "";
  for (let i = 0; i < lead; i++) html += '<span class="dm-pad" aria-hidden="true"></span>';
  for (let d = 1; d <= days; d++){
    const ds = dsOf(y, m, d), c = COUNTS[ds];
    if (!c){
      // 无该日数据的日期照常占位显示日号（保持与星期表头对齐），不可点击
      html += '<span class="dm-cell is-empty"><span class="dc-day">' + d
        + '</span><span class="dc-n" aria-hidden="true"></span></span>';
      continue;
    }
    const sel = ds === DATA.current;
    // 数据目录未连通时仅内联兜底的那天可取数，其余标注不可切换（title 说明原因）
    const off = !viewable(ds, 24) && !viewable(ds, 48);
    html += '<button type="button" role="option" class="date-opt'
      + (ds === LATEST ? " is-latest" : "") + (c.live ? " is-live" : "")
      + (off ? " is-off" : "")
      + '" data-date="' + ds + '"'
      + ' aria-selected="' + (sel ? "true" : "false") + '"'
      + (off ? ' aria-disabled="true"' : "")
      + ' title="' + ds + " · 24H " + (c["24"] || 0) + " 条 / 48H "
      + (c["48"] || 0) + " 条" + (c.live ? " · 进行中（该自然日尚未结束）" : "")
      + (off ? " · 运行态未连通数据目录，暂不可切换" : "") + '">'
      + '<span class="dc-day">' + d + "</span>"
      + '<span class="dc-n">' + chipHtml(24, c["24"] || 0, ds)
      + chipHtml(48, c["48"] || 0, ds) + "</span></button>";
  }
  $("#dmGrid").innerHTML = html;
  $("#dmMonth").textContent = y + " 年 " + (m + 1) + " 月";
  const inMonth = DATES.filter(ds => ymKey(ds) === calYM);
  const sum = inMonth.reduce((a, ds) => a + (+(COUNTS[ds] || {})["24"] || 0), 0);
  $("#dmHint").textContent = inMonth.length + " DAYS · " + sum + " ITEMS";
  $("#dmPrev").disabled = calYM <= MIN_YM;
  $("#dmNext").disabled = calYM >= MAX_YM;
}
function setCursor(ds){
  calCursor = ds;
  calYM = Math.min(MAX_YM, Math.max(MIN_YM, ymKey(ds)));
  renderCal();
  const el = $('.date-opt[data-date="' + ds + '"]', $("#dmGrid"));
  if (el) el.focus();
}
function shiftCursor(delta){
  const p = calCursor.split("-").map(Number);
  const nd = new Date(p[0], p[1] - 1, p[2] + delta);
  let nxt = dsOf(nd.getFullYear(), nd.getMonth(), nd.getDate());
  if (!COUNTS[nxt]){
    const asc = delta > 0;
    const cand = DATES.filter(ds => asc ? ds > calCursor : ds < calCursor);
    nxt = asc ? (cand[0] || calCursor) : (cand.length ? cand[cand.length - 1] : calCursor);
  }
  setCursor(nxt);
}
function openDateMenu(){
  calYM = ymKey(DATA.current || LATEST);
  calCursor = DATA.current || LATEST;
  renderCal();
  dateMenu.hidden = false;
  dateBtn.setAttribute("aria-expanded", "true");
  const el = $('.date-opt[data-date="' + DATA.current + '"]', $("#dmGrid"));
  if (el) el.focus();
}
function closeDateMenu(){
  dateMenu.hidden = true;
  dateBtn.setAttribute("aria-expanded", "false");
}
dateBtn.addEventListener("click", e => {
  e.stopPropagation();
  if (dateMenu.hidden) openDateMenu(); else closeDateMenu();
});
document.addEventListener("click", e => {
  if (!dateMenu.hidden && !e.target.closest(".datepicker")) closeDateMenu();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !dateMenu.hidden){ closeDateMenu(); dateBtn.focus(); }
});
$("#dmPrev").addEventListener("click", e => { e.stopPropagation(); stepMonth(-1); renderCal(); });
$("#dmNext").addEventListener("click", e => { e.stopPropagation(); stepMonth(1); renderCal(); });
$("#dmToday").addEventListener("click", e => { e.stopPropagation(); setCursor(LATEST); });
$("#dmGrid").addEventListener("click", e => {
  const chip = e.target.closest(".dc-chip");
  if (chip){
    e.stopPropagation(); closeDateMenu();
    switchView(chip.dataset.date, +chip.dataset.window);
    return;
  }
  const cell = e.target.closest(".date-opt");
  if (!cell) return;
  e.stopPropagation(); closeDateMenu();
  switchDate(cell.dataset.date);
});
dateMenu.addEventListener("keydown", e => {
  const map = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
  if (e.key in map){ e.preventDefault(); shiftCursor(map[e.key]); return; }
  if (e.key === "PageUp"){ e.preventDefault(); stepMonth(-1); renderCal(); return; }
  if (e.key === "PageDown"){ e.preventDefault(); stepMonth(1); renderCal(); return; }
  if (e.key === "Enter" || e.key === " "){
    const cell = e.target.closest(".date-opt");
    if (cell){
      e.preventDefault(); closeDateMenu();
      switchDate(cell.dataset.date); dateBtn.focus();
    }
  }
});
/* 窗口切换（24 / 48 小时）：Hero meta 行滑轨控件在日期区块内，故用事件委托 */
function syncWindows(w){
  $$(".hw-btn", dayEl).forEach(b => b.classList.toggle("is-on", +b.dataset.window === w));
  $$(".hw-switch", dayEl).forEach(s => s.classList.toggle("on-48", w === 48));
}
function updateDateBtn(d){
  const info = dateInfo(d);
  $("#dateBtnMd").textContent = info.md;
  $("#dateBtnFull").textContent = info.full + " " + info.weekday;
  const c = COUNTS[d] || {}, cw = +DATA.window || 24;
  $("#dateBtnC24").textContent = c["24"] != null ? c["24"] : "—";
  $("#dateBtnC48").textContent = c["48"] != null ? c["48"] : "—";
  // 明确当前窗口期：高亮对应条数（与月历格内 is-on 同一视觉）
  $("#dateBtnC24").classList.toggle("is-on", cw === 24);
  $("#dateBtnC48").classList.toggle("is-on", cw === 48);
  $$(".date-opt").forEach(x =>
    x.setAttribute("aria-selected", String(x.dataset.date === d)));
}

/* ============ 日期切换（按需渲染：投影 → 标记；内存缓存，不重复请求） ============ */
function switchDate(d){ return switchView(d, DATA.window); }
let viewSeq = 0;
async function switchView(d, w){
  const ws = String(w || DATA.window || 24);
  const c = COUNTS[d];
  if (!c || c[ws] == null) return;
  const seq = ++viewSeq;
  // 运行态按需取数会有一瞬空白：先铺等高骨架屏，避免「空白 → 内容」的高度跳变
  const needFetch = !inlineView(d, ws) && !VIEW_CACHE[viewKey(d, ws)];
  if (needFetch && dayEl.children.length && curData) renderSkeleton();
  const v = await loadView(d, ws);
  if (seq !== viewSeq) return;              // 快速连点：丢弃过期渲染
  if (!v){                                  // 取不到数：说明原因，不静默失败
    if (VIEW_SRC.mode === "runtime") showNotice(runtimeNotice());
    else if (dayEl.children.length && !dayEl.querySelector(".hero")) dayEl.innerHTML = "";
    return;
  }
  DATA.current = d; DATA.window = +ws;
  dayEl.innerHTML = renderViewInner(v, { winCounts: winCountsOf(d) });
  dayEl.dataset.date = d; dayEl.dataset.window = ws;
  curData = v;
  observeSpy();
  // 重置筛选与搜索
  state.region = "all"; state.tags.clear(); state.q = "";
  $("#search").value = "";
  $$(".seg [data-region]", dayEl).forEach(x =>
    x.setAttribute("aria-pressed", String(x.dataset.region === "all")));
  $$("[data-tag]", dayEl).forEach(x => x.setAttribute("aria-pressed", "false"));
  clearHighlights(); applyFilters();      // 内部 syncShown()：渐进加载回到「已展开 8 条」
  injectBiTags(); renderCardLang(); highlight();
  countUp(dayEl);
  updateDateBtn(d);
  if (!dateMenu.hidden) renderCal();
  updateSpyManual(); updateMiniAxis();
  syncTopbarH(); syncStickyHeights(); updateNavpod(); syncNodeList(); writeHash();
  refreshPanels();                                   // 开着悬浮舱面板时同步其内容
  document.title = "月生 · AI 资讯日报 " + d;
  if (drawer.classList.contains("open")) closeDrawer();
  if (booted) { hideResume(); checkResume(); }
  if (booted) safeScrollTo({ top: 0, behavior: reduceMotion() ? "auto" : "smooth" });
}

/* ============ 筛选 ============ */
function itemMatch(card){
  if (state.region !== "all" && card.dataset.region !== state.region) return false;
  if (state.tags.size){
    const tags = card.dataset.tags ? card.dataset.tags.split(",") : [];
    if (!tags.some(t => state.tags.has(t))) return false;
  }
  if (state.q){
    const hay = (card.dataset.title + " " + card.dataset.summary).toLowerCase();
    if (!hay.includes(state.q.toLowerCase())) return false;
  }
  return true;
}
function filtersActive(){
  return state.region !== "all" || state.tags.size > 0 || state.q !== "";
}
function applyFilters(){
  const active = filtersActive();
  $(".filter-reset", dayEl).hidden = !active;
  let totalVisible = 0;
  syncShown();                    // 渐进：筛选中全部放开，否则按「已展开」收起
  daySections().forEach(sec => {
    let n = 0;
    $$(".card", sec).forEach(c => {
      const ok = itemMatch(c);
      c.style.display = ok ? "" : "none";
      if (ok && !c.hidden) n++;
    });
    totalVisible += n;
    const cnt = $(".node-count", sec);
    if (cnt) {
      // 保留徽标结构（<b>数字</b><i>条</i>），筛选时大数字变为可见数
      const cb = $("b", cnt), ci = $("i", cnt);
      if (cb && ci) {
        cb.textContent = active ? String(n) : cnt.dataset.total;
        ci.textContent = active ? "/ " + cnt.dataset.total + " 条" : "条";
      } else {
        cnt.textContent = (active ? n + " / " : "") + cnt.dataset.total + " 条";
      }
    }
    const empty = $(".node-empty", sec);
    if (empty) empty.style.display = n ? "none" : "";
  });
  // 主轴计数同步（大主轴 + 迷你主轴）
  $$(".ah-node", dayEl).forEach(b => {
    const sec = $(".node[data-node=\\"" + b.dataset.node + "\\"]", dayEl);
    const n = sec ? $$(".card", sec).filter(c => c.style.display !== "none").length : 0;
    const el = $(".ahn-count", b);
    el.textContent = (active ? n + " / " : "") + b.dataset.total + " 条";
  });
  $$(".am-btn", dayEl).forEach(b => {
    const sec = $(".node[data-node=\\"" + b.dataset.node + "\\"]", dayEl);
    const n = sec ? $$(".card", sec).filter(c => c.style.display !== "none").length : 0;
    const el = $("em:not(.am-flag)", b);
    if (el) el.textContent = (active ? n + " / " : "") + b.dataset.total;
  });
  dayEl.classList.toggle("searching", state.q !== "" && totalVisible === 0);
}
function resetFilters(){
  state.region = "all"; state.tags.clear(); state.q = "";
  $("#search").value = "";
  $$(".seg [data-region]", dayEl).forEach(x =>
    x.setAttribute("aria-pressed", String(x.dataset.region === "all")));
  $$("[data-tag]", dayEl).forEach(x => x.setAttribute("aria-pressed", "false"));
  clearHighlights(); applyFilters();
}

/* ============ 搜索 + 高亮 ============ */
const searchInput = $("#search");
let searchTimer = null;
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = searchInput.value.trim();
    applyFilters(); highlight();
  }, 120);
});
/* 文案刷新总入口：先按语言模式重排卡片双语，再套搜索高亮。
   （顺序不能反：重排会重建标题节点，先高亮会被冲掉） */
function refreshText(){
  renderCardLang();
  highlight();
}
function clearHighlights(){
  dayCards().forEach(c => {
    const t = titleTextNode(c);
    if (t) t.textContent = c.dataset.title;
  });
}
function highlight(){
  clearHighlights();
  if (!state.q) return;
  const q = state.q.toLowerCase();
  dayCards().forEach(c => {
    if (c.style.display === "none") return;
    const t = titleTextNode(c);
    const raw = c.dataset.title;
    const idx = raw.toLowerCase().indexOf(q);
    if (idx < 0) return;
    t.innerHTML = escHtml(raw.slice(0, idx)) + "<mark>" +
      escHtml(raw.slice(idx, idx + q.length)) + "</mark>" +
      escHtml(raw.slice(idx + q.length));
  });
}

/* ============ 主轴 scrollspy（含降级；每次渲染后重新订阅） ============ */
function setSpy(node){
  $$(".ah-node, .am-btn", dayEl).forEach(b =>
    b.setAttribute("aria-current", String(b.dataset.node === node)));
}
let spy = null;
function observeSpy(){
  if (spy) { spy.disconnect(); spy = null; }
  if (!("IntersectionObserver" in window)) return;
  spy = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting && dayEl.contains(e.target)) setSpy(e.target.dataset.node);
    });
  }, { rootMargin: "-20% 0px -70% 0px", threshold: 0 });
  $$(".node", dayEl).forEach(s => spy.observe(s));
}
window.addEventListener("scroll", () => updateSpyManual(), { passive: true });
function updateSpyManual(){
  let cur = null;
  daySections().forEach(s => {
    const r = s.getBoundingClientRect();
    if (r.top <= window.innerHeight * 0.35 && r.bottom > 0) cur = s.dataset.node;
  });
  if (cur) setSpy(cur);
  syncNodeList();                 // 导航舱的环节面板与主轴共用同一处当前环节
}
function scrollToNode(node){
  const sec = $(".node[data-node=\\"" + node + "\\"]", dayEl);
  if (sec) safeIntoView(sec, { behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
}

/* ============ 迷你主轴显隐 ============ */
function updateMiniAxis(){
  const hero = $(".axis-hero", dayEl);
  const show = !!hero && hero.getBoundingClientRect().bottom < 64;
  $$(".axis-mini", dayEl).forEach(m => m.classList.toggle("show", show));
}
window.addEventListener("scroll", () => updateMiniAxis(), { passive: true });
window.addEventListener("resize", () => updateMiniAxis());

/* ============ 数字滚动（reduced-motion 降级） ============ */
function countUp(scope){
  const reduce = reduceMotion();
  $$(".stat-num", scope).forEach(el => {
    const target = parseInt(el.dataset.target, 10) || 0;
    if (reduce){ el.textContent = target; return; }
    const t0 = performance.now(), dur = 900;
    (function tick(t){
      const p = Math.min(1, (t - t0) / dur);
      el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  });
}

/* ============ 事件委托（绑在常驻日期容器上，内容按需渲染） ============ */
dayEl.addEventListener("click", e => {
    const win = e.target.closest(".hw-btn");
    if (win && dayEl.contains(win)){ switchView(DATA.current, +win.dataset.window); return; }
    const region = e.target.closest(".seg [data-region]");
    if (region && dayEl.contains(region)){
      state.region = region.dataset.region;
      $$("[data-region]", dayEl).forEach(x =>
        x.setAttribute("aria-pressed", String(x === region)));
      applyFilters(); return;
    }
    const tag = e.target.closest(".tagchip[data-tag]");
    if (tag && dayEl.contains(tag)){
      const t = tag.dataset.tag;
      state.tags.has(t) ? state.tags.delete(t) : state.tags.add(t);
      tag.setAttribute("aria-pressed", String(state.tags.has(t)));
      applyFilters(); return;
    }
    const reset = e.target.closest(".filter-reset");
    if (reset && dayEl.contains(reset)){ resetFilters(); return; }
    const axis = e.target.closest(".ah-node, .am-btn");
    if (axis && dayEl.contains(axis)){ scrollToNode(axis.dataset.node); return; }
    // 热点条目 → 定位到下方面板里的那一条
    const jump = e.target.closest(".hot-jump");
    if (jump && dayEl.contains(jump)){ locateCard(jump.dataset.target); return; }
    // 卡片 → 回到上方热点条目（交叉热点代表）
    const cardHot = e.target.closest(".card-hot");
    if (cardHot && dayEl.contains(cardHot)){ locateHot(cardHot.dataset.target); return; }
    const hot = e.target.closest(".hot-head");
    if (hot && dayEl.contains(hot)){
      const open = hot.getAttribute("aria-expanded") === "true";
      hot.setAttribute("aria-expanded", String(!open));
      hot.closest(".hot-item").querySelector(".hot-timeline").hidden = open;
      return;
    }
    // 渐进加载：展开更多（增量）/ 收起（回到首屏 8 条并滚回节头）
    const moreBtn = e.target.closest(".more-btn");
    if (moreBtn && dayEl.contains(moreBtn)){
      const sec = moreBtn.closest(".node");
      if (moreBtn.dataset.act === "more") expandSection(sec);
      else collapseSection(sec);
      return;
    }
    // 触屏「译」图标：就地展开/收起该条译文（点它不该打开抽屉）
    const biTag = e.target.closest(".card-bi");
    if (biTag && dayEl.contains(biTag)){
      e.stopPropagation();
      toggleCardAlt(biTag.closest(".card"));
      return;
    }
    const card = e.target.closest(".card");
    if (card && dayEl.contains(card)){ openDrawer(card.dataset.id); return; }
});
dayEl.addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  const card = e.target.closest ? e.target.closest(".card") : null;
  if (card && dayEl.contains(card)){ e.preventDefault(); openDrawer(card.dataset.id); }
});

/* ============ 热点 ↔ 面板 双向定位 ============
   热点条目尾部的「环节 · 序号」→ 定位到面板卡片；卡片上的「交叉热点」→ 回到热点条目。
   定位前只解开**真正挡住这条卡片**的状态（筛选隐藏 / 「查看全部」折叠），再滚动并高亮。 */
function flash(el){
  el.classList.remove("is-target");
  el.style.animation = "";             // 复位内联覆盖，让 .is-target 的类规则生效
  void el.offsetWidth;                 // 重置动画，连点也能重放
  el.classList.add("is-target");
  setTimeout(() => {
    el.classList.remove("is-target");
    // 与移类同一任务内把动画定点关掉：`.card` 自身带 rise 出现动画，单独移掉 .is-target 会让
    // animation-name 从 targetFlash 回落到 rise → 浏览器新建一个动画 → 高亮结束后卡片又闪一下。
    // 内联 none 一步到位，两个变更同帧生效，浏览器不会创建新动画（不复用「开关类名」写法）。
    el.style.animation = "none";
  }, 2600);
}
/* 卡片此刻是否真的看得见：① 筛选把它置为内联 display:none；
   ② 「查看全部」折叠由样式规则 .grid > .card:nth-child(n+9) 接管。
   两种都要算「隐藏」——只看内联样式会漏掉折叠。 */
function cardShown(card){
  if (card.style.display === "none") return false;
  return getComputedStyle(card).display !== "none";
}
function shownCards(){ return dayCards().filter(cardShown); }
/* 解隐藏时「被迫现身」的卡片不重放出现动画（否则整块面板跟着闪一次）。
   用内联 animation:none 定点处理：与 display 变更同处一个任务内，浏览器不会画出动画首帧。
   不用「开关类名」的写法——类名一旦移除，动画会被重新创建，等于又闪一次。
   **目标卡片必须排除在外**：内联 animation 的优先级高于 .is-target 的类规则，
   连它一起冻结会把定位高亮（targetFlash）也一起关掉。 */
function freezeEntrance(cards){
  cards.forEach(c => { if (cardShown(c)) c.style.animation = "none"; });
}
function locateCard(itemId){
  if (!itemId) return false;
  const card = $('.card[data-id="' + itemId + '"]', dayEl);
  if (!card) return false;
  // 已经显示在界面上的：什么都不解开（多余的解开会牵动整块面板），只滚到它并高亮；
  // 只有真被筛选隐藏、或被渐进加载折叠挡住的，才解开对应的一处。
  if (!cardShown(card)){
    // 取两个检查点（解隐藏前、还原筛选后）：任一时点被隐藏的卡片都算「被迫现身」，
    // 它们不能重放出现动画 —— 否则整块面板会跟着闪一次。
    const before = shownCards();
    ensureCardVisible(card);                      // ① 渐进折叠 ② 筛选隐藏
    const mid = shownCards();
    freezeEntrance(dayCards().filter(c => c !== card &&
      !(before.indexOf(c) >= 0 && mid.indexOf(c) >= 0)));
  }
  safeIntoView(card, { behavior: reduceMotion() ? "auto" : "smooth", block: "center" });
  flash(card);
  return true;
}
function locateHot(eventId){
  if (!eventId) return false;
  const item = $('.hot-item[data-event="' + eventId + '"]', dayEl);
  if (!item) return false;
  const head = $(".hot-head", item);
  if (head && head.getAttribute("aria-expanded") !== "true") head.click();
  safeIntoView(item, { behavior: reduceMotion() ? "auto" : "smooth", block: "center" });
  flash(item);
  return true;
}

/* ============ L2 详情抽屉 ============ */
const drawer = $("#drawer"), overlay = $("#overlay"), body = $("#drawerBody");

function visibleCardsInNode(node){
  return dayCards().filter(c => c.dataset.node === node && cardShown(c));
}
/* ============ 抽屉头部：标题 + 摘要 + 对照译文（三模式各自成形） ============
   原文：原文在前，标题行右侧「译」按钮点开即就地对照（触屏无悬停时的等价入口）
   对照：原文在前，译文按「标题一块 / 摘要一块」紧随其后，读者能逐块对上号
   目标语：译文为主（用全文译文 summary_full_alt，不用压缩摘要译文），原文退为附注
   悬停浮层两种方向都支持：原文模式给译文，目标语模式给信源原文。 */
let drawerLead = "", drawerTail = "", drawerItem = null, drBiOn = false;
function drawerLeadHTML(it){
  const mode = document.documentElement.dataset.langmode || "orig";
  const tOrig = it.title || "", tAlt = it.title_alt || "";
  const sOrig = it.summary_full || it.summary || "";
  // 摘要译文只用**全文译文**（与正文同源）；没有全文译文时宁可留空并说明，
  // 也不拿压缩摘要译文冒充全文——那正是「译文不完整」的观感来源。
  const sAltFull = it.summary_full_alt || "";
  const sAltCard = it.summary_alt || "";
  const sAlt = sAltFull || sAltCard;
  const hasAlt = !!(tAlt || sAlt);
  const attrs = hasAlt
    ? ' data-lang="' + escHtml(it.lang || "") + '"' +
      ' data-title-alt="' + escHtml(tAlt) + '" data-summary-alt="' + escHtml(sAlt) + '"' +
      ' data-title-orig="' + escHtml(tOrig) + '" data-summary-orig="' + escHtml(sOrig) + '"'
    : "";
  // 覆盖度说明：① 译文只覆盖部分原文（超长/分段失败）② 只有压缩摘要译文 ③ 无摘要译文
  const covNote = sOrig && !sAltFull
    ? '<p class="drawer-note">' + (sAltCard
        ? "摘要全文暂无译文，下方为列表压缩摘要（≤60 汉字）的对照译文。"
        : "摘要暂无译文（机器翻译未覆盖本条）。") + "</p>"
    : (it.summary_full_alt_partial
      ? '<p class="drawer-note">原文较长，机器译文只覆盖了前若干段，其余未译。</p>' : "");
  if (mode === "tgt" && hasAlt){
    return '<div class="drawer-trow"><h2 class="drawer-title" id="drawerTitle"' + attrs + ">" +
      escHtml(tAlt || tOrig) + "</h2></div>" +
      '<p class="drawer-summary"' + attrs + ">" + escHtml(sAlt || sOrig) + "</p>" +
      covNote +
      '<div class="drawer-orig"><b>' + escHtml(uiZh("srcorig")) + "</b>" + escHtml(tOrig) +
      (sOrig && sOrig !== sAlt ? "<br>" + escHtml(sOrig) : "") + "</div>";
  }
  const biBtn = mode === "orig" && hasAlt
    ? '<button type="button" class="dr-bi" data-dr-bi="1" aria-pressed="' + (drBiOn ? "true" : "false") +
      '" title="显示对照译文（机器译文 · 未校对）">' +
      escHtml(drBiOn ? uiZh("hidealt") : uiZh("showalt")) + "</button>"
    : "";
  const altBlock = (mode === "both" && hasAlt)
    ? '<p class="drawer-alt"><span class="da-tag">' + escHtml(MT_TAG) + "</span>" +
      (tAlt ? "<b>" + escHtml(tAlt) + "</b>" : "") +
      (sAlt ? '<span class="da-sum">' + escHtml(sAlt) + "</span>" : "") + "</p>"
    : "";
  return '<div class="drawer-trow">' +
    '<h2 class="drawer-title" id="drawerTitle"' + attrs + ">" + escHtml(tOrig) + "</h2>" +
    biBtn + "</div>" +
    '<p class="drawer-summary"' + attrs + ">" + escHtml(sOrig) + "</p>" +
    altBlock + covNote;
}
/* 「译」按钮：在原文与对照之间就地切换译文块（不重渲染、不丢滚动位置） */
function applyDrBi(){
  const old = $(".drawer-alt", body);
  if (old) old.remove();
  const btn = $("[data-dr-bi]", body);
  if (btn){
    btn.setAttribute("aria-pressed", String(drBiOn));
    btn.textContent = drBiOn ? (uiZh("hidealt") || "收起对照") : (uiZh("showalt") || "译文对照");
  }
  if (!drBiOn || !drawerItem) return;
  const tAlt = drawerItem.title_alt || "";
  const sAlt = drawerItem.summary_full_alt || drawerItem.summary_alt || "";
  if (!(tAlt || sAlt)) return;
  const p = document.createElement("p");
  p.className = "drawer-alt";
  p.innerHTML = '<span class="da-tag">' + escHtml(MT_TAG) + "</span>" +
    (tAlt ? "<b>" + escHtml(tAlt) + "</b>" : "") +
    (sAlt ? '<span class="da-sum">' + escHtml(sAlt) + "</span>" : "");
  const s = $(".drawer-summary", body);
  if (s && s.parentNode) s.parentNode.insertBefore(p, s.nextSibling);
  else body.insertBefore(p, body.firstChild);
}
/* 语言模式变化 → 抽屉正文头部跟着重排（元信息与相关报道等语言无关，原样保留） */
function refreshDrawerLang(){
  if (!drawer.classList.contains("open") || !drawerItem) return;
  const y = body.scrollTop;
  body.innerHTML = drawerLeadHTML(drawerItem) + drawerTail;
  body.scrollTop = y;
  if (drBiOn) applyDrBi();
}
function openDrawer(id){
  const it = curData.items.find(x => x.id === id);
  if (!it || !it.url) return;
  drawerItem = it; drBiOn = false;
  curIdx = curData.items.findIndex(x => x.id === id);
  lastFocus = document.activeElement;
  // 热点事件查找：canonical_item 是本条 → 就是它；否则按成员条目 id 兜底匹配。
  // （旧实现拿 source_ids（信源 id 列表）去比条目 id，永远不命中，所以多信源
  //   事件在卡片抽屉里看不到「相关报道」——本次修掉。）
  const ev = (curData.hot_events || []).find(e => e.canonical_item === id) ||
             (curData.hot_events || []).find(e =>
               (e.members || []).some(m => m.item_id === id));
  const rel = ev && ev.source_count > 1 ? (ev.members || []) : [];
  const meta = NODE_META[it.node] || {};
  const tagsC = (it.tags_c || []).map(t =>
    '<span class="chip chip-b">' + escHtml(t) + "</span>").join("");
  const tagsB = (it.tags_b || []).map(t =>
    '<span class="chip chip-b">' + escHtml(t) + "</span>").join("");
  const verified = it.source_tier === "T4"
    ? '<span class="verified no">● 未验证（T4 社区信源，需交叉验证后采信）</span>'
    : "";
  const relCountry = s => s.country_name || "";
  /* 相关报道按「信源」归组：Event 的 members 是逐条报道明细，同一信源可能
     就同一事件收录多条（如 AI HOT 的两条原始链接）。标题「N 个信源」是独立
     信源数，列表也必须同口径归组，否则同一信源会重复出现（旧 bug）。 */
  const relGroups = [], relIndex = {};
  rel.forEach(s => {
    const key = s.source_id || s.source_name || s.item_id;
    if (relIndex[key] === undefined){ relIndex[key] = relGroups.length; relGroups.push([]); }
    relGroups[relIndex[key]].push(s);
  });
  const relDom = u => { try { return new URL(u).hostname.replace(/^www\\./, ""); }
                        catch (_e) { return "另一条收录"; } };
  const relMore = g => g.slice(1).map(s =>
    '<a class="rel-more" href="' + escHtml(s.url) + '" target="_blank" ' +
    'rel="noopener noreferrer" title="' + escHtml(s.source_name) +
    ' 就同一事件的另一条收录">' + escHtml(relDom(s.url)) + "</a>").join("");
  const relSrcCount = ev ? (ev.source_count || relGroups.length) : relGroups.length;
  /* 详情页译文交互（规范 2.4）：抽屉是深读场景，原文模式下也必须能拿到译文。
     三条入口：① 标题/摘要**悬停**出对照浮层（抽屉内同样可用，与卡片一致）
     ② 标题行右侧显式「译」按钮（触屏无悬停时的等价入口，点开即就地对照）
     ③ 抽屉头部语言三态，可把整页切成「对照 / 目标语」。
     译文按块与原文一一对应（标题一块、摘要一块），不做「标题+摘要拼成一段」，
     否则读者对不上号，会以为译文缺一截。 */
  const lead = drawerLeadHTML(it);
  const tail =
    (it.summary_compressed
      ? '<p class="drawer-note">※ 列表卡片展示压缩摘要（≤60 汉字），此处为摘要全文，未改动原意。</p>'
      : "") +
    '<div class="drawer-meta">' +
      '<span class="chip chip-src">' + flagSvg(it.country, 16) + escHtml(it.source_name) +
        '<i class="tier">' + escHtml(it.source_tier || "") + "</i></span>" +
      (it.importance === "头条" ? '<span class="badge-hot">头条</span>' : "") +
      (it.region === "china"
        ? '<span class="card-region">' + flagSvg("CN", 12) + "涉及中国</span>" : "") +
      verified +
    "</div>" +
    (ev && ev.canonical_item === it.id
      ? '<div class="drawer-hotbox">' +
        '<div class="dhb-top">' +
        '<button type="button" class="dhb-toggle" aria-expanded="false" ' +
        'aria-controls="dhbNote" title="展开说明：本条为什么只链一个信源">' +
        '<span class="dhb-badge">交叉热点 · ' + relSrcCount + " 信源</span>" +
        '<svg class="dhb-caret" viewBox="0 0 24 24" width="12" height="12" fill="none" ' +
        'stroke="currentColor" stroke-width="2" aria-hidden="true">' +
        '<path d="M6 9l6 6 6-6"/></svg></button>' +
        '<button type="button" class="dhb-jump" data-target="' +
        escHtml(ev.event_id) + '">回到上方热点条目</button></div>' +
        '<p class="dhb-note" id="dhbNote" hidden>本条是该交叉热点的<b>入档代表</b>：' +
        '同一事件有 ' +
        relSrcCount + " 个信源报道（共 " + rel.length + " 篇），按规范只入档一条" +
        "（其中权威度最高、发布最早者），所以卡片与「原文」链接指向的都是这一条" +
        "（" + escHtml(it.source_name || "") + "）。其余信源见下方「相关报道」，" +
        "每条都可各自打开原文。</p></div>"
      : "") +
    '<div class="drawer-section"><h4 data-ui="source">信源<i>SOURCE</i></h4>' +
      '<div class="kv"><span data-ui="country">来源国家/地区</span><b>' + flagSvg(it.country, 16) +
      escHtml(it.country_name || "未知") +
      (it.country ? " · " + escHtml(it.country) : "") + "</b></div>" +
      '<div class="kv"><span data-ui="tier">信源分层</span><b>' + escHtml(it.source_name || "") +
      " · " +
      escHtml(it.source_tier || "") + " " +
      escHtml(TIER_NAMES[it.source_tier] || "") + "</b></div>" +
      '<div class="kv"><span data-ui="authority">权威度</span><b>' + escHtml(it.authority) +
      "/10</b></div></div>" +
    '<div class="drawer-section"><h4 data-ui="time">时间<i>TIME</i></h4>' +
      '<div class="kv"><span data-ui="published">发布时间</span><b>' + escHtml(it.published_bj) +
      "</b></div>" +
      '<div class="kv"><span data-ui="timebasis">时间口径</span><b>' + escHtml(it.time_basis) +
      "</b></div></div>" +
    '<div class="drawer-section"><h4 data-ui="path">主线归属<i>PATH</i></h4>' +
      '<div class="kv"><span data-ui="node">所属环节</span><b>' +
      escHtml(meta.name || it.node_name || "") +
      (meta.en ? " · " + escHtml(meta.en) : "") + "</b></div>" +
      '<div class="kv"><span data-ui="subcat">子类</span><b>' + escHtml(it.subcategory || "") +
      "</b></div></div>" +
    '<div class="drawer-section"><h4 data-ui="labels">标签<i>LABELS</i></h4>' +
      '<div class="card-chips">' + tagsB + tagsC + "</div>" +
      '<p class="drawer-note">前置标签为内容属性（B 轨），后置为信源原始分类（C 轨，只读保留）。</p></div>' +
    (relGroups.length
      ? '<div class="drawer-section"><h4 data-ui="related">相关报道<i>RELATED · 同事件 ' +
        relSrcCount +
        " 个信源" + (rel.length > relSrcCount ? " · " + rel.length + " 篇报道" : "") +
        '</i></h4>' +
        '<ul class="rel-list">' + relGroups.map(g => {
          const s0 = g[0];
          const cname = relCountry(s0);
          return "<li>" + flagSvg(s0.country, 16) +
            '<a href="' + escHtml(s0.url) + '" target="_blank" rel="noopener noreferrer">' +
            escHtml(s0.source_name || "") + '</a>' + relMore(g) +
            '<span class="rel-auth">' + escHtml(cname ? cname + " · " : "") +
            "权威度 " + escHtml(s0.authority) + "</span></li>";
        }).join("") + "</ul></div>"
      : "") +
    '<div class="drawer-links">' +
      '<a class="btn btn-primary" href="' + escHtml(it.url) + '" target="_blank" rel="noopener noreferrer">' +
        "阅读原文" +
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17L17 7M9 7h8v8"/></svg></a>' +
      (it.mirror_url
        ? '<a class="btn btn-ghost" href="' + escHtml(it.mirror_url) + '" target="_blank" rel="noopener noreferrer">聚合镜像页</a>'
        : "") +
    "</div>";
  drawerLead = lead; drawerTail = tail;
  body.innerHTML = lead + tail;
  const crumb = $("#drawerCrumb");
  crumb.style.setProperty("--nc", "var(--accent-" + it.node + ")");
  crumb.innerHTML = "<b>" + escHtml(meta.name || it.node_name || "") + "</b>" +
    (meta.en ? "<i>" + escHtml(meta.en) + "</i>" : "") + " › " +
    escHtml(it.subcategory || "");
  drawer.hidden = false;
  requestAnimationFrame(() => { drawer.classList.add("open"); overlay.classList.add("open"); });
  updatePrevNext();
  $("#closeDrawer").focus();
}
function updatePrevNext(){
  const it = curData.items[curIdx];
  const list = it ? visibleCardsInNode(it.node) : [];
  const i = list.findIndex(c => c.dataset.id === (it || {}).id);
  $("#prevItem").disabled = i <= 0;
  $("#nextItem").disabled = i < 0 || i >= list.length - 1;
}
function stepDrawer(dir){
  const it = curData.items[curIdx];
  if (!it) return;
  const list = visibleCardsInNode(it.node);
  const i = list.findIndex(c => c.dataset.id === it.id);
  const nxt = list[i + dir];
  if (nxt) openDrawer(nxt.dataset.id);
}
function closeDrawer(){
  drawer.classList.remove("open"); overlay.classList.remove("open");
  setTimeout(() => { drawer.hidden = true; }, 250);
  if (lastFocus) lastFocus.focus();
  curIdx = -1; drawerItem = null; drBiOn = false;
}
body.addEventListener("click", e => {
  // 详情页译文入口：标题行右侧「译」按钮（触屏无悬停时的等价入口）
  const bb = e.target.closest ? e.target.closest("[data-dr-bi]") : null;
  if (bb){ drBiOn = !drBiOn; applyDrBi(); return; }
  const j = e.target.closest ? e.target.closest(".dhb-jump") : null;
  if (j){ const t = j.dataset.target; closeDrawer(); locateHot(t); return; }
  // 说明盒默认只占一行；点这一行（右侧跳转按钮除外）才展开下面的说明
  const tg = e.target.closest ? e.target.closest(".dhb-toggle") : null;
  if (tg){
    const open = tg.getAttribute("aria-expanded") === "true";
    tg.setAttribute("aria-expanded", String(!open));
    const note = $("#dhbNote", body);
    if (note) note.hidden = open;
  }
});
$("#closeDrawer").addEventListener("click", closeDrawer);
overlay.addEventListener("click", closeDrawer);
$("#prevItem").addEventListener("click", () => stepDrawer(-1));
$("#nextItem").addEventListener("click", () => stepDrawer(1));
$("#copyLink").addEventListener("click", async () => {
  const it = curData.items[curIdx];
  if (!it) return;
  try { await navigator.clipboard.writeText(it.url); showToast("原文链接已复制"); }
  catch (e) { showToast("复制失败，请手动复制"); }
});
let toastTimer = null;
function showToast(msg){
  const t = $("#toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}

/* ============ 键盘导航：j/k 移动、Enter 开、Esc 关、/ 搜索 ============ */
let kbIdx = -1;
function kbMove(dir){
  const vis = dayCards().filter(cardShown);
  if (!vis.length) return;
  kbIdx = (kbIdx + dir + vis.length) % vis.length;
  dayCards().forEach(c => c.classList.remove("kb-focus"));
  const c = vis[kbIdx];
  c.classList.add("kb-focus");
  safeIntoView(c, { block: "nearest", behavior: reduceMotion() ? "auto" : "smooth" });
  c.focus({ preventScroll: true });
}
document.addEventListener("keydown", e => {
  const tag = (e.target.tagName || "").toLowerCase();
  const typing = tag === "input" || tag === "textarea";
  // 命令面板：⌘K / Ctrl+K 开关；开关与方向键在任何时候都优先
  if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")){
    e.preventDefault();
    cmdk.hidden ? openCmd() : closeCmd();
    return;
  }
  if (!cmdk.hidden){
    if (e.key === "Escape"){ e.preventDefault(); closeCmd(); }
    else if (e.key === "ArrowDown"){ e.preventDefault(); moveCmd(1); }
    else if (e.key === "ArrowUp"){ e.preventDefault(); moveCmd(-1); }
    else if (e.key === "Enter"){ e.preventDefault(); if (cmdItems[cmdCursor]) { const a = cmdItems[cmdCursor]; closeCmd(); a.run(); } }
    return;
  }
  if (e.key === "Escape"){
    if (drawer.classList.contains("open")) closeDrawer();
    else if (!$("#npList").hidden || !$("#npDate").hidden || !$("#npRead").hidden) closePanels();
    else if (typing){ e.target.blur(); }
    return;
  }
  if (typing) return;
  if (e.key === "/"){ e.preventDefault(); searchInput.focus(); return; }
  // 阅读控制：Home / End 回顶回底；1–5 直接跳环节
  if (e.key === "Home"){
    e.preventDefault();
    safeScrollTo({ top: 0, behavior: reduceMotion() ? "auto" : "smooth" });
    return;
  }
  if (e.key === "End"){
    e.preventDefault();
    safeScrollTo({ top: document.documentElement.scrollHeight,
                   behavior: reduceMotion() ? "auto" : "smooth" });
    return;
  }
  if (/^[1-5]$/.test(e.key)){
    const n = curData ? curData.nodes[+e.key - 1] : null;
    if (n){ e.preventDefault(); scrollToNode(n.key); return; }
  }
  // 抽屉打开时：j/k 切换同节点上一条/下一条（规范第三篇 2.3 交互要求）
  if (drawer.classList.contains("open")){
    if (e.key === "j"){ e.preventDefault(); stepDrawer(1); }
    else if (e.key === "k"){ e.preventDefault(); stepDrawer(-1); }
    return;
  }
  if (e.key === "j" || e.key === "ArrowDown"){ e.preventDefault(); kbMove(1); }
  else if (e.key === "k" || e.key === "ArrowUp"){ e.preventDefault(); kbMove(-1); }
});

/* ============ 术语表与双语对照层 ============ */
const UI = UI_TEXT || {};
const uiZh = k => (UI[k] ? UI[k][0] : "");
const uiEn = k => (UI[k] ? UI[k][1] : "");
const MT_TAG = uiZh("mt") || "机器译文 · 未校对";
/* 触屏没有 hover —— 用「点按」代替悬停（不猜 UA，只看媒体特性） */
const IS_TOUCH = matchMedia("(hover: none)").matches;
if (IS_TOUCH) document.documentElement.classList.add("touch");

const biPop = $("#biPop");
let biTimer = null, biAnchor = null;
function hideBipop(){ clearTimeout(biTimer); biAnchor = null; biPop.hidden = true; }
function placeBipop(el){
  const r = el.getBoundingClientRect(), p = biPop.getBoundingClientRect(), M = 10, G = 10;
  const capW = innerWidth - p.width - M;
  let left = Math.min(Math.max(M, r.left), capW);
  let top = r.bottom + G;                                     // 默认放在下方
  if (top + p.height > innerHeight - M) top = r.top - p.height - G;   // 下方放不下 → 翻到上方
  // 详情页抽屉占右侧半屏：浮层优先向**左**展开，避免压住标题与右上动作键
  if (r.left > innerWidth * 0.5){
    const l = r.left - p.width - G;
    if (l >= M){ left = l; top = Math.min(Math.max(M, r.top), Math.max(M, innerHeight - p.height - M)); }
  }
  biPop.style.left = Math.max(M, left) + "px";
  biPop.style.top = Math.max(M, top) + "px";
}
/* 浮层内容：固定三行 —— ① 提示徽标 ② 标题 ③ 摘要（≤60 汉字）。
   方向随语言模式自动对调：原文 / 对照模式下给译文，目标语模式下给信源原文。 */
const SRC_ORIG = uiZh("srcorig") || "信源原文";
function biPayload(el){
  if (!el || !el.dataset) return null;
  const tgt = document.documentElement.dataset.langmode === "tgt";
  if (tgt && el.dataset.titleOrig)
    return { tag: SRC_ORIG, title: el.dataset.titleOrig,
             sum: el.dataset.summaryOrig || "", term: false };
  if (el.dataset.titleAlt)
    return { tag: MT_TAG, title: el.dataset.titleAlt,
             sum: el.dataset.summaryAlt || "", term: false };
  const k = el.dataset.ui;
  if (k && UI[k]) return { tag: null, title: "", sum: "", term: UI[k][1] };
  return null;
}
/* 延迟 400ms：鼠标扫过列表不该一路弹浮层；用 fixed 定位故不占文档流、不会引起跳动。
   抽屉打开时**同样允许**——详情页是深读场景，悬停标题/摘要必须能拿到译文。 */
document.addEventListener("mouseover", e => {
  if (IS_TOUCH || !cmdk.hidden) return;
  const el = e.target.closest ? e.target.closest("[data-title-alt],[data-ui]") : null;
  if (!el || el === biAnchor) return;
  const p = biPayload(el);
  if (!p || !(p.title || p.term)) return;
  biAnchor = el;
  clearTimeout(biTimer);
  biTimer = setTimeout(() => {
    biPop.innerHTML = (p.tag ? '<span class="bi-tag">' + escHtml(p.tag) + "</span>" : "") +
      (p.term ? '<span class="bi-term">' + escHtml(p.term) + "</span>" : "") +
      (p.title ? '<span class="bi-title">' + escHtml(p.title) + "</span>" : "") +
      (p.sum ? '<span class="bi-sum">' + escHtml(p.sum) + "</span>" : "");
    biPop.hidden = false;
    placeBipop(el);
  }, 400);
});
document.addEventListener("mouseout", e => {
  const el = e.target.closest ? e.target.closest("[data-title-alt],[data-ui]") : null;
  if (el && el === biAnchor) hideBipop();
});
window.addEventListener("scroll", hideBipop, { passive: true });

/* 卡片双语：按模式重排标题/摘要的 DOM。默认（原文）不插入任何节点——保持原布局 */
function cardLangHTML(zh, alt, cls, mode){
  const a = escHtml(zh || ""), b = escHtml(alt || "");
  if (!b) return a;
  if (mode === "tgt")                       // 目标语：译文明文在前，原文降权附后
    return '<span class="' + cls + '-alt">' + b + '</span><span class="' + cls + '-zh">' +
      a + "</span>";
  if (mode === "both")                      // 对照：原文为主，译文另起一行
    return '<span class="' + cls + '-zh">' + a + '</span><span class="' + cls + '-alt">' +
      b + "</span>";
  return a;
}
function titleTextNode(c){ return $(".ct-zh", c) || $(".card-title", c); }
function renderCardLang(){
  const mode = document.documentElement.dataset.langmode || "orig";
  dayCards().forEach(c => {
    const t = $(".card-title", c), s = $(".card-summary", c);
    if (t) t.innerHTML = cardLangHTML(c.dataset.title, c.dataset.titleAlt, "ct", mode);
    if (s) s.innerHTML = cardLangHTML(c.dataset.summary, c.dataset.summaryAlt, "cs", mode);
  });
}
/* 触屏「译」图标：点开就地展开译文（无 hover 时才出现） */
function injectBiTags(){
  if (!IS_TOUCH) return;
  dayCards().forEach(c => {
    if (!c.dataset.titleAlt || $(".card-bi", c)) return;
    const b = document.createElement("button");
    b.type = "button"; b.className = "card-bi"; b.dataset.hasAlt = "1";
    b.textContent = uiZh("translate");
    b.title = uiZh("translate") + "：" + c.dataset.titleAlt;
    $(".card-top", c).appendChild(b);
  });
}
function toggleCardAlt(card){
  const old = $(".card-alt", card);
  if (old){ old.remove(); return; }
  if (!card.dataset.titleAlt) return;
  const p = document.createElement("p");
  p.className = "card-alt";
  p.textContent = card.dataset.titleAlt +
    (card.dataset.summaryAlt ? "　" + card.dataset.summaryAlt : "");
  const s = $(".card-summary", card);
  if (s && s.parentNode) s.parentNode.insertBefore(p, s.nextSibling);
  else card.appendChild(p);
}
function setLangMode(mode, persist){
  document.documentElement.dataset.langmode = mode;
  $$("[data-lang-mode]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.langMode === mode)));
  if (persist) store.set("yuesheng-lang", mode);
  refreshText();
  refreshDrawerLang();          // 抽屉开着时同步重排（详情页与列表页同一语言模式）
}
$("#langSwitch").addEventListener("click", e => {
  const b = e.target.closest("[data-lang-mode]");
  if (b) setLangMode(b.dataset.langMode, true);
});
$("#drawerLang").addEventListener("click", e => {
  const b = e.target.closest("[data-lang-mode]");
  if (b) setLangMode(b.dataset.langMode, true);
});

/* ============ 渐进加载（取代「查看全部」） ============ */
/* 批次：桌面 20 条 / 移动 10 条——一屏约两行半，点「展开更多」后落点仍在视野内，
   不必重新找位置。 */
const stepSize = () => (innerWidth < 768 ? 10 : 20);
const INIT_SHOWN = 8;
function syncShown(){
  const active = filtersActive();
  daySections().forEach(sec => {
    const bar = $(".more-bar", sec);
    const limit = bar ? +bar.dataset.shown : Infinity;
    // 筛选/搜索时全部放开——「找得到」优先于「少渲染」
    $$(".card", sec).forEach(c => { c.hidden = active ? false : +(c.dataset.pidx || 0) >= limit; });
    if (bar) updateMoreBar(bar, active);
  });
}
function updateMoreBar(bar, active){
  const total = +bar.dataset.total, shown = Math.min(+bar.dataset.shown, total);
  active = active === undefined ? filtersActive() : active;
  const cnt = $(".mb-count", bar);
  if (cnt) cnt.innerHTML = uiZh("shown") + " <b>" + (active ? total : shown) + "</b> / " +
    uiZh("of") + " " + total + " " + uiZh("items");
  const more = $('[data-act="more"]', bar), less = $('[data-act="less"]', bar);
  if (more) more.hidden = active || shown >= total;
  if (less) less.hidden = active || shown <= INIT_SHOWN;
}
/* 展开：新卡片出现在按钮上方，**不需要滚动**（上方内容没动，视口自然不跳） */
function expandSection(sec){
  const bar = $(".more-bar", sec);
  if (!bar) return;
  bar.dataset.shown = Math.min(+bar.dataset.total, +bar.dataset.shown + stepSize());
  syncShown();
}
/* 收起：文档高度骤减会让视口失去参照 → 主动滚到该节节头，落在一个确定位置 */
function collapseSection(sec){
  const bar = $(".more-bar", sec);
  if (!bar) return;
  bar.dataset.shown = INIT_SHOWN;
  syncShown();
  safeIntoView(sec, { behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
}
/* 定位前的解隐藏：按批次把「已展开」补到覆盖这条卡片为止（不一次全展开） */
function ensureCardVisible(card){
  const sec = card && card.closest(".node");
  if (sec){
    const bar = $(".more-bar", sec);
    if (bar){
      const i = +(card.dataset.pidx || 0);
      if (i >= +bar.dataset.shown){
        let n = +bar.dataset.shown;
        while (n <= i) n += stepSize();
        bar.dataset.shown = Math.min(n, +bar.dataset.total);
      }
    }
  }
  if (card.style.display === "none") resetFilters();
  syncShown();
}

/* ============ 悬浮导航舱 ============ */
const navpod = $("#navpod"), npList = $("#npList"), npRing = $("#npRingBar");
const mprogBar = $("#mprog i"), topbarEl = document.querySelector(".topbar");
const RING_C = 2 * Math.PI * 19;
let scrollIdle = null, lastY = window.scrollY;
const scrollRatio = () => {
  const h = document.documentElement.scrollHeight - innerHeight;
  return h > 0 ? Math.min(1, Math.max(0, window.scrollY / h)) : 0;
};
function updateNavpod(){
  const p = scrollRatio();
  if (npRing) npRing.style.strokeDashoffset = (RING_C * (1 - p)).toFixed(2);
  if (mprogBar) mprogBar.style.width = (p * 100).toFixed(2) + "%";
}
function syncTopbarH(){
  const tucked = topbarEl.classList.contains("tuck");
  setH("--topbar-h", tucked ? 0 : topbarEl.getBoundingClientRect().height);
}
/* 吸顶偏移量写 CSS 变量：**不做整数取整**。
   取整会让下一层的 top 与上一层实际底边差最多 0.5px——层高52.4px 写成 52px 时，
   下方快捷栏就压在顶栏 0.4px 上。这类误差平时看不出来，但会让几何断言在
   「无缺陷」时报出亚像素 FAIL，久了就没人相信断言了。
   subpixel 只影响偏移量定位，不影响元素自身的边框清晰度，故可放心保留小数。 */
function setH(name, px){
  document.documentElement.style.setProperty(name, Math.round(px * 100) / 100 + "px");
}
/* 吸顶栈实测高度写入：快捷栏 → --axismini-h，筛选栏 → --filters-h。
   筛选栏的停靠位置 = 顶栏 + 快捷栏，两层必须紧贴、层间零缝隙。

   为什么必须实测而非写死常量：快捷栏与筛选栏的高度都随 --fs（字号三档）
   改变，任何写死的数值必然在某档字号下错位——这是历次叠字故障的直接来源。
   为什么快捷栏高度只能实测：它是 position:fixed，恒定占据顶栏下方一段，
   筛选栏的 top 必须落在它真实的下沿。

   两者都是「不可见即 0」：快捷栏窄屏 display:none、筛选栏窄屏 position:static，
   此时写 0，对应元素自动退回上一层的下沿，不会凭空留出空白。 */
function syncStickyHeights(){
  const mini = $(".axis-mini", dayEl) || $(".axis-mini");
  let mh = 0;
  if (mini && getComputedStyle(mini).display !== "none"){
    mh = mini.getBoundingClientRect().height;
  }
  setH("--axismini-h", mh);

  const el = $(".filters", dayEl) || $(".filters");
  let fh = 0;
  if (el && getComputedStyle(el).position === "sticky"){
    fh = el.getBoundingClientRect().height;
  }
  setH("--filters-h", fh);
}
/* 移动端：向下滚动把导航舱与顶栏收起，向上滚动立刻出现（阅读区域最大化） */
function updateTuck(){
  const y = window.scrollY, down = y > lastY + 6, mobile = innerWidth < 768;
  navpod.classList.toggle("tuck", mobile && down && y > 260);
  if (topbarEl.classList.contains("tuck") !== (mobile && down && y > 420)){
    topbarEl.classList.toggle("tuck", mobile && down && y > 420);
    syncTopbarH();
  }
  lastY = y;
}
window.addEventListener("scroll", () => {
  updateNavpod(); updateTuck();
  navpod.classList.remove("idle");
  clearTimeout(scrollIdle);
  // 面板开着时不降透明度——那会把日期、条数一起变淡，等于没法读
  scrollIdle = setTimeout(() => {
    if (allPanelsClosed()) navpod.classList.add("idle");
  }, 1200);                                                 // 停止滚动后降噪
}, { passive: true });
window.addEventListener("resize", () => {
  updateNavpod(); syncTopbarH(); syncStickyHeights();
  const open = Object.keys(PANELS).find(k => !$(PANELS[k]).hidden);   // 断点切换后重锚
  if (open) anchorPanel(open);
});
$("#npTop").addEventListener("click", () =>
  safeScrollTo({ top: 0, behavior: reduceMotion() ? "auto" : "smooth" }));
$("#npBottom").addEventListener("click", () =>
  safeScrollTo({ top: document.documentElement.scrollHeight,
                 behavior: reduceMotion() ? "auto" : "smooth" }));
function buildNodeList(){
  npList.innerHTML = (curData ? curData.nodes : []).map(n =>
    '<button type="button" class="np-item" role="menuitem" data-node="' + escHtml(n.key) +
    '" style="--nc:var(--accent-' + escHtml(n.key) + ')" aria-current="false">' +
    "<i></i>" + escHtml(n.name) + "<b>" + n.count + "</b></button>").join("");
  syncNodeList();
}
function syncNodeList(){
  const cur = currentSection();
  $$(".np-item", npList).forEach(b =>
    b.setAttribute("aria-current", String(b.dataset.node === cur)));
}
/* ============ 悬浮舱三面板（环节 / 日期 / 阅读设置）互斥 ============
   一次只让读者看一件事：打开一个就关掉另外两个，点导航舱外部全部收起。
   定位：**贴着各自的按钮弹出**（底边对齐按钮顶边），不是一律吊在整舱上方——
   吊在舱上方时面板底部离视口上沿太近，日期面板一行十几天，顶部那几行会看不全、点不到。
   打开时按视口实际余量收紧 max-height，保证第一行永远在视口内。
   日期面板只列**最近 10 天**——面板高度可控（桌面与移动端都不用滚），
   更早的日期走面板底部的输入框，或命令面板（⌘K）看全部。 */
const PANELS = { nodes: "#npList", dates: "#npDate", read: "#npRead" };
const PANEL_BTN = { nodes: "#npNodes", dates: "#npDates", read: "#npReadBtn" };
const NP_DATE_MAX = 10;
function togglePanel(which, force){
  const want = force === undefined ? $(PANELS[which]).hidden : force;
  Object.keys(PANELS).forEach(k => {
    const open = (k === which) && want;
    $(PANELS[k]).hidden = !open;
    const b = $(PANEL_BTN[k]);
    if (b) b.setAttribute("aria-expanded", String(open));
  });
  // 触屏没有 hover，面板打开期间必须保持满不透明度，否则内容读不清
  if (want) navpod.classList.remove("idle");
  if (!want) return;
  anchorPanel(which);
  if (which === "nodes") buildNodeList();
  if (which === "dates") buildDateList();
  if (which === "read") syncReadPanel();
}
/* 面板贴按钮定位：底边 = 按钮顶边 + 8px（bottom 是**相对 navpod** 的距离，
   navpod 自身 fixed 在右下，故 `navR.bottom - b.bottom + b.height + GAP` 正好换算过去）；
   水平同理要换算成相对 navpod 的 left——直接用视口坐标会把面板推到屏幕外。
   打开时按视口实际余量收紧 max-height，保证第一行永远在视口内。 */
function anchorPanel(which){
  const panel = $(PANELS[which]), btn = $(PANEL_BTN[which]);
  if (!panel || !btn) return;
  const navR = navpod.getBoundingClientRect(), b = btn.getBoundingClientRect();
  const M = 10, GAP = 8;
  panel.style.bottom = (navR.bottom - b.bottom + b.height + GAP) + "px";
  panel.style.right = "auto";
  panel.style.left = "0px";                       // 先归零再量宽，避免沿用旧 left
  const w = panel.offsetWidth || (innerWidth < 768 ? 320 : 238);
  const hostLeft = navR.left;
  let left;                                        // 相对 navpod 左缘
  if (innerWidth < 768){
    left = (navR.width - w) / 2;                  // 移动端底栏：面板与舱同轴居中（在按钮条上方）
  } else {
    // 桌面竖排按钮：**右缘对齐按钮左缘**（向左展开）。若对齐按钮右缘，面板会盖住
    // 该按钮下方的回底 / 环节 / Aa / 命令面板四个按钮——真机截图才发现的。
    left = (b.left - hostLeft) - w;
    if (hostLeft + left < M) left = 0;            // 会出左视口 → 改贴 navpod 左缘
  }
  const lo = M - hostLeft, hi = innerWidth - M - w - hostLeft;
  panel.style.left = Math.max(lo, Math.min(left, Math.max(lo, hi))) + "px";
  const room = Math.round(b.top - GAP - M);
  panel.style.maxHeight = Math.max(200, Math.min(room, innerHeight - 120)) + "px";
}
function closePanels(){ togglePanel("nodes", false); togglePanel("dates", false);
  togglePanel("read", false); }
function allPanelsClosed(){
  return $("#npList").hidden && $("#npDate").hidden && $("#npRead").hidden;
}
/* 视图切换后：开着哪个面板就刷新哪个（环节高亮 / 日期列表 / 选中态） */
function refreshPanels(){
  if (!$("#npList").hidden){ buildNodeList(); syncNodeList(); }
  if (!$("#npDate").hidden) buildDateList();
  if (!$("#npRead").hidden) syncReadPanel();
}
function buildDateList(){
  const win = String(DATA.window || 24);
  const recent = (DATES || []).slice(-NP_DATE_MAX).reverse();
  $("#npDateRows").innerHTML = recent.map(d => {
    const di = dateInfo(d);
    const n = (COUNTS[d] && COUNTS[d][win] != null) ? COUNTS[d][win] : 0;
    const cls = "np-date" + (d === DATA.current ? "" : "") +
      (d === LATEST ? " is-latest" : "");
    return '<button type="button" class="' + cls + '" role="menuitem" data-date="' + d + '"' +
      ' aria-current="' + (d === DATA.current ? "true" : "false") + '">' +
      "<i></i>" + escHtml(di.md) + "<small>" + escHtml(di.weekday) + "</small>" +
      "<b>" + n + "</b></button>";
  }).join("") || '<p class="np-hint">暂无日期数据</p>';
}
/* 指定日期输入：接受 YYYY-MM-DD / YYYY/M/D / YYYY.MM.DD / YYYYMMDD，
   边输边校验并给出可执行的下一步（格式错 → 说清格式；无数据 → 说清范围；有效 → 报条数）。 */
function normDateInput(s){
  const t = (s || "").trim().replace(/[./]/g, "-").replace(/\\s+/g, "");
  let m = /^(\\d{4})-(\\d{1,2})-(\\d{1,2})$/.exec(t);
  if (!m) m = /^(\\d{4})(\\d{2})(\\d{2})$/.exec(t);
  if (!m) return null;
  const y = +m[1], mo = +m[2], da = +m[3];
  if (mo < 1 || mo > 12 || da < 1 || da > 31) return null;
  const ds = y + "-" + pad2(mo) + "-" + pad2(da);
  const dt = new Date(y, mo - 1, da);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== da) return null;
  return ds;
}
function checkDateInput(){
  const hint = $("#npDateHint"), raw = $("#npDateInput").value.trim();
  hint.classList.remove("is-bad", "is-ok");
  if (!raw){
    hint.textContent = uiZh("dateph");
    return null;
  }
  const ds = normDateInput(raw);
  if (!ds){
    hint.textContent = uiZh("datebad");
    hint.classList.add("is-bad");
    return null;
  }
  const win = String(DATA.window || 24);
  const n = COUNTS[ds] ? COUNTS[ds][win] : null;
  if (n == null){
    hint.textContent = uiZh("datenone") + "（" + uiZh("daterange") + " " +
      ((DATES && DATES[0]) || "—") + " ~ " + ((DATES && DATES[DATES.length - 1]) || "—") + "）";
    hint.classList.add("is-bad");
    return null;
  }
  hint.textContent = dateInfo(ds).md + " " + dateInfo(ds).weekday + " · " + win + "H " +
    n + " 条 · " + uiZh("dateok");
  hint.classList.add("is-ok");
  return ds;
}
$("#npDates").addEventListener("click", e => {
  e.stopPropagation(); togglePanel("dates");
});
$("#npReadBtn").addEventListener("click", e => {
  e.stopPropagation(); togglePanel("read");
});
$("#npDateRows").addEventListener("click", e => {
  const b = e.target.closest(".np-date");
  if (!b) return;
  closePanels();
  switchDate(b.dataset.date);
});
$("#npDateInput").addEventListener("input", checkDateInput);
$("#npDateInput").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  const ds = checkDateInput();
  if (!ds) return;
  closePanels();
  switchDate(ds);
});
$("#npFs").addEventListener("click", e => {
  const b = e.target.closest("[data-fs]");
  if (b) setFontScale(b.dataset.fs);
});
$("#npDensity").addEventListener("click", e => {
  const b = e.target.closest("[data-dense]");
  if (b) setDensity(b.dataset.dense === "1");
});
/* 阅读设置面板的选中态跟随真实设置（也随其它入口改变而更新） */
function syncReadPanel(){
  const fs = document.documentElement.style.getPropertyValue("--fs").trim() || "1";
  $$("#npFs [data-fs]").forEach(b =>
    b.setAttribute("aria-pressed", String(Math.abs(+b.dataset.fs - +fs) < 0.001)));
  const dense = $$(".grid", dayEl).some(g => g.classList.contains("dense"));
  $$("#npDensity [data-dense]").forEach(b =>
    b.setAttribute("aria-pressed", String((b.dataset.dense === "1") === dense)));
}
$("#npNodes").addEventListener("click", e => { e.stopPropagation(); togglePanel("nodes"); });
$("#npCmd").addEventListener("click", () => openCmd());
npList.addEventListener("click", e => {
  const b = e.target.closest(".np-item");
  if (!b) return;
  closePanels(); scrollToNode(b.dataset.node);
});
document.addEventListener("click", e => {
  if (!(e.target.closest && e.target.closest("#navpod"))) closePanels();
});

/* ============ 命令面板（⌘K / Ctrl+K） ============ */
const cmdk = $("#cmdk"), cmdkInput = $("#cmdkInput"), cmdkList = $("#cmdkList");
let cmdCursor = 0, cmdItems = [];
function cmdActions(){
  const a = [];
  const push = (g, label, em, run, node) => a.push({ g: g, label: label, em: em, run: run, node: node });
  push("导航", uiZh("totop") + " · " + uiEn("totop"), "Home",
    () => safeScrollTo({ top: 0, behavior: "smooth" }));
  push("导航", uiZh("tobottom") + " · " + uiEn("tobottom"), "End",
    () => safeScrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" }));
  (curData ? curData.nodes : []).forEach(n =>
    push("环节", n.name + " · " + n.en, n.count + " 条", () => scrollToNode(n.key), n.key));
  push("窗口", "24H · 当日", "", () => switchView(DATA.current, 24));
  push("窗口", "48H · 前日 + 当日", "", () => switchView(DATA.current, 48));
  ["dark", "light", "auto"].forEach(m =>
    push("主题", uiZh(m) + " · " + uiEn(m), "", () => applyTheme(m, true)));
  ["orig", "both", "tgt"].forEach(m =>
    push("语言", uiZh(m === "orig" ? "origmode" : (m === "both" ? "bothmode" : "tgtmode")),
      "", () => setLangMode(m, true)));
  push("操作", uiZh("export") + " · " + uiEn("export"), "", copyDigest);
  push("操作", "复制当前视图链接", "", copyDeepLink);
  // 可读性：与悬浮舱「阅读设置」面板同一入口、同一状态（当前档位标「当前」）
  const denseOn = $$(".grid", dayEl).some(g => g.classList.contains("dense"));
  push("操作", uiZh("density") + "：" + uiZh("normal"), denseOn ? "" : "当前",
    () => setDensity(false));
  push("操作", uiZh("density") + "：" + uiZh("compact"), denseOn ? "当前" : "",
    () => setDensity(true));
  const fsCur = (document.documentElement.style.getPropertyValue("--fs").trim() || "1");
  ["1", "1.08", "1.16"].forEach((v, i) =>
    push("操作", uiZh("fontsize") + "：" + [uiZh("std"), uiZh("big"), uiZh("xbig")][i],
      Math.abs(+v - +fsCur) < 0.001 ? "当前" : "", () => setFontScale(v)));
  (DATES || []).slice().reverse().forEach(d =>
    push("日期", dateInfo(d).md + " · " + dateInfo(d).full,
      (COUNTS[d] ? COUNTS[d][String(DATA.window || 24)] + " 条" : ""),
      () => switchDate(d)));
  return a;
}
function renderCmd(){
  const q = cmdkInput.value.trim().toLowerCase();
  let acts = cmdActions();
  if (q){
    acts = acts.filter(x =>
      (x.label + " " + (x.em || "") + " " + x.g).toLowerCase().includes(q));
    (curData ? curData.items : [])
      .filter(it => ((it.title || "") + " " + (it.summary || "")).toLowerCase().includes(q))
      .slice(0, 8)
      .forEach(it => acts.push({ g: "资讯", label: it.title,
        em: (it.node_name || "") + " · " + it.num, node: it.node,
        run: () => locateCard(it.id) }));
  }
  cmdItems = acts;
  if (cmdCursor >= acts.length) cmdCursor = 0;
  if (!acts.length){
    cmdkList.innerHTML = '<p class="cmdk-empty">没有匹配的命令</p>';
    return;
  }
  let html = "", lastG = null;
  acts.forEach((x, i) => {
    if (x.g !== lastG){
      html += '<div class="cmdk-group">' + escHtml(x.g) + "</div>";
      lastG = x.g;
    }
    html += '<button type="button" class="cmdk-item' + (i === cmdCursor ? " is-cursor" : "") +
      '" data-i="' + i + '" role="option"' +
      (x.node ? ' style="--nc:var(--accent-' + escHtml(x.node) + ')"' : "") +
      "><i></i>" + escHtml(x.label) +
      (x.em ? "<em>" + escHtml(x.em) + "</em>" : "") + "</button>";
  });
  cmdkList.innerHTML = html;
}
function openCmd(){
  cmdk.hidden = false; cmdkInput.value = ""; cmdCursor = 0; renderCmd();
  cmdkInput.focus();
}
function closeCmd(){ cmdk.hidden = true; cmdkInput.blur(); hideBipop(); }
function moveCmd(d){
  if (!cmdItems.length) return;
  cmdCursor = (cmdCursor + d + cmdItems.length) % cmdItems.length;
  renderCmd();
  const el = $('.cmdk-item.is-cursor', cmdkList);
  if (el) el.scrollIntoView({ block: "nearest" });
}
cmdkInput.addEventListener("input", () => { cmdCursor = 0; renderCmd(); });
cmdkList.addEventListener("click", e => {
  const b = e.target.closest(".cmdk-item");
  if (!b) return;
  const i = +b.dataset.i;
  closeCmd();
  if (cmdItems[i]) cmdItems[i].run();
});
cmdk.addEventListener("mousedown", e => { if (e.target === cmdk) closeCmd(); });

/* ============ 深链 / 导出 / 阅读位置 / 可读性 ============ */
function writeHash(){
  if (!DATA.current) return;
  const h = "#/" + DATA.current + "/" + DATA.window + "h";
  if (location.hash === h) return;
  // history.replaceState 在部分环境（file:// 不透明源等）会直接抛 SecurityError，
  // 抛在顶层会让后续渲染中断 —— 深链只是锦上添花，失败就退回直接改 hash。
  try { history.replaceState(null, "", h); }
  catch (e) { try { location.hash = h; } catch (e2) { /* 都不行就算了 */ } }
}
function readHash(){
  const m = /^#\\/(\\d{4}-\\d{2}-\\d{2})\\/(24|48)h$/.exec(location.hash || "");
  return m ? { d: m[1], w: +m[2] } : null;
}
function copyDeepLink(){
  const url = location.href.split("#")[0] + "#/" + DATA.current + "/" + DATA.window + "h";
  copyText(url, "当前视图链接已复制");
}
function copyDigest(){
  if (!curData) return;
  const lines = ["# 月生 · AI 资讯日报 " + DATA.current + "（" + DATA.window + "H）", ""];
  NODE_ORDER.forEach(k => {
    const items = (curData.items || []).filter(it => it.node === k);
    if (!items.length) return;
    lines.push("## " + (NODE_META[k] ? NODE_META[k].name : k) + "（" + items.length + " 条）", "");
    items.forEach(it => lines.push("- " + it.title + "（" + it.source_name +
      "，权威度 " + (it.authority || "?") + "/10）" + (it.url ? "  " + it.url : "")));
    lines.push("");
  });
  copyText(lines.join("\\n"), "今日清单已复制（Markdown）");
}
function copyText(text, okMsg){
  const done = () => showToast(okMsg);
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done,
      () => fallbackCopy(text) ? done() : showToast("复制失败，请手动复制"));
  } else {
    showToast(fallbackCopy(text) ? okMsg : "复制失败，请手动复制");
  }
}
function fallbackCopy(text){
  try {
    const t = document.createElement("textarea");
    t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(t);
    return ok;
  } catch (e){ return false; }
}
/* 密度：紧凑档把标题与摘要各压到 2 行、隐藏标签行、收紧卡内间距，
   同一屏大约多看三分之一条目（原先只收 gap 与内边距，几乎看不出差别）。 */
function setDensity(dense, silent){
  $$(".grid", dayEl).forEach(g => g.classList.toggle("dense", dense));
  store.set("yuesheng-dense", dense ? "1" : "0");
  syncReadPanel();
  if (!silent)
    showToast(dense ? "已切换到紧凑密度（同屏条目更多）" : "已切换到标准密度");
}
/* 字号：正文、卡片标题/摘要、抽屉正文与译文都乘同一比例尺（--fs），
   以前只有 body 生效、其余写死 px，等于开关无感。 */
function setFontScale(v){
  document.documentElement.style.setProperty("--fs", v);
  store.set("yuesheng-fs", v);
  syncTopbarH(); syncStickyHeights();    // 字号改变筛选栏高度 → 重算节头吸顶位置
  syncReadPanel();
}
/* 阅读位置：重访时提示「继续上次」——只在同日同窗口、且滚动过一定距离时提示 */
const RESUME_KEY = "yuesheng-read";
function currentSection(){
  let cur = null;
  daySections().forEach(s => {
    const r = s.getBoundingClientRect();
    if (r.top <= innerHeight * 0.35) cur = s.dataset.node;
  });
  return cur || (daySections()[0] || {}).dataset.node || null;
}
let readTimer = null;
window.addEventListener("scroll", () => {
  clearTimeout(readTimer);
  readTimer = setTimeout(() => {
    if (!DATA.current) return;
    try {
      store.set(RESUME_KEY, JSON.stringify({ d: DATA.current, w: DATA.window,
        y: Math.round(window.scrollY), node: currentSection() }));
    } catch (e){ /* 存不下就本次不记 */ }
  }, 800);
}, { passive: true });
const resumeBar = $("#resume");
function checkResume(){
  const raw = store.get(RESUME_KEY);
  if (!raw) return;
  let p = null;
  try { p = JSON.parse(raw); } catch (e){ return; }
  if (!p || p.d !== DATA.current || p.w !== DATA.window || !(p.y > 1200)) return;
  const nm = p.node && NODE_META[p.node] ? NODE_META[p.node].name : "—";
  $("#resumeNode").textContent = nm;
  resumeBar.hidden = false;
  requestAnimationFrame(() => resumeBar.classList.add("show"));
  $("#resumeGo").onclick = () => {
    hideResume();
    safeScrollTo({ top: p.y, behavior: reduceMotion() ? "auto" : "smooth" });
  };
}
function hideResume(){
  resumeBar.classList.remove("show");
  setTimeout(() => { resumeBar.hidden = true; }, 220);
}
$("#resumeX").addEventListener("click", hideResume);

/* 骨架屏：运行态切换日期取数时占位，避免「空白 → 内容」的高度跳变 */
function renderSkeleton(){
  let cards = "";
  for (let i = 0; i < 6; i++) cards += '<div class="skel-card"></div>';
  dayEl.innerHTML = '<div class="skel"><div class="skel-h"></div><div class="skel-row">' +
    cards + "</div></div>";
}

/* ============ 初始化：读索引 → 渲染首屏（数据源不可读时用内联兜底） ============ */
function showNotice(msg){
  const el = $("#srcNotice");
  el.textContent = msg;
  el.hidden = false;
}
/* 运行态取不到数据时的提示：说清「为什么不可用」与「怎么办」，
   避免被误读成页面没做完（降级是设计行为，不是构建缺陷）。 */
function runtimeNotice(){
  const snap = "已显示内联首屏快照（" + DATA.current + "）。";
  const tail = "如需浏览全部日期，请改用离线单文件版《ai_news_daily.html》"
    + "（数据全部内联，双击即可打开）。";
  if (IS_FILE)
    return "本页以本地文件方式打开（file://）：浏览器安全策略禁止页面读取同目录的数据文件，"
      + snap + tail;
  return "未能读到 数据/视图/（本页与数据目录的相对位置不符，或未通过 HTTP 访问），"
    + snap + tail;
}
(async function boot(){
  try {
    INDEX = await loadIndex();
  } catch (e){
    INDEX = VIEW_SRC.index || null;
    FALLBACK = true;
  }
  if (!INDEX){
    showNotice("数据源不可读，且本页无内联兜底数据——请检查 数据/视图/ 或重新构建页面。");
    return;
  }
  applyIndex();
  renderCal();
  renderDateBtnShell();
  // 深链优先：#/2026-10-14/48h 直接落到那一天那个窗口（便于把某一天分享出去）
  const hp = readHash();
  const start = (hp && COUNTS[hp.d] && COUNTS[hp.d][String(hp.w)] != null)
    ? hp : { d: DATA.current, w: DATA.window };
  await switchView(start.d, start.w);
  syncWindows(DATA.window);
  // 可读性偏好（与主题一样：不可持久化时仅本次生效）；silent：启动恢复不弹提示
  if (store.get("yuesheng-dense") === "1") setDensity(true, true);
  const fs = store.get("yuesheng-fs");
  if (fs) setFontScale(fs);
  setLangMode(store.get("yuesheng-lang") || "orig", false);
  syncTopbarH(); syncStickyHeights();
  booted = true;
  checkResume();
  if (VIEW_SRC.mode === "runtime" && (IS_FILE || FALLBACK)) showNotice(runtimeNotice());
})();
/* 首屏渲染前先把顶栏日期按钮填上（避免短暂空值） */
function renderDateBtnShell(){
  updateDateBtn(DATA.current);
  syncWindows(DATA.window);
}
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="L3 装配器：外壳 + 数据载荷 → 页面")
    ap.add_argument("--mode", choices=("offline", "runtime"), default="offline",
                    help="offline=自包含单文件（内联全部投影）；"
                         "runtime=运行态薄壳（按需 fetch 投影）")
    ap.add_argument("--out", help="输出目录，默认 仪表盘/")
    ap.add_argument("--name", help="输出文件名，默认离线/运行态各自的固定名"
                                  "（发布包用 index.html）")
    args = ap.parse_args()

    idx_path = VIEW_ROOT / "index.json"
    if not idx_path.exists():
        raise SystemExit("缺少 %s —— 先运行 view_projection.py" % idx_path)
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    days = sorted((index.get("days") or {}).keys())
    if not days:
        raise SystemExit("投影索引为空：%s" % idx_path)

    # 数据载荷：离线＝全部日期 × 双窗口；运行态＝最近完整日的 24h（首屏兜底）
    # 兜底**不剥任何字段**（含 summary_full_alt）：数据源不可读时正是最需要能读的场合，
    # 为压体积删内容属于牺牲体验。体积目标见规范第三篇 S4（观测指标，非硬约束）。
    views = {}
    for d in days:
        wins = index["days"][d].get("windows") or {}
        for w in ("24", "48"):
            if not wins.get(w):
                continue
            if args.mode == "runtime" and not (d == index.get("latest") and w == "24"):
                continue
            f = VIEW_ROOT / ("%s_%sh.json" % (d, w))
            if not f.exists():
                raise SystemExit("缺少投影 %s —— 先运行 view_projection.py" % f.name)
            v = json.loads(f.read_text(encoding="utf-8"))
            views["%s_%sh" % (d, w)] = v

    src = {"mode": args.mode, "base": "../数据/视图/",
           "index": index, "views": views}
    payload = json.dumps(src, ensure_ascii=False,
                         separators=(",", ":")).replace("</", "<\\/")

    assets_path = Path(__file__).resolve().parent / "assets" / "render_runtime.js"
    if not assets_path.exists():
        raise SystemExit("缺少渲染打包件 %s —— 先运行 gen_runtime_assets.py" % assets_path)
    # 产物 = 前端资产 + 前端渲染纯函数（页面与 Node 侧共用同一份实现）
    runtime_assets = assets_path.read_text(encoding="utf-8")

    latest = index.get("latest") or days[-1]
    lw = (index["days"][latest].get("windows") or {})
    dt = datetime.strptime(latest, "%Y-%m-%d")
    html = HTML_TEMPLATE
    html = html.replace("@@RUNTIME_ASSETS@@", runtime_assets)
    html = html.replace("@@VIEW_SRC_JSON@@", payload)
    html = html.replace("@@MD@@", "%02d.%02d" % (dt.month, dt.day))
    html = html.replace("@@DATE_FULL@@", "%d 年 %d 月 %d 日 %s"
                        % (dt.year, dt.month, dt.day, WEEKDAYS[dt.weekday()]))
    html = html.replace("@@C24@@", str((lw.get("24") or {}).get("filed", 0)))
    html = html.replace("@@C48@@", str((lw.get("48") or {}).get("filed", 0)))

    out_dir = Path(args.out) if args.out else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or ("ai_news_daily.html" if args.mode == "offline"
                         else "runtime_shell.html")
    path = out_dir / name
    # 显式 LF 落地：Windows 下 write_text 会把 \n 转成 \r\n，
    # 产物换行不稳会让「基于 \n 的样式/结构校验」与逐字节比对失真。
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    print("== L3 页面已装配（%s · %d 天 · 内联投影 %d 份）=="
          % (args.mode, len(days), len(views)))
    print("输出：%s（%.1f KB）" % (path, path.stat().st_size / 1024))
    print("首屏默认：%s（最近完整自然日）· 渲染由前端纯函数完成，数据来自 数据/视图/"
          % latest)
    for d in days:
        w = (index["days"][d].get("windows") or {})
        print("  %s  %s 24h %-4s / 48h %-4s"
              % (d, "进行中" if index["days"][d].get("live") else "完整  ",
                 (w.get("24") or {}).get("filed", "—"),
                 (w.get("48") or {}).get("filed", "—")))

    if args.mode == "runtime":
        print("提示：运行态薄壳需经 HTTP 访问——浏览器禁止 file:// 页面读取本地 JSON。")
        print("      在项目根目录执行：python -m http.server 8765")
        print("      再访问：http://127.0.0.1:8765/仪表盘/runtime_shell.html")
        print("      页面会依次探测 ../数据/视图/、数据/视图/、./数据/视图/、/数据/视图/ 作为数据根；"
              "均不可达时自动降级为内联首屏快照并在页首说明原因。")


if __name__ == "__main__":
    main()
