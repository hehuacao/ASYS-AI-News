# -*- coding: utf-8 -*-
"""译文流水线（L1.5）——把 L1 事实源的标题与摘要预生成对照译文，供 L2 投影下发。

为什么单独一层
--------------
规范 R-02 有一条硬约束：**标题 = 信源原标题，禁止改写**。所以「界面全中英双语」不能靠
替换标题实现，只能**挂一层对照译文**。译文既不是原文、也不是事实源，它是可再生的派生
产物，因此放在 L1 与 L2 之间（L1.5），不入 L1 事实源、不参与去重与分类。

设计要点
--------
- **增量**：以「条目 id + 原文指纹（sha256）」为缓存键，原文没变就不重译。
- **可再生**：译表缺失可整体重跑；单个批次失败只丢该批，不影响其余。
- **可人工覆盖**：译表条目带 `trans.reviewed`，置 true 后本脚本不再覆盖（人工裁决优先）。
- **零第三方依赖**：只用标准库 `urllib`，接口为 OpenAI 兼容的 `/v1/chat/completions`。
- **密钥不入库**：优先读环境变量 `AGNES_API_KEY`，其次读本机 `config.json` 的 `api_key`；
  真实配置文件不随仓库分发。

产物
----
    数据/翻译/译表.json    {<条目 id>: {lang, title_alt, summary_alt, full_alt,
                                        src_hash, trans:{provider, model, at, reviewed}}}

用法
----
    python 脚本/translate_items.py                # 增量翻译（默认 10 条/批）
    python 脚本/translate_items.py --batch 12     # 调批大小
    python 脚本/translate_items.py --limit 60     # 只处理前 60 条（试跑）
    python 脚本/translate_items.py --date 2026-10-14
    python 脚本/translate_items.py --dry-run      # 只报数量，不发请求
"""
import argparse
import concurrent.futures as futures
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY_ROOT = ROOT / "数据" / "日报"
TRANS_ROOT = ROOT / "数据" / "翻译"
TABLE_PATH = TRANS_ROOT / "译表.json"

BASE_URL = os.environ.get("AGNES_BASE_URL", "https://api.agnes-ai.cn/v1")
DEFAULT_MODEL = "agnes-3.0-flash"
PROVIDER = "agnes"
# 摘要全文的切段策略：**按句边界切段、逐段独立翻译、按序拼接**。
# 若改为硬截到固定字符数，长摘要的译文只覆盖开头，详情页对照时读者看到「译文不完整」。
SEG_MAX = 1200      # 单段送译的字符数上限（一次请求的原文体量）
MAX_SEG = 8         # 单条最多译 8 段（覆盖到 ~9.6k 字符；实测最长 5.5k，足够）
SENT_END = re.compile(r"(?<=[.!?。！？；;])\s+|\n+")
BJ = timezone(timedelta(hours=8))

CJK = re.compile(r"[\u4e00-\u9fff]")


def split_long(text, seg_max=SEG_MAX):
    """把长摘要按句边界切成若干段，每段不超过 seg_max（单句超长时硬切）。

    切点优先落在句子边界——段内句子被截断会让译文读起来断气。
    """
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= seg_max:
        return [t]
    out, cur = [], ""
    for sent in SENT_END.split(t):
        if not sent:
            continue
        if len(sent) > seg_max:                      # 超长单句：再按逗号切，仍超则硬切
            for piece in re.split(r"(?<=[,，])\s*", sent):
                if len(piece) > seg_max:
                    for k in range(0, len(piece), seg_max):
                        out.append(piece[k:k + seg_max])
                    continue
                if cur and len(cur) + len(piece) > seg_max:
                    out.append(cur); cur = ""
                cur += piece
            continue
        if cur and len(cur) + len(sent) > seg_max:
            out.append(cur); cur = ""
        cur += sent
    if cur:
        out.append(cur)
    return out


# ------------------------------------------------------------------ 语言判定
def lang_of(text):
    """判定原文语言：汉字占比 ≥20% 或 ≥2 个汉字即判中文，否则英文。

    与 L2 投影保持同一判据（两处各自实现会漂移，故写在流水线里、由投影复用）。
    """
    s = text or ""
    cjk = len(CJK.findall(s))
    if cjk >= max(2, len(s) * 0.2):
        return "zh"
    return "en"


