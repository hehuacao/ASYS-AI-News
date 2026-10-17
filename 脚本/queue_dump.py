# -*- coding: utf-8 -*-
"""导出指定自然日的待裁决队列（人工队列 + 待归类池），供内容裁决参考。

用法：python queue_dump.py 2026-10-11 [摘要最大字数，默认 90]

每行格式：[ID后4位|信源|置信度|当前节点|候选节点分值] 标题 || 摘要
裁决结论写回：数据/日报/<日期>_自然日裁决.json，再用 adjudicate.py --decisions 落盘。
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DAILY_ROOT = BASE / "数据" / "日报"


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    date_str = sys.argv[1]
    maxlen = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    path = DAILY_ROOT / ("%s.json" % date_str)
    if not path.exists():
        raise SystemExit("日报数据不存在：%s" % path)
    ds = json.loads(path.read_text(encoding="utf-8"))
    items = {it["id"]: it for it in ds["items"]}
    q = list(ds.get("review_queue") or []) + list(ds.get("unclassified_pool") or [])
    print("== %s 待裁决 %d 条（人工队列 %d / 待归类池 %d）==" % (
        date_str, len(q), len(ds.get("review_queue") or []),
        len(ds.get("unclassified_pool") or [])))
    if not q:
        print("（队列为空，无需人工裁决）")
        return
    for iid in q:
        it = items[iid]
        top = sorted((it.get("node_scores") or {}).items(),
                     key=lambda kv: -kv[1])[:2]
        tops = " ".join("%s:%s" % (k, v) for k, v in top)
        summ = (it.get("summary") or "").replace("\n", " ")[:maxlen]
        title = (it.get("title") or "").replace("\n", " ")[:110]
        print("[%s|%s|c=%s|%s|%s] %s || %s" % (
            iid[-4:], it.get("source_id"), it.get("confidence"),
            it.get("node") or "-", tops, title, summ))


if __name__ == "__main__":
    main()
