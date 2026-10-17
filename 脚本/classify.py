#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify.py — 资讯分类器：快照 → 打标去重 → 日报数据集

输入：数据/快照/<日期>/*.json（fetch_sources.py 产出）+ 信源注册表/sources.json

处理链：
  - 归一化：时间统一北京时间人话格式；标题不改写；摘要压缩至 ≤60 汉字
  - 时间窗：数据集窗口 = 资讯发布自然日的整日（北京时间）；界面 48h 视图由前端
    合并相邻两个自然日，合并口径在 L2 投影层实现
  - A 轨主线分类：AI产业化价值链五节点（能力/产品/产业/治理/趋势）唯一归属 + 子类，
    规则分类器（信源先验 + 关键词加权），输出置信度
  - B 轨属性标签：封闭词表 14 个（发布/更新/融资/政策/论文/教程/观点/事故/榜单/
    开源/降价/合作/人事/数据）
  - C 轨来源标签：信源原始分类只读透传
  - D 轨地域分区：全球 / 中国（信源属性 + 中文内容 + 中国实体识别）；
    另记录来源国家/地区码（ISO 3166-1 alpha-2），用于国旗区分
  - 去重与事件合并：规范化 URL + 标题相似度判重，合并为 Event 保留信源计数
  - 置信度分流：≥0.8 入档；0.6–0.8 人工裁决队列；<0.6 待归类池
  - 重要度三级：头条 / 重要 / 一般
  - 结构性噪声闸门：无 AI 主体内容的模板化条目显式排除，保留可追溯

输出：
    数据/日报/<日期>.json            日报数据集（页面数据源）
    数据/日报/<日期>_分类质检报告.md  质检报告

用法：
  python classify.py                    # 处理今日快照
  python classify.py --date 2026-10-13  # 处理指定日期快照
  python classify.py --only aihot       # 只处理指定信源快照

依赖：仅 Python 标准库。
"""
import argparse
import difflib
import html as html_mod
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REGISTRY_PATH = BASE / "信源注册表" / "sources.json"
SNAPSHOT_ROOT = BASE / "数据" / "快照"
BACKFILL_ROOT = BASE / "数据" / "回溯"
DAILY_ROOT = BASE / "数据" / "日报"
BJ = timezone(timedelta(hours=8))
SPEC_VERSION = "AIIS-01 v1.19"

# 规范 4.1：B 轨封闭词表
B_VOCAB = ["发布", "更新", "融资", "政策", "论文", "教程", "观点",
           "事故", "榜单", "开源", "降价", "合作", "人事", "数据"]

NODES = ["capability", "product", "industry", "governance", "frontier"]
NODE_NAMES = {"capability": "能力", "product": "产品", "industry": "产业",
              "governance": "治理", "frontier": "趋势"}

# D 轨国家/地区码（ISO 3166-1 alpha-2，EU=欧盟）：来源国旗区分 + 后续跨域汇总。
# 与 sources.json 的 country 字段一一对应；新增信源时在此补中文名。
COUNTRY_NAMES = {
    "CN": "中国", "US": "美国", "GB": "英国", "FR": "法国", "DE": "德国",
    "EU": "欧盟", "JP": "日本", "KR": "韩国", "CH": "瑞士", "CA": "加拿大",
    "AU": "澳大利亚", "IL": "以色列", "IN": "印度", "SG": "新加坡",
    "NL": "荷兰", "SE": "瑞典", "RU": "俄罗斯", "UA": "乌克兰",
    "IT": "意大利", "ES": "西班牙", "FI": "芬兰", "NO": "挪威",
    "DK": "丹麦", "BR": "巴西",
}

SUBCATS = {
    "capability": ["前沿模型发布", "算法与训练方法", "评测与基准", "算力与基础设施"],
    "product": ["新产品与新功能", "迭代与修复", "开源项目与工具链", "垂直行业落地"],
    "industry": ["投融资与财报", "并购与合作", "市场格局与竞争", "组织与人事"],
    "governance": ["政策法规与监管", "安全与风险事件", "版权与判例", "伦理与社会影响"],
    "frontier": ["具身智能与机器人", "多模态与AIGC", "Agent与自动化", "新兴方向与前瞻观点"],
}

# ---------------------------------------------------------------- 关键词表
# (关键词, 权重)；命中即累加。中英文混合。
# 说明：
# - 中文关键词按子串匹配；纯 ASCII 关键词编译为词边界正则，避免子串误配
#   （ban→Bankruptcy、repo→reportedly、app→happy 等）
# - 模型/公司实体名权重压到 0.6：标题提到模型名≠主题就是模型（如「卡兹克看 AI 趋势」）
CAP_KW = [
    ("open weight", 3), ("open weights", 3), ("weights released", 3), ("open-source model", 3),
    # 单词 "weights"：权重开源是能力层明确信号，缺它会让「Meta releases Llama 4
    # weights」被平台主体先验抢到产品层（实证）。已由 open/weights released 覆盖
    # 的复合词条在编译阶段按单数优先去重，不会重复计分。
    ("weights", 2.5),
    ("open source model", 3), ("model release", 3), ("releases", 1.5), ("launch", 1.2),
    ("launches", 1.5), ("unveil", 2), ("announcing", 1.2), ("introducing", 1.2),
    ("frontier model", 3), ("large language model", 2), ("language model", 1.8),
    ("benchmark", 2.5), ("leaderboard", 2.5), ("state-of-the-art", 2.5), ("sota", 2.5),
    ("arena", 2), ("evaluation", 1.5), ("eval", 1.2),
    ("training", 2), ("pretrain", 2.5), ("pre-train", 2.5), ("fine-tun", 2), ("distill", 2),
    ("quantiz", 2), ("scaling law", 2.5), ("architecture", 1), ("transformer", 1.5),
    ("mixture-of-experts", 2.5), ("context window", 2),
    ("decision model", 1.5),
    ("gpu", 2.5), ("chip", 2), ("tpu", 2.5), ("cuda", 2.5), ("data center", 2),
    ("datacenter", 2), ("compute cluster", 2.5),
    ("arxiv", 1.5), ("preprint", 1.5), ("dataset", 1), ("corpus", 1),
    ("video model", 3), ("image model", 3), ("diffusion", 2),
    ("introduce", 2.0), ("trained", 2.5), ("pretrained", 2.5),
    ("outperform", 2.0), ("surpass", 2.0), ("beats", 1.2), ("study", 1.0),
    ("studies", 1.0),
    ("gpt-", 0.6), ("claude", 0.6), ("gemini", 0.6), ("llama", 0.6), ("qwen", 0.6),
    ("mistral", 0.6), ("deepseek", 0.6), ("grok", 0.6), ("opus", 0.6), ("sonnet", 0.6),
    ("haiku", 0.6),
    ("模型", 2.5), ("开源", 1.5), ("权重", 3), ("训练", 2), ("推理", 1.5), ("评测", 2.5),
    ("基准", 2.5), ("榜单", 2), ("算力", 2.5), ("芯片", 2.5), ("上下文", 2), ("蒸馏", 2),
    ("量化", 1.5), ("论文", 1.5), ("多模态", 1.2),
]
PROD_KW = [
    ("feature", 2.5), ("features", 2.5), ("rollout", 2), ("rolling out", 2), ("rolls out", 2),
    ("integration", 2), ("integrates", 2), ("plugin", 2), ("extension", 2), ("add-on", 2),
    ("sdk", 2), ("tool", 2), ("tooling", 2), ("cli", 2), ("gui", 2), ("editor", 1.5),
    ("ide", 1.8), ("vscode", 2.5), ("vs code", 2.5), ("cursor", 1.8),
    ("copilot", 2), ("assistant", 1.5), ("chatbot", 2), ("agent framework", 2.5),
    ("framework", 1.5), ("library", 1.5), ("repository", 1.5), ("repo", 1.2),
    ("open-source project", 2), ("open source project", 2),
    ("generally available", 2), ("now available", 2), ("now supports", 2.5), ("available in", 1.5),
    ("update", 2), ("updates", 2), ("v0.", 2), ("v1.", 2), ("v2.", 2), ("release v", 2),
    ("patch", 1.5), ("bug fix", 2), ("fixes", 1.5),
    ("mobile", 1.5), ("ios", 1.5), ("android", 1.5), ("desktop app", 2), ("browser", 1),
    ("deploy", 1.5), ("app", 1.5), ("api", 0.4),
    ("产品", 2.5), ("功能", 2.5), ("上线", 2), ("更新", 2), ("应用", 1.5), ("工具", 2),
    ("插件", 2), ("集成", 2), ("客户端", 2), ("助手", 1.5), ("发布新", 3), ("新版", 2.5),
]
IND_KW = [
    ("funding", 3), ("raises", 3), ("raised", 3), ("series a", 3), ("series b", 3),
    ("series c", 3), ("series d", 3), ("series e", 3), ("seed round", 3), ("round", 1),
    ("valuation", 3), ("valued at", 3), ("unicorn", 2.5),
    ("revenue", 2.5), ("earnings", 2.5), ("profit", 2), ("ipo", 3), ("going public", 3),
    ("bankruptcy", 3), ("chapter 11", 3), ("insolvent", 3), ("wind down", 2),
    ("acquires", 3), ("acquisition", 3), ("acquired", 3), ("merger", 3), ("merges", 3),
    ("partnership", 2.5), ("partners with", 2.5), ("teams up", 2), ("deal", 1.5),
    ("contract", 2.0),
    ("investment", 2), ("invests", 2.5), ("capex", 2.5), ("billion", 0.8), ("million", 0.4),
    ("ceo", 2), ("cto", 2), ("coo", 2), ("steps down", 3), ("resign", 3), ("appoints", 2.5),
    ("hire", 1.5), ("hires", 2), ("layoff", 3), ("layoffs", 3), ("job cuts", 3),
    ("price cut", 3), ("pricing", 2), ("cheaper", 2), ("free tier", 1.5),
    ("market share", 2.5), ("competition", 1.5), ("competitor", 1.5), ("rival", 1.5),
    ("stocks slide", 2.5), ("shares slide", 2.5), ("stock market", 2.0),
    ("market cap", 2.0), ("sell-off", 2.5), ("selloff", 2.5),
    ("quarterly results", 2.5), ("earnings call", 2.5), ("guidance", 1.5), ("contract", 1.2),
    ("融资", 3), ("轮", 1.5), ("估值", 3), ("财报", 3), ("营收", 2.5), ("业绩", 2),
    ("收购", 3), ("并购", 3), ("上市", 3), ("破产", 3), ("合作", 2), ("携手", 2),
    ("联合", 1.5), ("高管", 2.5), ("离职", 3), ("裁员", 3),
    ("任命", 2.5), ("上任", 2.5), ("降价", 3), ("价格", 1.8), ("市场份额", 2.5),
    ("竞争", 1.5), ("订单", 2), ("签约", 2), ("投资", 2), ("商业化", 2),
]
GOV_KW = [
    ("regulation", 3), ("regulator", 3), ("regulators", 3), ("regulatory", 3),
    ("lawsuit", 3), ("sued", 3), ("sues", 3), ("suing", 3), ("court", 2.5), ("ruling", 3),
    ("judge", 2.5), ("verdict", 3), ("injunction", 3), ("tribunal", 2.5),
    ("bill", 2), ("legislation", 3), ("lawmakers", 2.5), ("congress", 2), ("senate", 2),
    ("parliament", 2), ("law", 1.5),
    ("ban", 3), ("bans", 3), ("banned", 3), ("prohibit", 2.5), ("not allowed", 2.5),
    ("crackdown", 3),
    ("executive order", 3), ("antitrust", 3), ("ftc", 3), ("doj", 2),
    ("investigation", 2.5), ("probe", 2), ("subpoena", 3), ("fine", 1.5),
    ("copyright", 3), ("infring", 3), ("trademark", 2.5), ("patent", 2),
    ("safeguard", 2), ("incident", 2.5), ("breach", 3), ("data leak", 3), ("leaked", 2),
    ("hacked", 3), ("outage", 2), ("deepfake", 3), ("deep fake", 3), ("fraud", 2.5),
    ("scam", 2.5), ("misinformation", 2.5), ("disinformation", 2.5),
    ("export control", 3), ("export controls", 3), ("sanction", 2.5), ("blacklist", 2.5),
    ("compliance", 2), ("audit", 1.5), ("red team", 2), ("red-team", 2), ("jailbreak", 2.5),
    ("ethic", 2.5), ("ethical", 2.5), ("bias", 1.5), ("discriminat", 2.5),
    ("surveillance", 2.5), ("privacy", 2.5), ("child safety", 3), ("csam", 3),
    ("eu ai act", 3), ("ai act", 3), ("ai safety", 2),
    ("emergency brake", 2.5), ("trust architecture", 2.5),
    ("sandbox", 1.2), ("bypass", 1.2), ("rogue", 1.2), ("theft", 2.5),
    ("warn", 1.5), ("fabricat", 2.5), ("hallucinat", 2.5), ("hoax", 2.5),
    ("false claim", 2.0),
    ("监管", 3), ("法规", 3), ("法案", 3), ("禁令", 3), ("禁止", 3), ("严禁", 3),
    ("封禁", 2.5), ("处罚", 2.5), ("罚款", 2.5), ("立案", 3), ("起诉", 3),
    ("诉讼", 3), ("法院", 2.5),
    ("判决", 3), ("版权", 3), ("侵权", 3), ("泄露", 3), ("宕机", 2.5), ("深伪", 3),
    ("诈骗", 2.5), ("滥用", 2.5), ("合规", 2), ("备案", 3), ("伦理", 2.5), ("调查", 2.5),
    ("反垄断", 3), ("约谈", 3), ("整治", 2.5), ("整改", 2.5), ("下架", 2.5), ("政策", 1.8),
    ("事故", 2.5),
]
FRONT_KW = [
    ("future of", 2.5), ("what's next", 2.5), ("whats next", 2.5), ("next decade", 2),
    ("prediction", 2.5), ("predicts", 2), ("forecast", 2.5), ("outlook", 2),
    ("roadmap", 2), ("paradigm", 2.5),
    ("world model", 3), ("embodied", 3), ("robot", 1.2), ("robotics", 2.5), ("humanoid", 3),
    ("agi", 2.5), ("artificial general intelligence", 3), ("superintelligence", 3),
    ("multimodal", 1.5), ("multi-modal", 1.5), ("text-to-video", 2), ("aigc", 2.5),
    ("agentic", 2), ("autonomous agent", 2), ("automation", 1.2),
    ("opinion", 2.5), ("op-ed", 2.5), ("essay", 2.5), ("column", 1.5), ("commentary", 2),
    ("deep dive", 2), ("explainer", 2), ("interview", 1.5), ("podcast", 1),
    ("trend", 1.5), ("trends", 1.5),
    ("趋势", 3), ("未来", 1.5), ("前瞻", 3), ("研判", 3), ("观点", 3), ("评论", 2),
    ("思考", 1.5), ("解读", 1.5), ("深度", 1), ("机器人", 2.5), ("具身", 3),
    ("世界模型", 3), ("通用人工智能", 3), ("时间表", 2.5), ("范式", 2.5),
    ("agent", 0.8), ("智能体", 2),
]
NODE_KW = {"capability": CAP_KW, "product": PROD_KW, "industry": IND_KW,
           "governance": GOV_KW, "frontier": FRONT_KW}

# 非资讯内容（不进日报，路由到待归类池交裁决层显式排除）：
# 求职攻略/面试准备/职业建议这类页面标题里常带 interview / AI 等词，会被
# 关键词命中到高置信度误入档（实证：hn-algolia 的「Adobe Software Engineer
# Interview: Process, AI Rules and How to Prepare」被判趋势›具身智能 0.95）。
# 这里用标题形态判定而非节点降权——这类页面没有「主要影响落在哪一环节」。
NON_NEWS_TITLE_RE = [
    # 冒号/连字符分隔也算相邻：实证「Adobe Software Engineer Interview: Process,
    # AI Rules and How to Prepare」用空格分隔的写法漏判。
    (re.compile(r"\binterview\s*[:\-–—]?\s*(process|question|questions|prep|preparation|tips|guide)\b", re.I),
     "求职/面试攻略"),
    (re.compile(r"\binterview\b.{0,40}\bhow to (prepare|prep|pass|crush)\b", re.I),
     "求职/面试攻略"),
    (re.compile(r"\bhow to (prepare|prep|get|pass|crush)\b.{0,30}\binterview\b", re.I),
     "求职/面试攻略"),
    (re.compile(r"\b(interview|coding|system design) (questions|prep|tips|guide|cheat ?sheet)\b", re.I),
     "求职/面试攻略"),
    (re.compile(r"\b(resume|cv|cover letter|portfolio) (tips|guide|template|review)\b", re.I),
     "求职/简历攻略"),
    (re.compile(r"\b(job|hiring|career) (search|hunting|interview) (tips|guide|advice)\b", re.I),
     "求职攻略"),
    (re.compile(r"如何\s*(准备|应对|通过).{0,10}(面试|笔试)"), "求职/面试攻略"),
    (re.compile(r"(面试|求职|简历|笔试)[^。]{0,6}(攻略|指南|技巧|模板|经验分享)"), "求职攻略"),
]

# 事件合并的「主体锚点」与实词判据常量定义在 PLATFORM_ENTITY_KW 之后
# （EVENT_ANCHOR_KW 引用该列表）。

# 内容词（参与事件合并的实词）：长度 ≥4 的字母数字串，过滤常见虚词
_TITLE_STOP = {
    "that", "this", "with", "from", "have", "will", "been", "were", "they",
    "their", "your", "into", "over", "than", "then", "some", "such", "more",
    "most", "also", "just", "like", "make", "made", "about", "after", "before",
    "first", "other", "using", "says", "said", "here", "what", "when", "where",
    "which", "while", "could", "should", "would", "does", "done", "both",
    "only", "same", "each", "been", "being", "how", "why", "who", "new", "now",
}
_TITLE_WORD_RE = re.compile(r"[a-z][a-z0-9\-]{3,}")
# 合并阈值：共享实词数 ≥3，且较短标题的实词被覆盖 ≥50%（overlap 系数），
# 且至少一个共享实词是主体锚点。三个条件同时满足才判同一事件。
EVENT_MIN_SHARED = 3
EVENT_MIN_OVERLAP = 0.5

# 平台/服务主体先验：标题主体是消费级平台或产品服务时，落点通常在产品层
# （平台的功能变更、标注规则、订阅政策），而非模型/算法层。实证：YouTube
# 给 AI 音乐加标注被判能力›前沿模型发布（CAP_KW 的 launch/launches 抢分）。
PLATFORM_PRIOR = 2.5
PLATFORM_ENTITY_KW = [
    "youtube", "spotify", "netflix", "tiktok", "amazon", "apple music", "google play",
    "google maps", "microsoft", "meta", "instagram", "whatsapp", "linkedin", "adobe",
    "salesforce", "discord", "slack", "figma", "notion", "github", "gitlab", "android",
    "ios", "chrome", "firefox", "samsung", "sony", "nintendo", "playstation", "xbox",
    "tesla", "iphone", "ipad", "macbook", "windows", "steam", "play store",
]
PLATFORM_ENTITY_COMPILED = [(re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", re.I), k)
                           for k in PLATFORM_ENTITY_KW]

# 事件合并的「主体锚点」：同一事件的不同媒体标题往往措辞差异大、相似度
# 达不到 0.85（实证：techcrunch「YouTube Music launches new labels as AI-generated
# music floods streaming platforms」vs theverge「YouTube sticks new labels on
# AI-generated songs」，相似度仅 0.65，实为同一事件）。这类标题共享一个
# 专名主体（平台/公司/产品），据此做第二判据合并。
EVENT_ANCHOR_KW = PLATFORM_ENTITY_KW + [
    "openai", "anthropic", "deepmind", "mistral", "cohere", "perplexity", "hugging face",
    "nvidia", "amd", "intel", "qualcomm", "broadcom", "tsmc", "arm",
    "spacex", "tesla", "sora", "chatgpt", "claude", "gemini",
    "llama", "deepseek", "qwen", "kimi", "grok", "sec edgar",
    "federal reserve", "fda", "ftc", "doj", "european union", "congress",
    "supreme court", "white house", "stanford", "mit", "berkeley",
]
EVENT_ANCHOR_COMPILED = [
    re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", re.I)
    for k in EVENT_ANCHOR_KW]

# 规范第 5 节：信源原始分类 → 默认主线节点先验（最终仍按第 6 节裁决）
# 先验 2.5：标题强信号（≥2.5）即可改判——如 AIHOT industry 含政策内容改判治理
SOURCE_PRIOR = {
    ("aihot", "ai-models"): ("capability", 2.5),
    ("aihot", "ai-products"): ("product", 2.5),
    ("aihot", "industry"): ("industry", 2.5),
    ("aihot", "paper"): ("capability", 2.5),
    ("aihot", "tip"): ("frontier", 2.5),
    ("aihot", "flash"): (None, 0),
    ("arxiv-query", None): ("capability", 3.0),
    ("hf-papers", None): ("capability", 3.0),
    ("openalex", None): ("capability", 3.0),
    ("github-search", None): ("product", 2.0),
    ("federal-register", None): ("governance", 3.5),
    ("sec-edgar", None): ("industry", 3.5),
    ("congress-gov", None): ("governance", 3.5),
}

# 子类关键词（节点内二次判定）
SUB_KW = {
    ("capability", "前沿模型发布"): ["model release", "releases", "launch", "unveil", "introducing",
        "open weight", "open-source model", "weights released", "frontier model", "模型", "权重", "开源模型",
        "decision model"],
    ("capability", "算法与训练方法"): ["training", "pretrain", "fine-tun", "distill", "quantiz",
        "architecture", "transformer", "scaling law", "method", "algorithm", "study", "research",
        "训练", "算法", "方法", "研究", "提出", "论文"],
    ("capability", "评测与基准"): ["benchmark", "leaderboard", "sota", "state-of-the-art", "arena",
        "evaluation", "eval", "评测", "基准", "榜单"],
    ("capability", "算力与基础设施"): ["gpu", "chip", "tpu", "cuda", "data center", "datacenter",
        "compute cluster", "infrastructure", "算力", "芯片", "数据中心"],
    ("product", "新产品与新功能"): ["feature", "launch", "rollout", "now supports", "generally available",
        "now available", "new app", "功能", "上线", "发布新", "新品"],
    ("product", "迭代与修复"): ["update", "v0.", "v1.", "v2.", "patch", "bug fix", "fixes",
        "release v", "更新", "修复", "新版"],
    ("product", "开源项目与工具链"): ["open-source project", "repository", "repo", "framework",
        "library", "sdk", "cli", "tool", "toolchain", "github", "开源项目", "工具链", "框架"],
    ("product", "垂直行业落地"): ["healthcare", "hospital", "medical", "education", "school",
        "finance", "bank", "legal", "manufacturing", "deploy", "医疗", "医院", "教育", "金融",
        "法律", "制造", "落地"],
    ("industry", "投融资与财报"): ["funding", "raises", "series", "valuation", "ipo", "revenue",
        "earnings", "profit", "quarterly", "融资", "估值", "财报", "营收", "轮"],
    ("industry", "并购与合作"): ["acquires", "acquisition", "merger", "partnership", "partners",
        "deal", "收购", "并购", "合作"],
    ("industry", "市场格局与竞争"): ["market share", "competition", "competitor", "rival",
        "pricing", "price cut", "cheaper", "市场份额", "竞争", "降价", "价格"],
    ("industry", "组织与人事"): ["ceo", "cto", "coo", "steps down", "resign", "appoints", "hire",
        "layoff", "高管", "离职", "裁员", "任命", "上任", "人事"],
    ("governance", "政策法规与监管"): ["regulation", "regulator", "law", "bill", "legislation",
        "ban", "executive order", "antitrust", "investigation", "fine", "监管", "法规", "法案",
        "禁令", "政策", "约谈", "备案", "反垄断"],
    ("governance", "安全与风险事件"): ["breach", "leak", "hacked", "outage", "incident",
        "deepfake", "fraud", "scam", "safety", "jailbreak", "泄露", "宕机", "深伪", "诈骗",
        "事故", "安全", "emergency brake", "trust architecture", "sandbox", "bypass",
        "rogue", "theft", "replicate"],
    ("governance", "版权与判例"): ["copyright", "infring", "lawsuit", "sued", "court", "ruling",
        "verdict", "trademark", "patent", "版权", "侵权", "诉讼", "法院", "判决"],
    ("governance", "伦理与社会影响"): ["ethic", "bias", "discriminat", "surveillance", "privacy",
        "misinformation", "伦理", "歧视", "隐私", "监控"],
    ("frontier", "具身智能与机器人"): ["humanoid", "embodied", "robotics", "具身", "人形",
        "机器人公司", "robot vendor", "quadruped", "四足"],
    ("frontier", "多模态与AIGC"): ["multimodal", "multi-modal", "text-to-video", "aigc",
        "video generation", "image generation", "music generation", "多模态", "生成式", "文生", "图生"],
    ("frontier", "Agent与自动化"): ["agentic", "autonomous agent", "智能体", "自动化",
        "agent 范式", "agent paradigm", "multi-agent", "多智能体"],
    ("frontier", "新兴方向与前瞻观点"): ["future", "prediction", "forecast", "roadmap", "opinion",
        "essay", "trend", "world model", "agi", "superintelligence", "趋势", "未来", "前瞻",
        "研判", "观点", "世界模型", "通用人工智能", "评论", "解读"],
}

# B 轨标签关键词（规范 4.1 封闭词表）
B_TAG_KW = {
    "发布": ["release", "launch", "unveil", "announce", "introduc", "debut", "发布", "上线", "推出", "亮相"],
    "更新": ["update", "upgrade", "improve", "v0.", "v1.", "v2.", "patch", "iteration", "更新", "升级", "新版"],
    "融资": ["funding", "raises", "series a", "series b", "series c", "valuation", "ipo", "融资", "轮", "估值", "募资"],
    "政策": ["regulation", "regulator", "law", "bill", "legislation", "ban", "lawsuit", "sued",
             "court", "ruling", "executive order", "antitrust", "监管", "法规", "法案", "禁令",
             "诉讼", "法院", "判决", "政策", "约谈", "备案"],
    "论文": ["paper", "arxiv", "preprint", "study", "论文", "预印本"],
    "教程": ["tutorial", "how to", "how-to", "guide", "tips", "getting started", "教程", "如何", "指南", "技巧"],
    "观点": ["opinion", "op-ed", "essay", "argues", "takes", "i think", "why ", "观点", "评论", "思考", "怎么看"],
    "事故": ["breach", "leak", "outage", "incident", "hacked", "deepfake", "fraud", "scam",
             "failure", "bug", "泄露", "宕机", "事故", "故障", "深伪", "诈骗", "漏洞"],
    "榜单": ["benchmark", "leaderboard", "sota", "state-of-the-art", "arena", "ranking", "榜单", "排行", "基准"],
    "开源": ["open source", "open-source", "open weight", "weights", "mit license", "apache",
             "github", "repo", "开源"],
    "降价": ["price cut", "cheaper", "discount", "free tier", "pricing", "降价", "免费", "价格"],
    "合作": ["partnership", "partners", "collaborat", "teams up", "joins forces", "合作", "携手", "联合"],
    "人事": ["ceo", "cto", "coo", "steps down", "resign", "appoints", "hire", "layoff", "高管", "离职", "任命", "上任", "裁员", "人事"],
    "数据": ["dataset", "corpus", "data set", "数据", "数据集"],
}

# D 轨：中国实体与地域信号
CN_ENTITY_KW = [
    "阿里巴巴", "阿里云", "通义", "腾讯", "混元", "百度", "文心", "字节跳动", "豆包", "即梦",
    "月之暗面", "kimi", "智谱", "chatglm", "深度求索", "deepseek", "华为", "昇腾", "盘古",
    "商汤", "科大讯飞", "讯飞", "minimax", "稀宇", "阶跃", "stepfun", "零一万物", "百川",
    "面壁", "昆仑万维", "天工", "美团", "小米", "京东", "蚂蚁", "网易", "快手", "可灵",
    "生数", "爱诗", "智元", "宇树", "优必选", "中国移动", "中国电信", "中国联通",
    "网信办", "工信部", "国家数据局", "证监会", "广电总局", "国务院",
]
CN_REGION_KW = ["中国", "国内", "国产", "北京", "上海", "深圳", "杭州", "广州", "中文", "我国"]

# 中国公司/模型实体（用于 region 判定；中英文并列）
CN_ENTITY_KW += ["qwen", "通义千问", "wenxin", "ernie", "doubao", "hunyuan",
                 "glm", "baichuan", "pangu"]
# 英文中国实体（ASCII 子串匹配，词形本身唯一，误配风险低）：
# 此前只有 deepseek/qwen 等模型名，公司名一律缺失，导致「Chinese AI agents」
# 「China AI-chip share / Huawei」等标题判成 global，当日「涉及中国」为 0。
CN_ENTITY_KW += ["huawei", "alibaba", "alipay", "tencent", "baidu", "bytedance",
                 "sensetime", "zhipu", "moonshot", "xiaomi", "meituan", "unitree",
                 "agibot", "cambricon", "iflytek", "minimaxi", "stepfun"]
# 中国地域词（英文）：需词边界正则，"china" 子串会误配 Chinatown / Chinatext
CN_REGION_EN_RE = [
    (re.compile(r"\bchina(?:'s|s')?\b", re.I), "China"),
    (re.compile(r"\bchinese\b", re.I), "Chinese"),
    (re.compile(r"\bbeijing\b", re.I), "Beijing"),
    (re.compile(r"\bshanghai\b", re.I), "Shanghai"),
    (re.compile(r"\bshenzhen\b", re.I), "Shenzhen"),
    (re.compile(r"\bhangzhou\b", re.I), "Hangzhou"),
    (re.compile(r"\bguangdong\b", re.I), "Guangdong"),
    (re.compile(r"\bprc\b", re.I), "PRC"),
]
# 带连字符的模型家族用正则匹配，防普通词汇误配：
# "step-" 曾误配 step-level / step-wise（arXiv 论文高频词），"yi-" 同理
CN_ENTITY_RE = [
    (re.compile(r"\bstep-\d", re.I), "step-"),        # 阶跃星辰 Step-1/2/3 系
    (re.compile(r"\byi-[a-z0-9]", re.I), "yi-"),      # 零一万物 Yi 系（Yi-6B/Yi-Large）
]
# 摘要兜底的前导区长度：实体提及落在此之内才算主题信号（见 detect_region 说明）
SUMMARY_LEAD = 300

CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
HTML_TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
URL_PARAM_DROP = re.compile(r"^(utm_|fbclid$|gclid$|ref$|source$|spm$)", re.I)


# ---------------------------------------------------------------- 基础工具
def bj_now():
    return datetime.now(BJ)


def clean_text(s):
    if not s:
        return ""
    s = html_mod.unescape(s)
    s = HTML_TAG_RE.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def cjk_len(s):
    """摘要字数：汉字计 1，其余字符计 0.5（规范 7.2「≤60 字（汉字计）」）。"""
    n = 0.0
    for ch in s:
        n += 1.0 if CJK_RE.match(ch) else 0.5
    return n


def truncate_summary(s, limit=60):
    """压缩至 ≤60 汉字；无法保真时截断并标注「…」。返回 (文本, 是否经压缩)。"""
    s = clean_text(s)
    if not s:
        return "", False
    if cjk_len(s) <= limit:
        return s, False
    out = []
    n = 0.0
    for ch in s:
        w = 1.0 if CJK_RE.match(ch) else 0.5
        if n + w > limit:
            break
        out.append(ch)
        n += w
    # 尽量在词边界收尾（英文场景）
    text = "".join(out).rstrip(" ,;:.-—·、，")
    return text + "…", True


def norm_title(s):
    """标题相似度用的规范化：小写、仅保留字母数字与汉字。"""
    return re.sub(r"[^0-9a-z一-鿿]+", "", (s or "").lower())


def norm_url(u):
    """URL 规范化：小写 scheme/host、去 www、去追踪参数、去尾斜杠（规范 7.4 去重键）。"""
    if not u:
        return ""
    u = u.strip()
    m = re.match(r"^(https?)://([^/?#]+)(.*)$", u, re.I)
    if not m:
        return u.rstrip("/")
    scheme, host, rest = m.group(1).lower(), m.group(2).lower(), m.group(3)
    if host.startswith("www."):
        host = host[4:]
    path, _, query = rest.partition("?")
    params = [p for p in query.split("&") if p and not URL_PARAM_DROP.match(p.split("=")[0])]
    q = "&".join(sorted(params))
    out = scheme + "://" + host + path.rstrip("/")
    if q:
        out += "?" + q
    return out


def to_bj(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BJ)


def human_time(dt_bj, has_time=True):
    """北京时间人话格式：『10 月 13 日 01:36』；仅日期时『10 月 13 日』。"""
    if has_time:
        return "%d 月 %d 日 %02d:%02d" % (dt_bj.month, dt_bj.day, dt_bj.hour, dt_bj.minute)
    return "%d 月 %d 日" % (dt_bj.month, dt_bj.day)


def parse_dt(value, has_time=True):
    """解析多类时间字段 → (北京时间 datetime, 是否有时刻)。失败返回 (None, False)。"""
    if not value:
        return None, False
    value = value.strip()
    try:
        if re.match(r"^[A-Z][a-z]{2},", value):  # RFC 822
            dt = parsedate_to_datetime(value)
            return to_bj(dt), True
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):  # 纯日期
            dt = datetime.strptime(value, "%Y-%m-%d")
            return dt.replace(tzinfo=BJ), False
        iso = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return to_bj(dt), True
    except Exception:
        return None, False


# ---------------------------------------------------------------- 快照解析
def load_registry_meta():
    reg = json.load(open(REGISTRY_PATH, encoding="utf-8"))
    return {s["id"]: s for s in reg["sources"]}


def parse_feed(text):
    """RSS/Atom → [(title, link, published_raw, summary_raw, categories)]"""
    root = ET.fromstring(text)
    out = []
    ns = "{http://www.w3.org/2005/Atom}"
    items = list(root.iter("item"))
    if items:
        for it in items:
            title = clean_text(it.findtext("title") or "")
            link = (it.findtext("link") or "").strip()
            if not link:
                link = (it.findtext("guid") or "").strip()
            pub = it.findtext("pubDate") or it.findtext(
                "{http://purl.org/dc/elements/1.1/}date") or ""
            desc = it.findtext("description") or it.findtext(
                "{http://purl.org/rss/1.0/modules/content/}encoded") or ""
            cats = [c.text or "" for c in it.findall("category")]
            out.append((title, link, pub, clean_text(desc), cats))
    else:
        for it in root.iter(ns + "entry"):
            title = clean_text(it.findtext(ns + "title") or "")
            link = ""
            for l in it.findall(ns + "link"):
                if l.get("rel") in (None, "alternate"):
                    link = (l.get("href") or "").strip()
                    break
            pub = it.findtext(ns + "published") or it.findtext(ns + "updated") or ""
            summary = it.findtext(ns + "summary") or it.findtext(ns + "content") or ""
            cats = [c.get("term") or "" for c in it.findall(ns + "category")]
            if not cats:
                prim = it.find("{http://arxiv.org/schemas/atom}primary_category")
                if prim is not None:
                    cats = [prim.get("term") or ""]
            out.append((title, link, pub, clean_text(summary), cats))
    return out


def parse_aihot(obj, fetched_at):
    """AIHOT 日报 JSON：sections 五版块 + flashes 快讯。C 轨用版块原始分类。"""
    report = obj.get("report") or obj
    out = []
    sec_cat = {"模型发布/更新": "ai-models", "产品发布/更新": "ai-products",
               "行业动态": "industry", "论文研究": "paper", "技巧与观点": "tip"}
    for sec in report.get("sections") or []:
        cat = sec_cat.get(sec.get("label") or "", "unknown")
        for it in sec.get("items") or []:
            links = it.get("links") or {}
            out.append({
                "title": clean_text(it.get("title") or ""),
                "url": links.get("original") or links.get("aihot") or "",
                "mirror_url": links.get("aihot") or "",
                "published_raw": "", "has_time": False,
                "summary": clean_text(it.get("summary") or ""),
                "cats": [cat],
                "src_name": (it.get("source") or {}).get("name") or "",
            })
    for f in report.get("flashes") or []:
        links = f.get("links") or {}
        out.append({
            "title": clean_text(f.get("title") or ""),
            "url": links.get("original") or links.get("aihot") or "",
            "mirror_url": links.get("aihot") or "",
            "published_raw": f.get("publishedAt") or "",
            "has_time": True,
            "summary": "",
            "cats": ["flash"],
            "src_name": (f.get("source") or {}).get("name") or "",
        })
    return out


def parse_hn(obj, fetched_at):
    out = []
    for h in obj.get("hits") or []:
        url = h.get("url") or ""
        if not url:
            url = "https://news.ycombinator.com/item?id=%s" % h.get("objectID", "")
        out.append({
            "title": clean_text(h.get("title") or ""),
            "url": url, "mirror_url": "",
            "published_raw": h.get("created_at") or "", "has_time": True,
            "summary": clean_text(h.get("story_text") or ""),
            "cats": ["hackernews"],
            "extra": {"points": h.get("points"), "comments": h.get("num_comments")},
            "src_name": "Hacker News",
        })
    return out


def parse_github(obj, fetched_at):
    out = []
    for it in obj.get("items") or []:
        out.append({
            "title": "%s — %s" % (it.get("full_name") or "", clean_text(it.get("description") or "")),
            "url": it.get("html_url") or "", "mirror_url": "",
            "published_raw": it.get("pushed_at") or it.get("created_at") or "",
            "has_time": True,
            "summary": clean_text(it.get("description") or ""),
            "cats": ["github-repo"],
            "extra": {"stars": it.get("stargazers_count")},
            "src_name": "GitHub",
        })
    return out


def parse_openalex(obj, fetched_at):
    out = []
    for w in obj.get("results") or []:
        loc = (w.get("primary_location") or {})
        url = loc.get("landing_page_url") or w.get("doi") or ""
        inv = w.get("abstract_inverted_index") or {}
        words = sorted(
            ((pos, word) for word, poss in inv.items() for pos in poss),
            key=lambda x: x[0])
        abstract = " ".join(wd for _, wd in words[:400])
        out.append({
            "title": clean_text(w.get("display_name") or w.get("title") or ""),
            "url": url, "mirror_url": "",
            "published_raw": w.get("publication_date") or "", "has_time": False,
            "summary": clean_text(abstract),
            "cats": ["openalex:%s" % (w.get("type") or "work")],
            "extra": {"cited_by": w.get("cited_by_count")},
            "src_name": "OpenAlex",
        })
    return out


def parse_edgar(obj, fetched_at):
    out = []
    for h in ((obj.get("hits") or {}).get("hits") or []):
        src = h.get("_source") or {}
        ciks = src.get("ciks") or []
        adsh = (src.get("adsh") or "").replace("-", "")
        url = ""
        if ciks and adsh:
            url = "https://www.sec.gov/Archives/edgar/data/%s/%s/" % (
                int(ciks[0]), adsh)
        company = (src.get("display_names") or [""])[0]
        form = src.get("form") or src.get("root_forms") or [""]
        form = form[0] if isinstance(form, list) and form else form
        fdate, form_s = src.get("file_date") or "", form or "?"
        # 同一发行人当天同类型备案可能多份（不同 accession），标题若无报文号无法
        # 区分；补受理号（原始报文号，非新增内容）保证条目可辨识可点开。
        acc = src.get("adsh") or adsh
        title = "%s（%s，Form %s%s）" % (
            company, fdate, form_s, " · 受理号 %s" % acc if acc else "")
        desc = clean_text(src.get("file_description") or "")
        out.append({
            "title": clean_text(title),
            "url": url, "mirror_url": "",
            "published_raw": src.get("file_date") or "", "has_time": False,
            "summary": desc,
            "cats": ["edgar:%s" % (form or "filing")],
            "src_name": "SEC EDGAR",
        })
    return out


def parse_fedreg(obj, fetched_at):
    out = []
    for d in obj.get("results") or obj.get("documents") or []:
        out.append({
            "title": clean_text(d.get("title") or ""),
            "url": d.get("html_url") or "", "mirror_url": "",
            "published_raw": d.get("publication_date") or "", "has_time": False,
            "summary": clean_text(d.get("abstract") or ""),
            "cats": ["federal-register"],
            "src_name": "Federal Register",
        })
    return out


def parse_snapshot(path, meta):
    """读一份快照 → 原始条目列表；无效快照返回 (None, 原因)。"""
    data = json.load(open(path, encoding="utf-8"))
    if not data.get("valid"):
        return None, data.get("error") or "快照无效"
    src_id = data.get("source_id") or path.stem
    raw = data.get("raw") or ""
    fetched_at = data.get("fetched_at_bj") or ""
    stype = (meta or {}).get("type", "")
    try:
        if src_id == "aihot":
            items = parse_aihot(json.loads(raw), fetched_at)
        elif src_id == "hn-algolia":
            items = parse_hn(json.loads(raw), fetched_at)
        elif src_id == "github-search":
            items = parse_github(json.loads(raw), fetched_at)
        elif src_id == "openalex":
            items = parse_openalex(json.loads(raw), fetched_at)
        elif src_id == "sec-edgar":
            items = parse_edgar(json.loads(raw), fetched_at)
        elif src_id == "federal-register":
            items = parse_fedreg(json.loads(raw), fetched_at)
        elif stype in ("rss", "atom"):
            items = [{"title": t, "url": u, "published_raw": p, "has_time": True,
                      "summary": s, "cats": c, "mirror_url": "", "src_name": ""}
                     for (t, u, p, s, c) in parse_feed(raw)]
        else:
            return None, "类型 %s 无解析器" % stype
    except Exception as e:
        return None, "解析失败: %s" % e
    for it in items:
        it["source_id"] = src_id
        it["fetched_at_bj"] = fetched_at
    return items, None


# ---------------------------------------------------------------- 关键词编译
# 中文关键词：子串匹配；纯 ASCII 关键词：词边界正则 + 可选复数 s
# （防 ban→Bankruptcy 类误配，同时覆盖 chips/robots/models 等复数形态）
def _compile_kw(kw):
    if CJK_RE.search(kw):
        return None
    core = re.escape(kw)
    if kw.endswith("-"):          # 如 gpt- 允许后接数字/版本号
        return re.compile(r"(?<![a-z0-9])" + core + "s?", re.I)
    return re.compile(r"(?<![a-z0-9])" + core + "s?(?![a-z0-9])", re.I)


def compile_node_kw():
    compiled = {}
    for node, kws in NODE_KW.items():
        kws_set = {k for k, _ in kws}
        entries = []
        for kw, w in kws:
            # 跳过「另有单数条目」的复数词（由单数 + 可选 s 覆盖，避免重复计分）
            if kw.endswith("s") and kw[:-1] in kws_set:
                continue
            entries.append((_compile_kw(kw), kw, w))
        compiled[node] = entries
    return compiled


NODE_KW_COMPILED = compile_node_kw()
SUB_KW_COMPILED = {
    key: [(_compile_kw(kw), kw) for kw in kws] for key, kws in SUB_KW.items()
}
B_TAG_KW_COMPILED = {
    tag: [(_compile_kw(kw), kw) for kw in kws] for tag, kws in B_TAG_KW.items()
}


def kw_in(pat, kw, text):
    return pat.search(text) if pat is not None else (kw in text)


def score_text(text, compiled):
    """对一段文本累加各节点得分，返回 {node: score}。"""
    scores = {n: 0.0 for n in NODES}
    for node, entries in compiled.items():
        for pat, kw, w in entries:
            if kw_in(pat, kw, text):
                scores[node] += w
    return scores


# ---------------------------------------------------------------- 分类逻辑
STRONG_TITLE = 2.5   # 标题单节点得分 ≥ 此值视为「强信号」，可改判信源先验
MIN_TOP = 1.5        # 头部分数低于此值 → 置信度封顶 0.55（进待归类池）
PRIOR_ONLY_CAP = 0.55  # 标题零实词命中、仅靠先验/平台主体支撑时的置信上限（进待归类池）

# 结构性噪声闸门（规范第二篇 7.6）：以「程序性文书」为主体内容的备案类信源。
# 判据必须两条同时成立，缺一不可：
#   ① 标题与摘要均无 AI 实词命中（即分类完全靠信源先验撑着）；
#   ② 表单类型属**程序性文书**——基金与招股说明书、持仓与股权申报、股东会与
#      代理声明。这类文书正文出现的 AI 只存在于模板化风险因素段落。
# 命中者显式排除（route=excluded + noise_reason），**保留在数据集内可追溯**，
# 不进日报也不进人工队列。
# 经营主体的定期/临时披露（8-K / 10-Q / 10-K / 6-K / 20-F / S-1 / 425 等）
# 不受本规则影响——它们仍按 0.55 进待归类池，避免误伤真正与 AI 相关的公司公告。
SEC_STRUCTURAL_FORMS = frozenset({
    # 基金与招股说明书类
    "424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8", "424H",
    "485BPOS", "485APOS", "485BXT", "485POS", "497", "497J", "497K",
    "N-1A", "N-2", "N-8F", "ARS", "FWP", "POS",
    # 持仓与股权申报类
    "13F-HR", "13F-NT", "SC 13D", "SC 13G", "3", "4", "5", "144",
    # 股东会与代理声明类
    "DEF", "DEF 14A", "DEF 14C", "DEFA14A", "DEFM14A", "PRE 14A", "PRE 14C",
})


# AI 主体词：判断一份文本是否「以 AI 为主题」。SEC 条目的标题由机器拼装
# （发行人 + 日期 + 表单号 + 受理号），不含正文语义，故不能拿节点关键词做
# 「AI 实词命中」判断——发行人名里的 Investment / Acquisition / Data 等金融
# 通用词会造成假信号。本表只收 AI 主体词，供 SEC 闸门使用。
AI_SUBJECT_RE = re.compile(
    r"\b(?:a\.i\.|ai|artificial intelligence|machine learning|deep learning|"
    r"neural networks?|transformers?|llms?|large language models?|gen ?ai|"
    r"generative ai|chatbots?|copilots?|agentic|algorithms?|deepfakes?|"
    r"openai|anthropic|deepseek)\b"
    r"|人工智能|机器学习|深度学习|大模型|生成式|智能体|算法|深度伪造",
    re.IGNORECASE)


def sec_ai_evidence(title, summary):
    """SEC 条目是否含 AI 主体词（标题或申报说明）。"""
    return bool(AI_SUBJECT_RE.search("%s %s" % (title or "", summary or "")))


def sec_procedural_noise(src_id, cats, title, summary):
    """SEC 相关性闸门（结构性噪声，规范第二篇 7.6）。

    SEC EDGAR 是**全文检索**源：只有正文出现过 "artificial intelligence" 就会
    命中，于是模板化的基金说明书、持仓申报、代理声明乃至大盘股的程序性 8-K
    都会被带回，其 AI 只存在于风险因素段落。实测这类条目占当日入档约 1/4，
    且各日数量随大盘申报节奏跳动，严重干扰日报口径。

    闸门判据：**SEC 条目 + 标题与申报说明均无 AI 主体词**（见 AI_SUBJECT_RE）
    → 显式排除（route=excluded + noise_reason），**数据完整保留在数据集内可追溯**，
    不进日报、不占人工队列。

    为什么用「AI 主体词」而非节点关键词：SEC 标题是机器拼装的
    （发行人 + 日期 + 表单号 + 受理号），不含正文语义；发行人名里的
    Investment / Acquisition / Data 等金融通用词会命中节点词表造成假信号
    （实证：JPMorgan 424B2 曾凭 "investment" 拿到 0.95 自动入档）。

    反悔路径：闸门只认词表，白名单式放宽只需在 AI_SUBJECT_RE 增词
    （如把某发行主体补进去），不需要改流程。
    """
    if src_id != "sec-edgar" or sec_ai_evidence(title, summary):
        return None
    form = ""
    for c in cats or []:
        if isinstance(c, str) and c.startswith("edgar:"):
            form = c[6:]
            break
    kind = "程序性文书" if form.upper().replace("/A", "").strip() \
        in SEC_STRUCTURAL_FORMS else "非 AI 主体披露"
    return ("SEC %s（Form %s）：申报说明无 AI 主体词，"
            "AI 仅见于模板化风险因素" % (kind, form or "?"))


def detect_non_news(title):
    """非资讯内容识别：求职/面试攻略等。命中返回 (True, 说明)，否则 (False, "")。"""
    t = title or ""
    for rx, label in NON_NEWS_TITLE_RE:
        if rx.search(t):
            return True, label
    return False, ""


def score_nodes(title, summary, src_id, cats):
    """规则分类打分。返回 (combined, title_scores)。

    - 标题命中按原权重计；标题完全无命中时才用摘要（×0.8）——标题是主题的
      最强信号，长摘要易把主题稀释到相邻节点（规范 6.1「主要影响落点」）。
    - 信源先验按规范第 5 节映射表叠加；标题强信号可改判先验（见 classify_node）。
    """
    tl = (title or "").lower()
    title_scores = score_text(tl, NODE_KW_COMPILED)
    if max(title_scores.values()) == 0 and summary:
        title_scores = {n: s * 0.8 for n, s in
                        score_text(summary.lower(), NODE_KW_COMPILED).items()}
    combined = dict(title_scores)
    for (sid, cat), (node, prior) in SOURCE_PRIOR.items():
        if sid == src_id and (cat is None or cat in cats):
            if node:
                combined[node] += prior
            break
    # 平台主体先验：主体是消费级平台/服务时，产品层加权（规范 6.1 主要影响落点）。
    # 三重约束，缺一不可：
    # ① 标题已有能力层强信号（模型发布/权重开源/基准/训练方法）时不加——防
    #   「Microsoft releases Phi-4」这类平台主体的模型发布被抢到产品层。
    # ② 标题除平台名外还需有其他主题关键词命中，才计为标题证据（进 title_scores）；
    #   只有平台名时不进 title_scores，避免「Making 3D Model with Meta Oakley AI
    #   Glasses」这类零实词的个人演示凭空拿到强信号入档（实证）。
    # ③ 无论何种情况都进 combined，保证平台主体条目至少落到产品层而非「无归属」。
    for pat, name in PLATFORM_ENTITY_COMPILED:
        if pat.search(tl):
            if title_scores.get("capability", 0.0) < STRONG_TITLE:
                combined["product"] += PLATFORM_PRIOR
                if max(title_scores.values()) > 0:
                    title_scores["product"] += PLATFORM_PRIOR
            break
    return combined, title_scores


def classify_node(item):
    combined, title_scores = score_nodes(
        item["title"], item["summary"], item["source_id"], item["cats"])
    # 结构性噪声闸门：程序性文书（基金/招股书、持仓申报、代理声明）且无 AI 主体词
    noise = sec_procedural_noise(
        item["source_id"], item["cats"], item["title"], item["summary"])

    # 非资讯内容闸门：求职攻略等不进日报，压到待归类池由裁决层显式排除
    is_non_news, non_news_label = detect_non_news(item["title"])
    strong = {n for n, s in title_scores.items() if s >= STRONG_TITLE}
    # 排序：分数优先，标题强信号优先（内容判定优先于信源先验，规范 6.2）
    c_ranked = sorted(combined.items(),
                      key=lambda kv: (kv[1], kv[0] in strong), reverse=True)
    top_node, top = c_ranked[0]
    second = c_ranked[1][1]
    if top <= 0 or is_non_news:
        return None, None, 0.0, combined, noise
    margin = (top - second) / top

    # 无标题实词证据时（标题除先验外零命中），置信封顶 PRIOR_ONLY_CAP——
    # 先验只是「大概属于哪层」，不能单独支撑自动入档，否则任何带平台名/命中
    # 信源先验的条目都会拿到 0.95（实证：Meta Oakley AI Glasses 个人演示视频）。
    if max(title_scores.values(), default=0) <= 0:
        return (top_node, SUBCATS[top_node][0], round(PRIOR_ONLY_CAP, 2),
                combined, noise)

    if top_node in strong:
        confidence = 0.85 + 0.1 * margin          # 标题强信号（含与先验叠加）
    elif len(strong) == 1:
        confidence = 0.6 + 0.15 * margin          # 强信号被先验压过（极少）→ 人工队列
    else:
        confidence = 0.35 + 0.6 * margin          # 先验 + 摘要兜底驱动
    if top < MIN_TOP:
        confidence = min(confidence, 0.55)        # 信号太弱 → 待归类池
    confidence = round(min(0.95, confidence), 2)

    # 子类：节点内关键词命中加权（标题 ×2）；信源类型提供默认先验
    text = (item["title"] + " " + item["summary"]).lower()
    tl = (item["title"] or "").lower()

    def sub_hits(sub):
        return sum(2 if kw_in(p, kw, tl) else 1
                   for p, kw in SUB_KW_COMPILED[(top_node, sub)] if kw_in(p, kw, text))

    best_sub, best_hits = SUBCATS[top_node][0], -1
    for sub in SUBCATS[top_node]:
        hits = sub_hits(sub)
        if hits > best_hits:
            best_sub, best_hits = sub, hits
    if best_hits <= 0:
        if top_node == "frontier" and "tip" in item["cats"]:
            best_sub = "新兴方向与前瞻观点"      # 规范：纯教程保留趋势-新兴方向
        elif top_node == "capability" and any(
                c.startswith(("cs.", "openalex")) for c in item["cats"]):
            best_sub = "算法与训练方法"          # 学术源默认
        elif top_node == "industry" and "edgar:" in "".join(item["cats"]):
            best_sub = "投融资与财报"            # SEC filing 本质是财务披露
        elif top_node == "product" and "github-repo" in item["cats"]:
            best_sub = "开源项目与工具链"
    return top_node, best_sub, confidence, combined, noise


def tag_b_track(title):
    """B 轨属性标签：只用标题判定（摘要噪音大，chip 展示限 ≤3）。"""
    text = (title or "").lower()
    tags = []
    for tag in B_VOCAB:
        for pat, kw in B_TAG_KW_COMPILED[tag]:
            if kw_in(pat, kw, text):
                tags.append(tag)
                break
    return tags


def detect_region(item):
    """D 轨：全球/中国，按内容主体判定（语言不是地域信号——中文媒体也报道全球新闻）。

    判定信号（标题优先，摘要兜底）：中国实体 / 中国地域与机构词 → 中国；否则全球。
    摘要兜底只认「前导区」（SUMMARY_LEAD 字符）内的实体提及——实证： arXiv 论文在
    摘要深层提及 qwen/glm 基本是对照组或组件选用（如 "surpassing GLM 5.2"、
    "a small Qwen model for text encoding"），不是中国主体内容；出现在前导区
    才是主题信号（如 "built on Qwen3-Omni"）。
    """
    tl = (item["title"] or "").lower()
    for rx, name in CN_ENTITY_RE:
        if rx.search(tl):
            return "china", "中国实体（%s）" % name
    for kw in CN_ENTITY_KW:
        if kw.lower() in tl:
            return "china", "中国实体（%s）" % kw
    for kw in CN_REGION_KW:
        if kw in tl:
            return "china", "地域信号（%s）" % kw
    for rx, name in CN_REGION_EN_RE:
        if rx.search(tl):
            return "china", "地域信号（%s）" % name
    sl = (item["summary"] or "").lower()
    lead = sl[:SUMMARY_LEAD]
    for rx, name in CN_ENTITY_RE:
        if rx.search(lead):
            return "china", "中国实体·摘要（%s）" % name
    for kw in CN_ENTITY_KW:
        if kw.lower() in lead:
            return "china", "中国实体·摘要（%s）" % kw
    for kw in CN_REGION_KW:
        if kw in lead:
            return "china", "地域信号·摘要（%s）" % kw
    for rx, name in CN_REGION_EN_RE:
        if rx.search(lead):
            return "china", "地域信号·摘要（%s）" % name
    return "global", "默认（未检出中国主体）"


# ---------------------------------------------------------------- 主流程
def stable_id(date_str, source_id, key2):
    """条目 ID：日期 + 内容指纹（信源 + 规范化 URL 的 sha1 前 6 位）。

    历史做法按快照内顺序编号，同一日报每重跑一次（新快照补入新条目）序号
    就会整体错位，导致 P1.5 裁决表与 reports 中的 ID 全部失效。改为内容指纹
    后 ID 在同一自然日内稳定：重跑、补抓、48h 合并都不会改变条目身份。
    """
    import hashlib
    raw = "%s|%s" % (source_id or "", norm_url(key2 or "") if key2 else "")
    return "IT-%s-%s" % (date_str.replace("-", ""),
                         hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6].upper())


def short_disable_reason(notes):
    """停用信源的简短说明：优先取「当前…」状态段，否则取开头一段（不截尾）。"""
    n = (notes or "").strip()
    if not n:
        return "见信源注册表"
    i = n.find("当前")
    seg = (n[i:] if i >= 0 else n).replace("当前备用：", "").replace("当前启用但抓取不稳：", "")
    return seg if len(seg) <= 72 else seg[:72] + "…"


def all_snapshot_dates():
    """全部可用快照日（巡检 数据/快照/ + 回溯 数据/回溯/），升序。"""
    days = set()
    for root in (SNAPSHOT_ROOT, BACKFILL_ROOT):
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if d.is_dir() and len(d.name) == 10 and d.name[4] == "-":
                days.add(d.name)
    return sorted(days)


def collect_snap_dirs(date_str, snapshots=None):
    """返回该日报参与合并的快照目录列表。

    默认：<date_str-1> / <date_str> / <date_str+1> 三个自然日快照目录
    （一天整日内容分散在相邻两次抓取里）。可用 --snapshots 显式指定参与
    合并的快照日期；每日巡检快照（数据/快照/）与历史回溯快照（数据/回溯/）
    同时参与，同名日期的回溯目录排在后面（同一信源 URL 去重时前者优先）。
    """
    day0 = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=BJ)
    if snapshots:
        snap_days = [s.strip() for s in snapshots.split(",") if s.strip()]
    else:
        # 从 D-1 起合并到「最新可用快照」为止，而不是只取 D-1/D/D+1。
        # 理由：一次抓取会带回多日历史，D 日的部分内容可能只出现在更晚的
        # 快照里（实测只看相邻三天每天漏 14 条以上）。窗口按发布自然日过滤，
        # 多并入更晚的快照不会把别日内容混进来，只会更完整。
        start = day0 - timedelta(days=1)
        snap_days = []
        for ds in all_snapshot_dates():
            if datetime.strptime(ds, "%Y-%m-%d").replace(tzinfo=BJ) >= start:
                snap_days.append(ds)
        snap_days.sort(reverse=True)          # 新快照优先（内容更完整）
    dirs = []
    for ds in snap_days:
        for root in (SNAPSHOT_ROOT, BACKFILL_ROOT):
            d = root / ds
            if d.is_dir() and d not in dirs:
                dirs.append(d)
    return dirs


def build_items(date_str, only=None, window_h=24, snapshots=None):
    """构建指定自然日的条目集（自然日归档，24h 口径）。

    date_str 是**资讯发布的自然日**，窗口 = 该日整日：
    win_start = date_str 00:00（北京时间），win_end = date_str+1 00:00。
    数据集按自然日落盘（window_hours=24）；48h 日报视图由渲染层合并
    相邻两个自然日数据得到，不重复落盘。

    快照源：一天整日的内容分散在多次抓取里（14 日 00:00–07:00 在 14 日快照、
    07:00–24:00 在 15 日快照），且部分内容可能只出现在更晚的快照中，故默认
    合并「date_str-1 起至最新可用快照」的全部快照目录（新者优先），跨快照
    重复按 (source_id, 规范化 URL) 去重；发布日窗口过滤保证不混入别日内容。
    历史回溯（无当日快照时）：用 --snapshots 指定可用快照日期，并自动并入
    数据/回溯/<日期>/ 下的定向补抓快照（见 backfill_sources.py）。
    """
    meta_map = load_registry_meta()
    day0 = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=BJ)
    win_start = day0
    win_end = day0 + timedelta(days=1)

    snap_dirs = collect_snap_dirs(date_str, snapshots)
    if not snap_dirs:
        raise SystemExit("快照目录不存在：%s" % (SNAPSHOT_ROOT / date_str))
    only_set = set(x.strip() for x in only.split(",")) if only else None

    raw_items, skip_all = [], []
    valid_sids = set()
    for snap_dir in snap_dirs:
        for path in sorted(snap_dir.glob("*.json")):
            sid = path.stem
            if sid == "巡检报告":
                continue
            if only_set and sid not in only_set:
                continue
            meta = meta_map.get(sid, {})
            if meta and meta.get("enabled") is False:
                skip_all.append((sid, snap_dir.name, "已停用 · %s"
                                 % short_disable_reason(meta.get("notes"))))
                continue
            items, err = parse_snapshot(path, meta)
            if err:
                skip_all.append((sid, snap_dir.name, err))
                continue
            valid_sids.add(sid)
            raw_items.extend(items)

    # 跨快照合并：同一信源同一 URL 的文章只保留首条（重复内容）
    seen_urls, deduped = set(), []
    for raw in raw_items:
        key = (raw.get("source_id"), norm_url(raw.get("url") or raw.get("link") or ""))
        if key[1] and key in seen_urls:
            continue
        if key[1]:
            seen_urls.add(key)
        deduped.append(raw)
    raw_items = deduped

    # 跳过快照口径：一个信源只有在**整个合并集内未产出任何
    # 有效快照**时才算「跳过」。此前按 source_id 保留最先遇到的失败记录，
    # 会把旧快照目录（如 R-1）的失败原因挂到当期报告上，而该信源当期快照
    # 其实解析成功（只是条目全被窗过滤除）——报告因此失真。
    # 部分目录失败的信源另计「部分快照无效」，并优先取最接近归档日的记录。
    def _day_rank(rec):
        try:
            return abs((datetime.strptime(rec[1], "%Y-%m-%d")
                        - day0.replace(tzinfo=None)).days)
        except ValueError:
            return 99

    skip_by_sid = {}
    for rec in skip_all:
        skip_by_sid.setdefault(rec[0], []).append(rec)
    skipped, partial = [], []
    for sid, recs in skip_by_sid.items():
        recs.sort(key=_day_rank)
        if sid in valid_sids:
            # 当日目录也失败 = 当期抓取真的出了问题（需关注）；
            # 仅相邻目录失败 = 历史遗留，当期数据完整。
            today_fail = [r for r in recs if r[1] == date_str]
            partial.append((sid, len(recs), today_fail[0][2] if today_fail else ""))
        else:
            skipped.append((sid, recs[0][2]))
    skipped.sort()
    partial.sort()

    # 归一化 + 打标
    items, filtered_old = [], []
    for idx, raw in enumerate(raw_items, 1):
        meta = meta_map.get(raw["source_id"], {})
        if raw.get("published_raw"):
            dt_bj, has_time = parse_dt(raw["published_raw"], raw.get("has_time", True))
            basis = "原文发布"
        else:
            dt_bj, has_time, basis = None, False, "信源收录"
        if dt_bj is None:
            dt_bj, basis = parse_dt(raw["fetched_at_bj"], True)[0] or bj_now(), "信源收录"
            has_time = True
        # 时间窗：日报只收「前两天整日」[win_start, win_end) 内的条目；
        # 过早的历史内容（如官方博客 RSS 全量历史）与当天 00:00 之后的内容
        # （归次日日报）均不计入当日数据集，仅在统计中记录
        if dt_bj < win_start:
            filtered_old.append({"source_id": raw["source_id"], "title": raw["title"],
                                 "reason": "过早（窗口前）"})
            continue
        if dt_bj >= win_end:
            filtered_old.append({"source_id": raw["source_id"], "title": raw["title"],
                                 "reason": "当日未完结（归次日日报）"})
            continue
        full_summary = clean_text(raw.get("summary") or "")
        summary, compressed = truncate_summary(full_summary)
        node, sub, conf, scores, noise = classify_node(raw)
        region, region_basis = detect_region(raw)
        item = {
            "id": stable_id(date_str, raw["source_id"], raw.get("url") or raw.get("title")),
            "source_id": raw["source_id"],
            "source_name": (meta or {}).get("name") or raw.get("src_name") or raw["source_id"],
            "source_tier": (meta or {}).get("tier", "T3"),
            "authority": (meta or {}).get("authority", 5),
            "title": raw["title"],
            "summary": summary,
            "summary_full": full_summary,
            "summary_compressed": compressed,
            "url": raw["url"],
            "mirror_url": raw.get("mirror_url") or "",
            "published_bj": human_time(dt_bj, has_time),
            "published_iso": dt_bj.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "time_basis": basis,
            "node": node,
            "node_name": NODE_NAMES.get(node, ""),
            "subcategory": sub,
            "tags_b": tag_b_track(raw["title"]),
            "tags_c": raw.get("cats") or [],
            "region": region,
            "region_basis": region_basis,
            "noise_reason": noise,
            "country": (meta or {}).get("country") or "",
            "country_name": COUNTRY_NAMES.get((meta or {}).get("country") or "", ""),
            "confidence": conf,
            "node_scores": {n: round(s, 2) for n, s in scores.items()},
            "extra": raw.get("extra") or {},
        }
        items.append(item)
    return items, skipped, filtered_old, partial


def _independent_source_ids(members):
    """事件内**独立报道**的信源清单（`source_count` 的唯一实现）。

    入参 `members` = 事件成员**条目字典**的列表（非下标）。

    「多信源交叉」要数的是**有几篇彼此独立的报道**，不是「有几家登过」。
    T3 聚合策展站（AI HOT）与 T4 社区（Hacker News Algolia）会把同一篇
    原文**原样转载**——URL 完全相同。这类条目本就该合并进同一事件
    （`dedup_and_merge` 已按规范化 URL 并集），但若再按 `source_id` 去重，
    一篇报道会被算成「2 个信源」，于是：

      · 一篇没人 independently 报道过的稿子，凭一条转载混进「今日热点」；
      · 48h 窗口转载更密（次日续抓必然多出几条同 URL 转载），虚增更明显；
      · 顺带污染头条判定（`assign_importance` 以 `source_count >= 3` 为头条依据）。

    实证（2026-10-13/14）：13 日 24h 的 6 条热点里有 4 条、14 日 48h 的 9 条里
    有 5 条属于「同一 URL 被两个信源收录」的伪交叉；头条里也有 3 条是这样来的。

    口径：先按**规范化 URL** 把成员归并成一篇篇独立报道，每篇报道只由其中
    **权威度最高**的那条作代表（同 URL 时权威度高者即首发方），再对代表计信源。
    排序键与 `collapse_duplicate_routes` 一致：权威度降序、发布升序取首。
    URL 为空时退化为按条目 id 独立计（无从判断是否同一篇，宁可分开）。
    """
    by_url = {}
    for it in members:
        u = norm_url(it["url"]) or ("#empty#" + it["id"])
        cur = by_url.get(u)
        if cur is None or ((-it["authority"], it["published_iso"]) <
                           (-cur["authority"], cur["published_iso"])):
            by_url[u] = it
    return sorted({it["source_id"] for it in by_url.values()})


def dedup_and_merge(items):
    """规范 7.4：规范化 URL + 标题相似度 ≥0.85 → 同一 Event。"""
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    norm_urls = [norm_url(it["url"]) for it in items]
    norm_titles = [norm_title(it["title"]) for it in items]
    url_first = {}
    for i in range(n):
        u = norm_urls[i]
        if u and u in url_first:
            union(url_first[u], i)
        elif u:
            url_first[u] = i
    # 标题相似度（长度预过滤 + quick_ratio 上界门控，避免全量 O(n²) 重比较）
    # 【跨信源约束】同一信源的两条不同 URL 视为两份独立文档（如 SEC 的相邻
    # 备案号），不因标题雷同而并成一「事件」——否则会吞掉真实条目。
    for i in range(n):
        ti = norm_titles[i]
        if len(ti) < 10:      # 过短标题易误判，交给 URL 去重
            continue
        for j in range(i + 1, n):
            if find(i) == find(j):
                continue
            if items[i]["source_id"] == items[j]["source_id"]:
                continue
            tj = norm_titles[j]
            if len(tj) < 10:
                continue
            la, lb = len(ti), len(tj)
            if abs(la - lb) * 4 > (la if la > lb else lb):   # 长度差 >25% 不可能 ≥0.85
                continue
            sm = difflib.SequenceMatcher(None, ti, tj)
            if sm.real_quick_ratio() < 0.85 or sm.quick_ratio() < 0.85:
                continue
            if sm.ratio() >= 0.85:
                union(i, j)

    # 第二判据（主体锚点 + 实词覆盖）：相似度不足 0.85 但共享同一专名主体
    # 且实词高度重合的跨信源标题，判为同一事件。长度预过滤只作用于相似度判据，
    # 本判据不用长度差做预过滤（长短标题常是同一事件的长短两种写法）。
    words = [set(w for w in _TITLE_WORD_RE.findall((it["title"] or "").lower())
                 if w not in _TITLE_STOP) for it in items]
    for i in range(n):
        if not words[i]:
            continue
        for j in range(i + 1, n):
            if find(i) == find(j):
                continue
            if items[i]["source_id"] == items[j]["source_id"]:
                continue
            if not words[j]:
                continue
            shared = words[i] & words[j]
            if len(shared) < EVENT_MIN_SHARED:
                continue
            overlap = len(shared) / min(len(words[i]), len(words[j]))
            if overlap < EVENT_MIN_OVERLAP:
                continue
            has_anchor = any(
                pat.search(items[i]["title"] or "") and pat.search(items[j]["title"] or "")
                for pat in EVENT_ANCHOR_COMPILED)
            if has_anchor:
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    events = []
    for root, members in groups.items():
        # 入档代表口径（规范 7.4）：权威度最高 → 发布最早。
        # 排序键必须与 collapse_duplicate_routes 完全一致，否则并列权威度时
        # 本函数会挑「发布较晚」的那条当 canonical，而收敛层挑「发布较早」的
        # 那条入档，事件就会指向一条面板里不存在的条目（热点与卡片对不上）。
        best = sorted(members, key=lambda i: (-items[i]["authority"],
                                              items[i]["published_iso"]))[0]
        distinct_sources = _independent_source_ids([items[i] for i in members])
        ev = {
            "event_id": "EVT-%04d" % (len(events) + 1),
            "canonical_item": items[best]["id"],
            "source_count": len(distinct_sources),   # 独立信源数（同一信源多条只计 1）
            "source_ids": distinct_sources,
            "sources": [{"item_id": items[i]["id"],
                         "source_name": items[i]["source_name"],
                         "authority": items[i]["authority"],
                         "url": items[i]["url"]} for i in members],
            "max_authority": max(items[i]["authority"] for i in members),
        }
        for i in members:
            items[i]["event_id"] = ev["event_id"]
            items[i]["source_count"] = ev["source_count"]
        events.append(ev)
    return events


def assign_importance(items):
    """规范 7.6：头条=多信源交叉≥3 或 T0 首发重大；重要=权威度≥8；其余一般。

    T0 治理类头条限定「真正的政府行为」：联邦公报法规/国会法案/行政令，
    不含 SEC EDGAR 企业财报 filing（SEC 是登记机关，内容属产业信息）。
    """
    gov_headline_kw = ("final rule", "executive order", "proposed rule",
                       "法案", "条例", "行政令", "法规")
    # 标题需含 AI 相关词才够「重大」——防联邦公报程序性通知（如 USDA
    # 行政审批流程规则）蹭 AI 查询关键词抢头条
    ai_title_kw = ("ai", "a.i.", "artificial intelligence", "machine learning",
                   "algorithm", "neural", "model", "data", "privacy", "deepfake",
                   "chatbot", "llm", "人工智能", "算法", "模型", "数据", "隐私",
                   "深度伪造", "智能体")
    for it in items:
        tags = set(it["tags_b"])
        tl = (it["title"] or "").lower()
        headline = False
        if it["source_count"] >= 3:
            headline = True
        if it["source_tier"] == "T0" and it["node"] == "capability" and "发布" in tags:
            headline = True
        if it["source_tier"] == "T0" and it["node"] == "governance":
            official = it["source_id"] in ("federal-register", "congress-gov")
            ai_related = any(kw in tl for kw in ai_title_kw)
            if (official or any(kw in tl for kw in gov_headline_kw)) and ai_related:
                headline = True
        if headline:
            it["importance"] = "头条"
        elif it["authority"] >= 8:
            it["importance"] = "重要"
        else:
            it["importance"] = "一般"


def collapse_duplicate_routes(items, log=None):
    """规范 7.4：同一 Event（跨信源）只保留一条入档代表。

    规则层可能对同一事件的多 source 条目都给出高置信度而全部入档，导致
    清单里出现「同一篇文章两条」。此处统一收敛：保留权威度最高（并列则
    发布时间最早）的一条为 filed，其余标记 event_member；它们在 events
    结构中仍完整可溯，用于交叉热点「N 个信源」提示。

    仅处理「跨信源」重复：同一信源下 URL 不同的条目是独立文档，不收敛。
    """
    groups = {}
    for it in items:
        if it.get("route") == "filed" and it.get("event_id"):
            groups.setdefault(it["event_id"], []).append(it)

    n = 0
    for eid, members in groups.items():
        # 收敛条件（两条，满足其一即收敛）：
        #   ① 跨信源：多个信源就同一事件各发了一篇 → 只留一条入档（规范 7.4
        #      「入档唯一代表」，也是 A10「每事件至多一条入档代表」的要求）。
        #   ② 同 URL 重复：同一篇文档被收了多次（含聚合站原样转载）→ 必须收敛，
        #      否则入档清单会出现重复 URL（A2）。
        # 单一信源且 URL 互不相同 = 各自独立的文档（SEC 相邻备案号等），不收敛。
        #
        # 【与 source_count 口径的区别，二者不可混用】
        # · source_count 数「有几篇独立报道」→ 同 URL 转载只计 1（否则伪交叉）。
        # · 本函数管「入档清单别出现同一篇文档的两条」→ 同 URL 必须收敛成
        #   event_member，哪怕它来自两个不同信源。判据为「跨信源 **或** 同 URL」——
        #   只看跨信源会让同 URL 转载漏进面板，造成重复条目。
        if len(members) < 2:
            continue
        by_url = {}
        for it in members:
            u = norm_url(it["url"]) or ("#empty#" + it["id"])
            by_url.setdefault(u, []).append(it)
        dup_url = any(len(v) > 1 for v in by_url.values())
        cross_src = len({m["source_id"] for m in members}) >= 2
        if not (dup_url or cross_src):
            continue
        members.sort(key=lambda i: (-i["authority"], i["published_iso"]))
        rep, rest = members[0], members[1:]
        for it in rest:
            it["route"] = "event_member"
            it["event_member_of"] = rep["id"]
            it.setdefault(
                "adjudication",
                "同一事件已有入档代表（%s，权威度 %.1f），按规范 7.4 不重复入档"
                % (rep["source_name"], rep["authority"]))
            n += 1
        if log is not None:
            log.append((eid, rep["id"],
                        [(it["id"], it["source_name"]) for it in rest]))
    return n


def regroup_events(items, events):
    """把事件分组对齐到人工裁决的 `event_member_of` 关系（规范 7.4）。

    自动去重遵守「同信源豁免」（同一信源的不同 URL 不自动合并），人工裁决却可以判定
    「同一事件」并把成员挂到**另一事件**的代表上。此时原事件会失去全部入档成员，
    在热点区表现为「有 N 个信源、面板里却找不到对应条目」（实证 10-10 EVT-0045）。

    本函数按挂靠关系把成员并回代表所在事件并重算该事件，被搬空的事件随之撤销；
    未涉事的事件原样保留。返回被撤销的事件数。
    """
    by_id = {it["id"]: it for it in items}
    moves = {}
    for it in items:
        rep_id, eid = it.get("event_member_of"), it.get("event_id")
        if not rep_id or not eid:
            continue
        rep = by_id.get(rep_id)
        tgt = (rep or {}).get("event_id")
        if tgt and tgt != eid:
            moves.setdefault(tgt, []).append(it["id"])
    if not moves:
        return 0

    ev_map = {e["event_id"]: e for e in events}
    moved = set()
    for tgt, ids in moves.items():
        ev = ev_map.get(tgt)
        if ev is None:
            continue
        have = {s.get("item_id") for s in (ev.get("sources") or [])}
        for iid in ids:
            it = by_id.get(iid)
            if it is None or iid in have:
                continue
            ev.setdefault("sources", []).append(
                {"item_id": iid, "source_name": it.get("source_name"),
                 "authority": it.get("authority"), "url": it.get("url")})
            it["event_id"] = tgt          # 成员跟随代表所在事件（否则事件号悬空）
            have.add(iid)
            moved.add(iid)

    for e in events:
        if e["event_id"] in moves or not moved:
            continue
        kept = [s for s in (e.get("sources") or [])
                if s.get("item_id") not in moved]
        if len(kept) != len(e.get("sources") or []):
            e["sources"] = kept

    # 接收方重算：独立信源数 / 信源清单 / 峰值权威度，并回写成员的 source_count
    for tgt in moves:
        ev = ev_map.get(tgt)
        if ev is None:
            continue
        # 与 dedup_and_merge 同口径：人工挂进来的成员可能又带来一条同 URL 转载，
        # 仍按「独立报道」计信源，不能让重算把伪交叉又算回来。
        pool = [by_id[s["item_id"]] for s in ev.get("sources") or []
                if s.get("item_id") in by_id]
        if len(pool) == len(ev.get("sources") or []):
            sids = _independent_source_ids(pool)
        else:   # 成员条目已不在本数据集，退回按 source_name 去重
            sids = sorted({(by_id.get(s.get("item_id")) or {}).get("source_id")
                           or s.get("source_name") or ""
                           for s in ev.get("sources") or []})
        ev["source_ids"] = sids
        ev["source_count"] = len(sids)
        ev["max_authority"] = max(
            [(by_id.get(s.get("item_id")) or {}).get("authority") or 0
             for s in ev.get("sources") or []] or [0])
        for s in ev.get("sources") or []:
            it = by_id.get(s.get("item_id"))
            if it is not None:
                it["source_count"] = ev["source_count"]

    live = [e for e in events if e.get("sources")]
    dropped = len(events) - len(live)
    events[:] = live
    return dropped


def normalize_member_links(items, events):
    """把 `event_member_of` 统一成「**本事件入档代表**的条目 id」。

    历史上这个字段混用了两种写法：自动收敛与部分裁决写的是**事件号**（EVT-xxxx），
    `collapse_duplicate_routes` 写的是**条目 id**。两种混在一起会让「成员是否属于
    本事件」这类一致性判断失效（热点找不到对应条目、审计误报）。此处统一归一到
    条目 id；事件若没有任何成员，则置空。返回被修正的条目数。
    """
    by_id = {it["id"]: it for it in items}
    members_of = {}
    for e in events:
        members_of[e.get("event_id")] = [
            s.get("item_id") for s in (e.get("sources") or []) if s.get("item_id")]

    rep_of = {}
    for eid, ids in members_of.items():
        pool = [by_id[i] for i in ids if i in by_id]
        if not pool:
            continue
        filed = [it for it in pool if it.get("route") == "filed"]
        pool = filed or pool                 # 优先入档代表；没有则退化为全体成员
        pool.sort(key=lambda it: (-(it.get("authority") or 0),
                                  it.get("published_iso") or ""))
        rep_of[eid] = pool[0]["id"]

    fixed = 0
    for it in items:
        if it.get("route") != "event_member":
            continue
        tgt = rep_of.get(it.get("event_id"))
        if it.get("event_member_of") != tgt:
            it["event_member_of"] = tgt
            fixed += 1
    return fixed


def sync_event_canonical(items, events):
    """把事件的 `canonical_item` 对齐到「已入档（filed）代表」。

    规范 7.4 规定同一事件只保留一条入档代表（权威度最高 → 发布最早），但
    `dedup_and_merge` 跑在路由判定**之前**，只能按同一排序键给出候选；候选若恰好
    未被入档（置信度落到待裁决 / 待归类），事件就会指向一条**面板里不存在的条目**，
    热点于是与卡片对不上（实证 10-14 EVT-0051：canonical 是被折叠的 The Decoder，
    真正入档的是 The Verge）。

    本函数在路由与收敛之后、按同一口径重新指认，保证 `canonical_item` 恒为面板
    可见的入档条目；事件若完全没有入档成员（如全部待裁决），保持原样。
    返回被修正的事件数。
    """
    filed = {it["id"]: it for it in items if it.get("route") == "filed"}
    fixed = 0
    for e in events:
        cand = [filed[s["item_id"]] for s in (e.get("sources") or [])
                if s.get("item_id") in filed]
        if not cand:
            continue
        cand.sort(key=lambda it: (-(it.get("authority") or 0),
                                  it.get("published_iso") or ""))
        if e.get("canonical_item") != cand[0]["id"]:
            e["canonical_item"] = cand[0]["id"]
            fixed += 1
    return fixed


def route_confidence(items):
    """规范 6.3：≥0.8 入档；0.6–0.8 人工裁决队列；<0.6 待归类池。

    结构性噪声（规范第二篇 7.6）先行短路：命中者一律 route=excluded，
    保留在数据集内可追溯，不进日报也不占人工队列。
    """
    filed, review, unclassified = [], [], []
    for it in items:
        if it.get("noise_reason"):
            it["route"] = "excluded"
            continue
        if it["node"] is None or it["confidence"] < 0.6:
            it["route"] = "unclassified"
            unclassified.append(it)
        elif it["confidence"] < 0.8:
            it["route"] = "review"
            review.append(it)
        else:
            it["route"] = "filed"
            filed.append(it)
    return filed, review, unclassified


def write_outputs(date_str, items, events, filed, review, unclassified, skipped,
                  filtered_old, extra=None, window_hours=24, partial=None):
    """写日报数据集与质检报告。

    extra 为附加元数据（归档流程传入 fetch_runs 等）；window_hours 为本数据集
    的窗口口径（自然日归档为 24；48h 由渲染层合并两日得到，不落盘）。
    """
    DAILY_ROOT.mkdir(parents=True, exist_ok=True)
    by_node, by_region, by_imp, by_src, by_country = {}, {}, {}, {}, {}
    for it in items:
        by_region[it["region"]] = by_region.get(it["region"], 0) + 1
        by_src[it["source_id"]] = by_src.get(it["source_id"], 0) + 1
        c = it.get("country") or "UN"
        by_country[c] = by_country.get(c, 0) + 1
    for it in filed:
        by_node[it["node"]] = by_node.get(it["node"], 0) + 1
        by_imp[it["importance"]] = by_imp.get(it["importance"], 0) + 1
    filtered_by_src = {}
    for f in filtered_old:
        filtered_by_src[f["source_id"]] = filtered_by_src.get(f["source_id"], 0) + 1

    dataset = {
        "date": date_str,
        "generated_at": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "spec_version": SPEC_VERSION,
        "window_hours": window_hours,
        "day_kind": "natural",
        "stats": {
            "parsed_items": len(items),
            "filtered_old": len(filtered_old),
            "filtered_by_source": filtered_by_src,
            "filed": len(filed), "review": len(review), "unclassified": len(unclassified),
            "event_members": sum(1 for i in items if i.get("route") == "event_member"),
            "excluded": sum(1 for i in items if i.get("route") == "excluded"),
            "events": len(events), "multi_source_events": sum(
                1 for e in events if e["source_count"] >= 2),
            "by_node": by_node, "by_region": by_region,
            "by_importance": by_imp, "by_source": by_src, "by_country": by_country,
            "skipped_snapshots": [{"source_id": s, "reason": r} for s, r in skipped],
            "partial_snapshots": [{"source_id": s, "failed_dirs": n,
                                   "today_failed_reason": r}
                                  for s, n, r in (partial or [])],
        },
        "items": items,
        "events": events,
        "review_queue": [it["id"] for it in review],
        "unclassified_pool": [it["id"] for it in unclassified],
    }
    if extra:
        dataset.update(extra)
    out_json = DAILY_ROOT / ("%s.json" % date_str)
    with open(out_json, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=1)

    # ---------------- 质检报告（人工校正用）
    L = []
    L.append("# AI 日报分类质检报告 · %s" % date_str)
    L.append("")
    L.append("- 生成时间：%s（北京时间）" % bj_now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("- 规范版本：%s（第二篇 R-02）" % SPEC_VERSION)
    L.append("- 数据集：数据/日报/%s.json" % date_str)
    L.append("")
    L.append("## 1. 总览")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|---|---|")
    L.append("| 归档窗 | 当日整日（%s 00:00 ~ %s 00:00，北京时间） |" % (
        date_str, (datetime.strptime(date_str, "%Y-%m-%d")
                   + timedelta(days=1)).strftime("%m-%d")))
    L.append("| 解析条目总数（窗内） | %d |" % len(items))
    early = sum(1 for f in filtered_old if f.get("reason") == "过早（窗口前）")
    late = sum(1 for f in filtered_old if f.get("reason") == "当日未完结（归次日日报）")
    L.append("| 窗过滤除（过早历史 %d + 当日未完结 %d） | %d |" % (
        early, late, len(filtered_old)))
    L.append("| 入档（置信度 ≥0.8） | %d |" % len(filed))
    L.append("| 人工裁决队列（0.6–0.8） | %d |" % len(review))
    L.append("| 待归类池（<0.6） | %d |" % len(unclassified))
    L.append("| 事件（Event）数 | %d（多信源 %d） |" % (
        len(events), dataset["stats"]["multi_source_events"]))
    L.append("")
    L.append("**节点分布（入档条目）**：")
    for n in NODES:
        L.append("- %s %s：%d" % (n, NODE_NAMES[n], by_node.get(n, 0)))
    L.append("")
    L.append("**地域分布**：全球 %d / 中国 %d" % (
        by_region.get("global", 0), by_region.get("china", 0)))
    L.append("")
    L.append("**来源国家/地区分布（国旗区分口径）**：%s" % " · ".join(
        "%s %d" % (COUNTRY_NAMES.get(c, c), n)
        for c, n in sorted(by_country.items(), key=lambda kv: -kv[1])))
    L.append("")
    src_rank = sorted(by_src.items(), key=lambda kv: -kv[1])
    L.append("**信源贡献**：%s" % " · ".join(
        "%s %d" % (sid, cnt) for sid, cnt in src_rank[:10]) +
        ("　（其余 %d 个信源共 %d 条）" % (
            len(src_rank) - 10, sum(c for _, c in src_rank[10:]))
         if len(src_rank) > 10 else ""))
    if skipped:
        L.append("")
        L.append("**跳过快照（%d 个·整个合并集内未产出任何有效快照）**："
                 % len(skipped))
        for sid, reason in skipped:
            L.append("- %s：%s" % (sid, reason))
    if partial:
        today_bad = [(s, r) for s, _n, r in partial if r]
        L.append("")
        if today_bad:
            L.append("**当期快照失败（%d 个·有邻日快照兜底，未影响入档，但需关注）**："
                     % len(today_bad))
            for sid, reason in today_bad:
                L.append("- %s：%s" % (sid, reason))
        other_bad = [(s, n) for s, n, r in partial if not r]
        if other_bad:
            L.append("")
            L.append("**仅邻日快照失败（%d 个·当期数据完整，无需处理）**："
                     % len(other_bad))
            for sid, n in other_bad:
                L.append("- %s：%d 个相邻快照目录失败" % (sid, n))
    if filtered_by_src:
        old_rank = sorted(filtered_by_src.items(), key=lambda kv: -kv[1])
        L.append("")
        L.append("**窗过滤除 %d 条**（RSS 全量历史，非当日发布，不计入日报）：%s"
                 % (sum(filtered_by_src.values()),
                    " · ".join("%s %d" % (sid, cnt) for sid, cnt in old_rank[:6])))
    L.append("")

    L.append("## 2. 人工裁决队列（置信度 0.6–0.8，交内容裁决层处理）")
    L.append("")
    if review:
        L.append("| ID | 标题（截断） | 候选节点 | 子类 | 置信度 | 次候选 |")
        L.append("|---|---|---|---|---|---|")
        for it in review:
            scores = it["node_scores"]
            ranked = [kv for kv in sorted(scores.items(), key=lambda kv: -kv[1])
                      if kv[0] != it["node"]]
            second = "%s(%.1f)" % (NODE_NAMES.get(ranked[0][0], ranked[0][0]),
                                   ranked[0][1]) if ranked else "—"
            L.append("| %s | %s | %s | %s | %.2f | %s |" % (
                it["id"], it["title"][:38], NODE_NAMES[it["node"]], it["subcategory"],
                it["confidence"], second))
    else:
        L.append("（空）")
    L.append("")

    L.append("## 3. 待归类池（<0.6，交内容裁决层处理）")
    L.append("")
    if unclassified:
        for it in unclassified:
            L.append("- %s《%s》（%s）" % (it["id"], it["title"][:50], it["source_name"]))
    else:
        L.append("（空）")
    L.append("")

    L.append("## 4. 入档条目抽检（前 40 条，供人工校正规则）")
    L.append("")
    L.append("| # | 标题（截断） | 节点›子类 | B 轨 | C 轨 | D | 置信 | 重要度 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for i, it in enumerate(filed[:40], 1):
        L.append("| %d | %s | %s›%s | %s | %s | %s | %.2f | %s |" % (
            i, it["title"][:30], NODE_NAMES[it["node"]], it["subcategory"],
            "/".join(it["tags_b"]) or "—", "/".join(it["tags_c"])[:18] or "—",
            "中" if it["region"] == "china" else "全", it["confidence"],
            it["importance"]))
    L.append("")
    L.append("## 5. 多信源事件（Event 合并结果）")
    L.append("")
    multi = [e for e in events if e["source_count"] >= 2]
    if multi:
        L.append("| Event | 信源数 | 信源 | 代表条目标题（截断） |")
        L.append("|---|---|---|---|")
        by_id = {it["id"]: it for it in items}
        for e in multi:
            t = by_id[e["canonical_item"]]["title"][:34]
            L.append("| %s | %d | %s | %s |" % (
                e["event_id"], e["source_count"],
                "/".join(sorted(set(e["source_ids"]))), t))
    else:
        L.append("（无多信源事件）")
    L.append("")
    L.append("> 判定口径：标题关键词词边界匹配（中文子串）；标题强信号（单节点 ≥2.5）"
             "可改判信源先验（规范第 5/6 节）；无标题命中时才用摘要兜底（×0.8）。"
             "队列条目由 adjudicate.py 按信息实质内容裁决（规范第二篇 6.3），"
             "裁决结果回流为判例写入附录 A 并改进分类规则；人工干预为浏览纠错模式。")
    out_md = DAILY_ROOT / ("%s_分类质检报告.md" % date_str)
    out_md.write_text("\n".join(L), encoding="utf-8", newline="\n")
    return out_json, out_md


def main():
    ap = argparse.ArgumentParser(description="P1 资讯分类器（R-02 落地）")
    ap.add_argument("--date", help="快照日期 YYYY-MM-DD，默认今天（北京时间）")
    ap.add_argument("--only", help="只处理指定信源快照，逗号分隔")
    ap.add_argument("--window-h", type=int, default=24,
                    help="归档窗口（小时，默认 24；自然日归档为当日整日）")
    ap.add_argument("--snapshots",
                    help="参与合并的快照日期，逗号分隔（默认 前一日/当日/次日）；"
                         "历史回溯补全时用可用快照日显式指定")
    args = ap.parse_args()
    date_str = args.date or bj_now().strftime("%Y-%m-%d")

    snap_dirs = collect_snap_dirs(date_str, args.snapshots)
    items, skipped, filtered_old, partial = build_items(
        date_str, only=args.only, window_h=args.window_h,
        snapshots=args.snapshots)
    if not items:
        raise SystemExit("没有可解析的条目（快照目录：%s）" % (SNAPSHOT_ROOT / date_str))
    events = dedup_and_merge(items)
    assign_importance(items)
    filed, review, unclassified = route_confidence(items)
    collapse_log = []
    dup = collapse_duplicate_routes(items, collapse_log)
    # 收敛之后：① 事件分组对齐人工裁决的挂靠关系（跨事件挂靠会把事件搬空，
    # 热点于是找不到对应条目）；② 把 canonical 对齐到真正入档的那条（规范 7.4）
    regroup_events(items, events)
    normalize_member_links(items, events)
    canonical_fixed = sync_event_canonical(items, events)
    filed = [i for i in items if i["route"] == "filed"]
    review = [i for i in items if i["route"] == "review"]
    unclassified = [i for i in items if i["route"] == "unclassified"]
    fetch_runs = [{"snapshot": str(d.relative_to(BASE)).replace("\\", "/"),
                   "kind": "backfill" if d.parent == BACKFILL_ROOT else "cron",
                   "files": len(list(d.glob("*.json")))} for d in snap_dirs]
    out_json, out_md = write_outputs(
        date_str, items, events, filed, review, unclassified, skipped, filtered_old,
        extra={"fetch_runs": fetch_runs,
               "snapshot_days": sorted({d.name for d in snap_dirs})},
        partial=partial)

    print("== P1 分类完成 %s ==" % date_str)
    print("解析 %d 条（窗过滤除 %d）→ 入档 %d / 事件成员 %d / 人工队列 %d / "
          "待归类 %d；事件 %d 个" % (
              len(items), len(filtered_old), len(filed),
              sum(1 for i in items if i["route"] == "event_member"),
              len(review), len(unclassified), len(events)))
    if dup:
        print("跨信源重复收敛 %d 条为事件成员（同一事件只保留一条代表）" % dup)
    by_node = {}
    for it in filed:
        by_node[it["node"]] = by_node.get(it["node"], 0) + 1
    print("入档节点分布：%s" % "；".join(
        "%s %d" % (NODE_NAMES[n], by_node.get(n, 0)) for n in NODES))
    if skipped:
        print("跳过快照：%s" % "；".join("%s(%s)" % (s, r[:40]) for s, r in skipped))
    if partial:
        print("部分快照失败：%s" % "；".join(
            "%s(当期:%s)" % (s, r) if r else "%s(仅邻日 %d 目录)" % (s, n)
            for s, n, r in partial))
    print("数据集：%s" % out_json)
    print("质检报告：%s" % out_md)


if __name__ == "__main__":
    main()
