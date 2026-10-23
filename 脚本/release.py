#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包：把「展现文件 + 数据文件」打成可直接上静态服务器的发布包。

三种模式（对应三类更新）：
    --mode full    完整包（界面 + 全部数据）——首次部署
    --mode data    只打包数据目录——日常更新
    --mode shell   只打包界面（index.html）——界面改版

两种数据源（--source）：
    views（默认）   数据/视图/  —— 全量，历史全部随包
    publish         数据/发布/  —— 增量：窗口内数据 + **完整索引**
    两者都由 `脚本/sync_publish.py` 之外的独立流程维护：发布目录是视图目录的派生子集
    （近N 天数据 + 全量 index.json），索引给全量是为了线上保留全部历史导航，
    数据只给窗口是为了上传轻量——两者缺一不可。

产物（`发布/ai_news_daily-<打包日期>[-inc]/`）：
    index.html          部署根文档（运行态薄壳，页面装配器直接产出）
    data/views/*.json   投影数据（--ascii-only；否则同时给出中文目录名）
    release.json        发布清单（版本 + 文件 sha256 + 字节数 + 数据范围）
    部署说明.md          上线步骤 · 更新方式 · 回滚方式
    本地预览.py          零依赖静态服务（HTTP 是硬要求，file:// 会被浏览器拦住）

打包前强制校验（`--no-verify` 可跳过，不建议）：数据审计 → 投影校验 → 资产一致性。
校验不过就中止，宁可不出包，也不把有问题的数据发上线。
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 单日单窗口投影文件名（如 2026-10-11_24h.json / _48h.json）
DATA_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_\d+h\.json$")

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
VIEW_ROOT = ROOT / "数据" / "视图"
PUBLISH_ROOT = ROOT / "数据" / "发布"
RELEASE_ROOT = ROOT / "发布"
BJ = timezone(timedelta(hours=8))

PREVIEW_PY = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地预览（零依赖）：python 本地预览.py [端口]

运行态页面必须经 HTTP 访问——浏览器禁止 file:// 页面读取同目录数据文件。
"""
import functools
import http.server
import socketserver
import sys

DIRECTORY = "."
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # 预览时不做缓存，改完文件刷新即见
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


Handler.extensions_map[".json"] = "application/json"


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


with Server(("127.0.0.1", PORT), functools.partial(Handler, directory=DIRECTORY)) as httpd:
    print("预览地址：http://127.0.0.1:%d/          （Ctrl+C 退出）" % PORT)
    httpd.serve_forever()
'''

DEPLOY_DOC = """# 部署说明 · {pkg}

本包是**静态文件**：没有服务端接口、没有数据库、没有环境变量。
把 `index.html` 与数据目录按下面的相对位置放到同一目录树下即可。
带 `--ascii-only` 打包时数据目录为 `data/views/`（内容与中文目录完全一致）。

## 包内容

| 文件 | 说明 |
|---|---|
| `index.html` | 展现文件（运行态薄壳）。数据更新后刷新页面即呈现新内容，无需重新生成 |
| `index.json` | 数据索引（各日双窗口条数、最近完整日） |
| `<日期>_<窗口>.json` | 单日单窗口投影 |
| `release.json` | 发布清单（版本 + 文件 sha256 + 字节数） |
| `本地预览.py` | 零依赖静态服务，用于上线前自检 |

## 上线步骤

1. **放置文件**：把整个包上传到静态服务器、对象存储或静态托管平台，站点根目录即包目录。
   **zip 顶层必须直接是 `index.html`**（不能整套套在子目录里，否则站点根文档不存在）。
2. **设默认文档**：把 `index.html` 设为默认文档；确认 `.json` 的 Content-Type 为 `application/json`。
3. **自检**：浏览器打开站点，确认首屏落在「最近完整自然日」、日期与窗口切换可用、
   页首**没有**「数据源不可读」提示条。

### 上线前本地自检（必做）

```
python 本地预览.py 8765
# 浏览器打开 http://127.0.0.1:8765/
```

### nginx 参考

```nginx
server {{
  listen 80;
  root   /var/www/ai-daily;          # 指向本包目录
  index  index.html;
  location = /index.html {{ add_header Cache-Control "no-cache"; }}   # 改版立即生效
  location /data/ {{ add_header Cache-Control "max-age=300"; }}      # 历史文件内容不变，可缓存
  types {{ application/json json; }}
}}
```

---

## 更新方式

| 更新类型 | 需要上传 | 命令（在项目根目录） |
|---|---|---|
| 首次部署 / 大版本 | 整包 | `python 脚本/release.py` |
| 日常数据更新 | 数据目录 | `python 脚本/release.py --mode data` |
| 界面改版 | `index.html` | `python 脚本/release.py --mode shell` |

- **先传数据、后传界面**；上传时建议先传临时名再改名，避免访问者读到半个JSON。
- 索引 `index.json` 每次更新必换；历史日期的投影文件一经生成内容即不变，可增量同步。

## 回滚

用上一版包的对应文件覆盖即可，数据与界面可分别回滚、互不牵连。

## 页面提示「数据源不可读」？

运行态页面必须经 **HTTP** 访问。直接双击 `index.html`（`file://`）时，浏览器安全策略禁止
页面读取同目录数据文件，页面会按设计降级为「内联首屏快照 + 说明提示」——这是预期行为，
不是包的问题。若经 HTTP 访问仍出现该提示，请检查数据目录是否与 `index.html` 处于同一目录树下。

---
本包由 `脚本/release.py` 生成（契约版本 {spec}）。
"""


def remove_tree(path):
    """删除目录树，不依赖系统回收站。

    打包同一天重跑是常规操作（增量包目录名按日期固定），必须能覆盖旧目录。
    但部分环境会把 shutil.rmtree 重定向到回收站，回收站不可用时直接抛错，
    结果是**目录已被删掉、脚本却按失败退出**，后续步骤全不执行。
    故这里先用 rmtree，捕获异常后再确认目录是否已消失：已消失即视为成功。
    """
    try:
        shutil.rmtree(path)
        return
    except OSError as e:
        if not path.exists():
            return          # 实际已删除，只是回收站那步报错
        raise SystemExit("清理旧包目录失败：%s（%s）" % (path, e))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(name, args):
    """跑一个校验/装配脚本，返回 (ok, 末行输出)。"""
    r = subprocess.run([sys.executable, str(SCRIPT_DIR / name)] + args,
                       capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return r.returncode == 0, (out[-1] if out else "")


def preflight(verbose=True):
    """打包前强制校验：数据 → 投影 → 资产一致。"""
    checks = [
        ("数据审计", "validate_data.py", []),
        ("投影校验", "validate_view.py", []),
        ("资产一致性", "gen_runtime_assets.py", ["--check"]),
    ]
    bad = []
    for label, script, args in checks:
        ok, tail = run(script, args)
        if verbose:
            print("   %s %-6s %s" % ("OK  " if ok else "FAIL", label, tail[:70]))
        if not ok:
            bad.append(label)
    return bad


def load_index(src):
    p = src / "index.json"
    if not p.exists():
        raise SystemExit("缺少 %s —— 先运行 view_projection.py%s"
                         % (p, "（发布目录为空时先跑 sync_publish.py）"
                            if src == PUBLISH_ROOT else ""))
    return json.loads(p.read_text(encoding="utf-8"))


def build(mode, out_dir, zip_it, verify, ascii_dir=False, src=None):
    src = src or VIEW_ROOT
    index = load_index(src)
    days = sorted((index.get("days") or {}).keys())
    if not days:
        raise SystemExit("投影索引为空：%s" % (src / "index.json"))

    if out_dir.exists():
        remove_tree(out_dir)
    out_dir.mkdir(parents=True)

    files = []
    if mode in ("full", "shell"):
        ok, tail = run("render_dashboard.py",
                       ["--mode", "runtime", "--out", str(out_dir), "--name", "index.html"])
        if not ok:
            raise SystemExit("装配 index.html 失败：%s" % tail)
        files.append(out_dir / "index.html")

    # 数据目录：`--ascii-only` 时输出 `data/views/`。部分静态托管平台对 URL 做编码与重写，
    # 中文目录名 `数据/视图/` 在托管环境可能取不到数（本地可用）；两个目录内容一致，
    # 前端 BASE_CANDIDATES 逐个探测，ASCII 候选已排最前（本地中文目录仍由后面的候选兜住）。
    # ASCII 版包体积约为一半。
    ascii_only = ascii_dir
    if ascii_only:
        data_dirs = [("data", "views")]
    else:
        data_dirs = [("数据", "视图"), ("data", "views")]
    if mode in ("full", "data"):
        for seg in data_dirs:
            dst = out_dir.joinpath(*seg)
            dst.mkdir(parents=True, exist_ok=True)
            for f in sorted(src.glob("*.json")):
                if f.name.endswith(".tmp"):
                    continue
                shutil.copy2(f, dst / f.name)
                files.append(dst / f.name)
    else:
        for seg in data_dirs:
            stale = out_dir.joinpath(*seg)
            if stale.exists():
                shutil.rmtree(stale, ignore_errors=True)

    # 交付辅助文件：清单 / 说明 / 预览器
    (out_dir / "本地预览.py").write_text(PREVIEW_PY, encoding="utf-8", newline="\n")
    (out_dir / "部署说明.md").write_text(
        DEPLOY_DOC.format(pkg=out_dir.name, spec=index.get("spec_version", "")),
        encoding="utf-8", newline="\n")
    files += [out_dir / "本地预览.py", out_dir / "部署说明.md"]

    # 包内实际带的数据日期（可能窄于 index.json 列出的日期：增量包的窗口外日期
    # 要靠补打并部署全量包才会刷新为最新内容）。两者必须分开记，合并会谎报包的覆盖范围。
    # 按命名匹配而非定长下标——文件名长度会随窗口标识变化，定长判断曾静默失配。
    packaged_days = sorted({m.group(1) for f in files
                            for m in [DATA_NAME.match(f.name)] if m})

    manifest = {
        "package": out_dir.name,
        "mode": mode,
        "source": "publish" if src == PUBLISH_ROOT else "views",
        "built_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "spec_version": index.get("spec_version"),
        "schema": index.get("schema"),
        "data_dates": {"first": days[0], "last": days[-1], "count": len(days)},
        "packaged_data_dates": {
            "first": packaged_days[0] if packaged_days else None,
            "last": packaged_days[-1] if packaged_days else None,
            "count": len(packaged_days),
        },
        "latest_complete_day": index.get("latest"),
        "newest_day": index.get("newest"),
        "coverage_until": index.get("coverage_until"),
        "files": [{
            "path": str(f.relative_to(out_dir)).replace("\\", "/"),
            "bytes": f.stat().st_size,
            "sha256": sha256(f),
        } for f in sorted(files)],
    }
    manifest["total_bytes"] = sum(f["bytes"] for f in manifest["files"])
    mp = out_dir / "release.json"
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                  encoding="utf-8", newline="\n")

    # 自校验：清单里的 sha256 必须与实际文件一致
    for ent in manifest["files"]:
        if sha256(out_dir / ent["path"]) != ent["sha256"]:
            raise SystemExit("发布清单自校验失败：%s" % ent["path"])

    zp = None
    if zip_it:
        zp = out_dir.with_suffix(".zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out_dir.rglob("*")):
                if f.is_file():
                    # 相对**包目录本身**平铺写入：zip 解开后 index.html 必须在顶层。
                    # 若写成 relative_to(out_dir.parent) 会保留外层目录名
                    # （ai_news_daily-<日期>/index.html），站点根文档不存在 → 整站 404。
                    z.write(f, f.relative_to(out_dir))
    return manifest, zp


def main():
    ap = argparse.ArgumentParser(description="一键打包发布（静态文件）")
    ap.add_argument("--mode", choices=("full", "data", "shell"), default="full",
                    help="full=界面+数据 / data=只数据 / shell=只界面")
    ap.add_argument("--out", help="包目录，默认 发布/ai_news_daily-<日期>[-mode]")
    ap.add_argument("--zip", action="store_true", help="额外产出 zip")
    ap.add_argument("--no-verify", action="store_true", help="跳过打包前校验（不建议）")
    ap.add_argument("--ascii-only", action="store_true",
                    help="数据目录只用 ASCII 名（data/views/），不重复产出中文目录；"
                         "包体积约减半，托管环境取数更稳")
    ap.add_argument("--source", choices=("publish", "views"), default="views",
                    help="publish=取 数据/发布/（增量：窗口内数据 + 完整索引，日常用）；"
                         "views=取 数据/视图/（全量，默认）")
    args = ap.parse_args()

    src = PUBLISH_ROOT if args.source == "publish" else VIEW_ROOT
    if args.source == "publish" and not (src / "index.json").exists():
        raise SystemExit("发布目录为空：%s —— 先运行 `python 脚本/sync_publish.py`"
                         % src)

    if not args.no_verify:
        print("== 打包前校验 ==")
        bad = preflight()
        if bad:
            raise SystemExit("校验未通过（%s）——已中止打包。"
                             "确需跳过请加 --no-verify" % "、".join(bad))

    day = datetime.now(BJ).strftime("%Y%m%d")
    suffix = "" if args.mode == "full" else "-" + args.mode
    if args.source == "publish" and args.mode == "full":
        suffix = "-inc"
    out_dir = Path(args.out) if args.out else RELEASE_ROOT / ("ai_news_daily-%s%s" % (day, suffix))

    print("== 打包（%s · 数据源 %s）==" % (args.mode, args.source))
    manifest, zp = build(args.mode, out_dir, args.zip, not args.no_verify,
                         args.ascii_only, src=src)
    print("包目录：%s" % out_dir)
    print("  文件 %d 个 · 合计 %.1f KB · 索引列出 %s ~ %s（%d 天）"
          % (len(manifest["files"]), manifest["total_bytes"] / 1024,
             manifest["data_dates"]["first"], manifest["data_dates"]["last"],
             manifest["data_dates"]["count"]))
    pk = manifest["packaged_data_dates"]
    if pk["count"] != manifest["data_dates"]["count"]:
        print("  本包实际带数据 %s ~ %s（%d 天）；其余日期沿用线上已上传的同路径文件"
              % (pk["first"], pk["last"], pk["count"]))
    print("  契约 %s · 规范 %s · 最近完整日 %s"
          % (manifest["schema"], manifest["spec_version"],
             manifest["latest_complete_day"]))
    if zp:
        print("压缩包：%s（%.1f KB）" % (zp, zp.stat().st_size / 1024))
    print("下一步：把包目录上传到静态服务器/对象存储；上线前可用 "
          "`python 本地预览.py 8765` 自检（运行态必须经 HTTP）。")


if __name__ == "__main__":
    main()