def src_hash(it):
    # 摘要全文用**完整原文**参与指纹：截断指纹会让「截断长度」一旦改变就整表失效
    raw = "\u0001".join([
        it.get("title") or "", it.get("summary") or "",
        it.get("summary_full") or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ 密钥
def load_api_key():
    """按 环境变量 → 项目根 config.json → 本机技能目录 config.json 的顺序取密钥。"""
    key = (os.environ.get("AGNES_API_KEY") or "").strip()
    if key:
        return key
    cands = [
        Path(__file__).resolve().parent.parent / "config.json",
        Path.home() / ".workbuddy" / "skills" / "AgnesAI" / "scripts" / "config.json",
    ]
    for cfg in cands:
        if not cfg.exists():
            continue
        try:
            key = (json.loads(cfg.read_text(encoding="utf-8")).get("api_key") or "").strip()
        except Exception:
            continue
        if key:
            return key
    return ""


# ------------------------------------------------------------------ 接口调用
def chat_json(system, user, key, model=DEFAULT_MODEL, max_tokens=4096, timeout=180):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def extract_json(text):
    """从模型输出里抠出第一个 JSON 对象：模型爱裹 ```json 代码块或前后寒暄。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"```\s*$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return None


# ------------------------------------------------------------------ 提示词
SYS = ("你是资深科技媒体编辑，负责一份 AI 资讯日报的中英对照译文。"
       "你输出的内容只用于「帮助读者快速理解外文标题与摘要」，"
       "不替代原文，也不作为事实来源。")


def build_prompt(batch, src, tgt):
    src_name = "英文" if src == "en" else "中文"
    tgt_name = "简体中文" if tgt == "zh" else "英文"
    rules = [
        "1. 只输出一个 JSON 对象，键为条目 id，值为 {\"title\": \"...\", \"summary\": \"...\", \"full\": \"...\"}；不要输出解释、代码块或多余文字。",
        "2. 忠实原文：不增删事实、不补充背景、不做推断，原文为空的字段输出空字符串。",
        "3. 产品名、公司名、模型名、机构名、人名保留原文不译（例：OpenAI、GPT-5、Transformer、Meta）；可在首次出现时用括号补一个简短中文说明。",
        "4. 数字、日期、金额、百分比、单位一律照抄，不做换算。",
        "5. 中文译文用" + tgt_name + "，行文贴近中文科技媒体；英文译文用新闻体简洁英文。",
        "6. 标题按原标题语序直译，不要润色成「标题党」，也不要重写为摘要。",
    ]
    items = [{"id": b["id"], "title": b["title"], "summary": b["summary"],
              "full": b["full"]} for b in batch]
    return ("任务：把下列 " + src_name + " 资讯条目翻译为" + tgt_name + "。\n\n规则：\n"
            + "\n".join(rules) + "\n\n条目（JSON 数组）：\n"
            + json.dumps(items, ensure_ascii=False))


# ------------------------------------------------------------------ 主流程
def load_table():
    if TABLE_PATH.exists():
        try:
            return json.loads(TABLE_PATH.read_text(encoding="utf-8"))
        except Exception:
            print("译表解析失败，已备份并从头开始", file=sys.stderr)
            TABLE_PATH.replace(TABLE_PATH.with_suffix(".corrupt.json"))
    return {}


def save_table(table):
    TRANS_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = TABLE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(table, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, TABLE_PATH)


def collect_items(only_date=None):
    """收集待译条目：入档（route != excluded）且原文非空。"""
    seen, files = {}, sorted(DAILY_ROOT.glob("20??-??-??.json"))
    for p in files:
        if only_date and p.stem != only_date:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in d.get("items") or []:
            if it.get("route") == "excluded":
                continue
            if not (it.get("title") or "").strip():
                continue
            seen[it["id"]] = it
    return seen


def main():
    ap = argparse.ArgumentParser(description="L1.5 译文流水线：预生成标题/摘要对照译文")
    ap.add_argument("--batch", type=int, default=10, help="每批条目数（默认 10）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（试跑）")
    ap.add_argument("--date", help="只处理某个自然日")
    ap.add_argument("--workers", type=int, default=3, help="并发批数（默认 3）")
    ap.add_argument("--dry-run", action="store_true", help="只报数量，不发请求")
    args = ap.parse_args()

    table = load_table()
    items = collect_items(args.date)

    todo = []
    for iid, it in items.items():
        lang = lang_of(it.get("title") or "")
        h = src_hash(it)
        rec = table.get(iid)
        if rec and rec.get("src_hash") == h:
            continue                       # 原文未变
        if rec and rec.get("trans", {}).get("reviewed"):
            continue                       # 人工已定稿，不覆盖
        todo.append({
            "id": iid,
            "lang": lang,
            "tgt": "zh" if lang == "en" else "en",
            "title": (it.get("title") or "").strip(),
            "summary": (it.get("summary") or "").strip(),
            "full": (it.get("summary_full") or "").strip(),
            "hash": h,
        })

    if args.limit:
        todo = todo[:args.limit]
        print("（--limit 生效，本轮处理 %d 条）" % len(todo))
    if not todo:
        print("无需翻译，译表已是最新。")
        return 0

    key = load_api_key()
    if not key and not args.dry_run:
        print("未取得 API Key：请设置环境变量 AGNES_API_KEY，"
              "或在项目根的 config.json 中填写 api_key。",
              file=sys.stderr)
        return 2

    # 超长摘要**分段翻译**：按句边界切段、逐段独立翻译后按序拼接（早先把原文硬截到
    # 500 字符再送译，导致长摘要的译文只覆盖开头一小段）。仍有剩余未译时在译表记
    # full_partial，前端据此明示覆盖范围。
    units = []          # 真正发请求的最小单位（1 主单元 + N 段单元）
    partial_ids = set()
    for t in todo:
        segs = split_long(t["full"])
        if len(segs) > MAX_SEG:
            partial_ids.add(t["id"])
        units.append({"id": t["id"], "tgt": t["tgt"], "title": t["title"],
                      "summary": t["summary"], "full": "", "hash": t["hash"],
                      "lang": t["lang"], "owner": t["id"]})
        for si, seg in enumerate(segs[:MAX_SEG], start=1):
            units.append({"id": "%s#f%d" % (t["id"], si), "tgt": t["tgt"], "title": "",
                          "summary": "", "full": seg, "hash": t["hash"],
                          "lang": t["lang"], "owner": t["id"]})
    print("条目总数 %d · 已有译文 %d · 待译 %d（分段后请求单元 %d）" %
          (len(items), len(items) - len(todo), len(todo), len(units)))
    if args.limit:
        todo = todo[:args.limit]
        print("（--limit 生效，本轮处理 %d 条）" % len(todo))
    if not todo:
        print("无需翻译，译表已是最新。")
        return 0
    if args.dry_run:
        return 0

    groups = {}
    for u in units:
        groups.setdefault(u["tgt"], []).append(u)
    batches = []
    for tgt, arr in groups.items():
        for i in range(0, len(arr), args.batch):
            batches.append((tgt, arr[i:i + args.batch]))
    print("批数 %d（%s）" % (len(batches),
                            " / ".join("%s→%d 单元" % (k, len(v)) for k, v in groups.items())))

    t0 = time.time()
    done = [0]
    lock = __import__("threading").Lock()
    got_by_owner = {}      # 条目 id → {title, summary, segs{序号:译文}, lost}

    def run(b):
        tgt, batch = b
        src = "en" if tgt == "zh" else "zh"
        prompt = build_prompt(batch, src, tgt)
        for attempt in range(3):
            try:
                raw = chat_json(SYS, prompt, key)
                obj = extract_json(raw)
                if obj and isinstance(obj, dict):
                    return batch, obj
                print("[warn] 批次 %s… 解析失败（第 %d 次）" %
                      (batch[0]["id"], attempt + 1), file=sys.stderr)
            except urllib.error.HTTPError as e:
                print("[warn] 批次 %s… HTTP %s（第 %d 次）" %
                      (batch[0]["id"], e.code, attempt + 1), file=sys.stderr)
            except Exception as e:
                print("[warn] 批次 %s… %s（第 %d 次）" %
                      (batch[0]["id"], e, attempt + 1), file=sys.stderr)
            time.sleep(2 + attempt * 3)
        return batch, None

    fail = 0
    with futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for batch, obj in ex.map(run, batches):
            if not obj:
                fail += len(batch)
                continue
            for u in batch:
                got = obj.get(u["id"])
                if not isinstance(got, dict):
                    fail += 1
                    continue
                slot = got_by_owner.setdefault(
                    u["owner"], {"title": "", "summary": "", "segs": {}, "lost": 0})
                if u["title"] or u["summary"]:
                    slot["title"] = (got.get("title") or "").strip()
                    slot["summary"] = (got.get("summary") or "").strip()
                else:
                    txt = (got.get("full") or "").strip()
                    if txt:
                        slot["segs"][int(u["id"].rsplit("#f", 1)[1])] = txt
                    else:
                        slot["lost"] += 1
                with lock:
                    done[0] += 1
                    if done[0] % 100 == 0:
                        print("  已处理 %d/%d 单元（%.0fs）"
                              % (done[0], len(units), time.time() - t0), file=sys.stderr)
    # 汇总：按条目写回译表（失败条目不覆盖旧值，重跑只补这些）
    stamp = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
    ok = 0
    for t in todo:
        slot = got_by_owner.get(t["id"])
        if not slot or not (slot["title"] or slot["summary"] or slot["segs"]):
            continue
        rec = {
            "lang": t["lang"],
            "title_alt": slot["title"],
            "summary_alt": slot["summary"],
            "full_alt": "".join(slot["segs"][k] for k in sorted(slot["segs"])),
            "src_hash": t["hash"],
            "trans": {"provider": PROVIDER, "model": DEFAULT_MODEL,
                      "at": stamp, "reviewed": False},
        }
        if t["id"] in partial_ids or slot["lost"]:
            rec["full_partial"] = True      # 仍有原文未译，前端须明示覆盖范围
        table[t["id"]] = rec
        ok += 1
    save_table(table)
    print("完成：成功 %d 条 · 失败 %d 条 · 用时 %.0fs → %s"
          % (ok, fail, time.time() - t0, TABLE_PATH))
    if fail:
        print("提示：失败条目译表未更新，重跑本脚本即只补这些（增量）。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
