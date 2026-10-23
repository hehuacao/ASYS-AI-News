#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步发布目录：把视图目录最近 N 天的投影 + 完整索引复制到 数据/发布/。

用法：
    python 脚本/sync_publish.py# 默认最近 7 天
    python 脚本/sync_publish.py --days 14   # 改窗口天数

产出：
    数据/发布/index.json          —— 完整索引，列出视图目录的**全部**日期
    数据/发布/<日期>_<窗口>.json  —— 仅窗口内的数据文件

为什么索引是全量、数据是窗口：
    发布包靠 Pages 的内容哈希去重与资产合并，窗口外的历史文件一旦上传过就一直可访问；
    而页面的日期列表完全由index.json 决定（render_dashboard.py 的 applyIndex）。
    因此索引给全量（线上保留全部历史导航）、数据只给窗口（上传轻量），两者缺一不可。

本目录是纯派生产物：可随时删除重建，唯一事实源始终是 数据/视图/。
"""
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEW_ROOT = ROOT / "数据" / "视图"
PUBLISH_ROOT = ROOT / "数据" / "发布"

# 只清本模块管辖的命名，绝不触碰其他文件
DATA_GLOB = "20??-??-??_*h.json"


def atomic_copy(src, dst):
    """同目录临时文件 + os.replace 原子覆盖，避免部署读到半个 JSON。"""
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def sync(days_window=7, verbose=True):
    idx = VIEW_ROOT / "index.json"
    if not idx.exists():
        raise SystemExit("缺少 %s —— 先运行 view_projection.py" % idx)

    import json
    index = json.loads(idx.read_text(encoding="utf-8"))
    all_days = sorted((index.get("days") or {}).keys())
    if not all_days:
        raise SystemExit("投影索引为空：%s" % idx)

    keep = set(all_days[-days_window:]) if days_window > 0 else set(all_days)
    PUBLISH_ROOT.mkdir(parents=True, exist_ok=True)

    wanted, copied = set(), []
    for day in sorted(keep):
        for f in sorted(VIEW_ROOT.glob("%s_*h.json" % day)):
            atomic_copy(f, PUBLISH_ROOT / f.name)
            wanted.add(f.name)
            copied.append(f.name)

    # 索引始终复制全量版本（页面日期列表由它决定）
    atomic_copy(idx, PUBLISH_ROOT / "index.json")

    # 清理窗口外的陈旧数据文件（只按本模块的命名清，不碰 index.json 与其他文件）
    pruned = []
    for f in sorted(PUBLISH_ROOT.glob(DATA_GLOB)):
        if f.name not in wanted:
            f.unlink()
            pruned.append(f.name)

    total = sum((PUBLISH_ROOT / n).stat().st_size for n in wanted)
    if verbose:
        print("== 发布目录已同步（窗口 %d 天）==" % len(keep))
        print("   数据文件 %d 份（%s ~ %s）· %.0f KB"
              % (len(wanted), min(keep), max(keep), total / 1024))
        print("   index.json 为完整索引，列出全部 %d 天 —— 线上保留全量历史导航"
              % len(all_days))
        if pruned:
            print("   清理窗口外：%s" % "、".join(pruned))
    return {"days": sorted(keep), "files": sorted(wanted), "pruned": pruned}


def main():
    ap = argparse.ArgumentParser(description="同步发布目录（视图目录最近 N 天 + 完整索引）")
    ap.add_argument("--days", type=int, default=7,
                    help="数据文件窗口天数，默认 7；0 表示全部（等同全量）")
    args = ap.parse_args()
    if args.days < 0:
        raise SystemExit("--days 不能为负")
    sync(args.days)


if __name__ == "__main__":
    main()