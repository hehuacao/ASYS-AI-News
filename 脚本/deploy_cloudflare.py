#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署发布包到 Cloudflare Pages（文件上传，不依赖 Git 集成）。

用法：
    python 脚本/deploy_cloudflare.py# 部署当前最新的整包
    python 脚本/deploy_cloudflare.py --dir 发布/ai_news_daily-20261018-inc
    python 脚本/deploy_cloudflare.py --preview# 部署到预览环境而非生产
    python 脚本/deploy_cloudflare.py --prune-only# 不部署，只清理旧部署记录
    python 脚本/deploy_cloudflare.py --keep-deployments 5            # 保留最近 5 条（默认 3）

凭据来自 配置/cloudflare_deploy.json（项目内、不入库），只读入内存并经环境变量
传给 wrangler，不写入命令行参数、不落盘、不打印。

产物：一次 Pages 部署，随后清理旧部署记录（只留最近 --keep-deployments 条）。
上传走内容哈希去重，未变更文件不会重复传输，历史资产由平台保留
——因此日常部署只带增量数据也不会丢线上历史。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_ROOT = ROOT / "发布"
CONFIG = ROOT / "配置" / "cloudflare_deploy.json"
API = "https://api.cloudflare.com/client/v4"
DEFAULT_KEEP_DEPLOYMENTS = 3


def load_config():
    if not CONFIG.exists():
        raise SystemExit("缺少部署配置 %s" % CONFIG)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for k in ("account_id", "api_token", "project_name"):
        if not cfg.get(k):
            raise SystemExit("配置缺少字段 %s：%s" % (k, CONFIG))
    return cfg


def latest_package():
    """最新整包目录：取 发布/ 下 mtime 最新的 ai_news_daily-* 目录。"""
    if not RELEASE_ROOT.is_dir():
        raise SystemExit("没有发布目录：%s —— 先运行 release.py" % RELEASE_ROOT)
    cands = [p for p in RELEASE_ROOT.glob("ai_news_daily-*")
             if p.is_dir() and (p / "index.html").exists()]
    if not cands:
        raise SystemExit("%s 下没有可用发布包（需含 index.html）" % RELEASE_ROOT)
    return max(cands, key=lambda p: p.stat().st_mtime)


PKG_DATE_RE = re.compile(r"^ai_news_daily-(\d{8})(-inc)?$")


def remove_tree(path):
    """删除目录树，不依赖系统回收站。

    部分环境把 shutil.rmtree 重定向到回收站，回收站不可用时直接抛错，
    但目录其实已被删除。此时若按失败上报，会把「已清理」误报成「清理失败」。
    故捕获异常后再确认目录是否已消失：已消失即视为成功。
    """
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        return not path.exists()


def prune_old_packages(keep_dir):
    """删除日期早于 keep_dir 的旧发布包（目录 + 同名 .zip）。

    只按包名里的日期判定，**同日的另一个类型（全量 / -inc）一律保留**——
    它们体积都不大，且全量包是规则变更后补打的底通，误删的代价远大于收益。
    删除是不可逆操作，故先确认目标绝对路径确实位于 发布/ 下且名称严格匹配。
    """
    m = PKG_DATE_RE.match(keep_dir.name)
    if not m:
        raise SystemExit("包名不符合 ai_news_daily-<YYYYMMDD>[-inc]：%s" % keep_dir.name)
    keep_day = m.group(1)

    root = RELEASE_ROOT.resolve()
    victims = []
    for p in sorted(RELEASE_ROOT.iterdir()):
        if p.is_dir():
            mm = PKG_DATE_RE.match(p.name)
            if mm and mm.group(1) < keep_day:
                victims.append(p)
        elif p.is_file() and p.suffix == ".zip":
            mm = PKG_DATE_RE.match(p.stem)
            if mm and mm.group(1) < keep_day:
                victims.append(p)

    if not victims:
        print("   发布目录：只有 %s 及其同日包，无旧包可清。" % keep_dir.name)
        return 0

    print("   清理旧发布包（日期早于 %s）：" % keep_day)
    done = 0
    for v in victims:
        rp = v.resolve()
        # 边界自检：必须在 发布/ 之内、且不是 发布/ 本身
        if rp == root or root not in rp.parents:
            print("   跳过（目标越出发布目录）：%s" % rp)
            continue
        try:
            if rp.is_dir():
                mb = sum(f.stat().st_size for f in rp.rglob("*") if f.is_file()) / 1048576
                if not remove_tree(rp):
                    print("   删除失败 %s/：目录仍存在" % rp.name)
                    continue
                print("   已删除 %s/（%.1f MB）" % (rp.name, mb))
            else:
                mb = rp.stat().st_size / 1048576
                rp.unlink()
                print("   已删除 %s（%.1f MB）" % (rp.name, mb))
            done += 1
        except OSError as e:
            print("   删除失败 %s：%s" % (rp.name, e))
    print("   已清理 %d/%d 项。" % (done, len(victims)))
    return done


def find_npx():
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit("未找到 npx —— 部署需 Node.js（wrangler 通过 npx 调用）")
    return npx


def deploy(pkg_dir, cfg, preview=False):
    if not (pkg_dir / "index.html").exists():
        raise SystemExit("包内缺少 index.html：%s" % pkg_dir)

    env = dict(os.environ)
    env["CLOUDFLARE_API_TOKEN"] = cfg["api_token"]   # 凭据只走环境变量
    if cfg.get("account_id"):
        # 必须显式传 account_id：账户范围的 Token 调 /accounts 返回空列表，
        # wrangler 自动获取账户 ID 会失败（报 9109 / "Failed to automatically
        # retrieve account IDs"），部署直接退出。
        env["CLOUDFLARE_ACCOUNT_ID"] = cfg["account_id"]

    args = [find_npx(), "--yes", "wrangler", "pages", "deploy", str(pkg_dir),
            "--project-name=%s" % cfg["project_name"],
            "--commit-dirty=true"]
    if preview:
        args.append("--branch=preview")
    else:
        args.append("--branch=%s" % cfg.get("production_branch", "main"))

    print("== 部署 Cloudflare Pages ==")
    print("   项目 %s · 环境 %s · 包 %s"
          % (cfg["project_name"], "预览" if preview else "生产", pkg_dir.name))
    print("   运行：npx wrangler pages deploy …（凭据经环境变量传入，不落盘）")
    r = subprocess.run(args, env=env)
    if r.returncode != 0:
        raise SystemExit("部署失败（wrangler 退出码 %d）" % r.returncode)
    if preview:
        print("预览部署完成（不影响生产站点）。地址见上方 wrangler 输出的 Deployment URL。")
    else:
        host = cfg.get("domain") or ("%s.pages.dev" % cfg["project_name"])
        print("部署完成：https://%s/" % host)
    return 0

# 线上字节比对必须带浏览器 UA：托管侧按 UA 拦截，Python 默认 UA 会被 403
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _fetch_bytes(url, timeout=30):
    """取回线上文件内容，返回 (status, content_type, body)。"""
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA,
                                               "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, (r.headers.get("Content-Type") or ""), r.read()


def verify_deployed(pkg_dir, cfg, is_incremental=False):
    """部署后校验线上数据文件是否真的可取。

    托管平台对不存在的路径返回 200 + 首页字节（HTML 回退伪 200），只看状态码
    必然漏判 —— 必须比对 content-type 与字节数。

    增量包不含窗口外日期，其线上文件必然退化为 HTML 回退（单个部署 = 该目录
    manifest，跨部署不合并，窗口外文件靠全量包保活），故只报告不中止；
    全量包必须覆盖索引中的全部日期，否则说明发布不完整。
    """
    host = cfg.get("domain") or ("%s.pages.dev" % cfg["project_name"])
    views_dir = pkg_dir / "data" / "views"
    idx_path = views_dir / "index.json"
    if not idx_path.exists():
        print("== 部署后校验：包内无 index.json，跳过 ==")
        return 0
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    days = idx.get("days") or {}
    pkg_files = {f.name for f in views_dir.glob("*.json")}
    in_pkg, out_pkg = [], []
    for d, meta in sorted(days.items()):
        for w in (meta.get("windows") or {}):
            name = "%s_%sh.json" % (d, w)
            (in_pkg if name in pkg_files else out_pkg).append(name)

    base = "https://%s/data/views/" % host
    bad_in, bad_out, ok = [], [], 0
    for name in in_pkg + out_pkg:
        local = views_dir / name
        try:
            status, ctype, body = _fetch_bytes(base + name)
        except Exception as e:
            (bad_in if name in in_pkg else bad_out).append((name, "请求失败：%s" % e))
            continue
        if "json" not in (ctype or "").lower():
            (bad_in if name in in_pkg else bad_out).append(
                (name, "content-type=%s（HTML 回退伪 200）" % ctype))
            continue
        if local.exists() and len(body) != local.stat().st_size:
            (bad_in if name in in_pkg else bad_out).append(
                (name, "字节数不一致：线上 %d / 本地 %d"
                 % (len(body), local.stat().st_size)))
            continue
        ok += 1

    print("== 部署后校验 ==")
    print("   线上可取 %d 个（包内 %d / 窗口外 %d）" % (ok, len(in_pkg), len(out_pkg)))
    if bad_in:
        print("   ❌ 包内文件异常 %d 个：" % len(bad_in))
        for n, r in bad_in[:10]:
            print("      %s — %s" % (n, r))
        raise SystemExit("部署后校验不通过：包内数据文件在线上不可取。")
    if bad_out:
        if is_incremental:
            print("   ⚠️ 窗口外文件退化 %d 个（增量包不含这些日期，属预期）："
                  % len(bad_out))
            for n, r in bad_out[:6]:
                print("      %s — %s" % (n, r))
            print("      → 需补打并部署全量包，窗口外日期才会恢复正常。")
        else:
            print("   ❌ 窗口外文件异常 %d 个：" % len(bad_out))
            for n, r in bad_out[:10]:
                print("      %s — %s" % (n, r))
            raise SystemExit("部署后校验不通过：全量包应覆盖索引中的全部日期。")
    print("   ✅ 校验通过")
    return 0


def _api(cfg, method, path):
    """调 Cloudflare API。凭据只进请求头，不进 URL、不打印。"""
    url = API + path
    req = urllib.request.Request(url, method=method,
                                 headers={"Authorization": "Bearer %s" % cfg["api_token"],
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit("Cloudflare API %s %s 返回 HTTP %d：%s"
                         % (method, path, e.code, body[:300]))


def list_deployments(cfg, per_page=25):
    # 实测该端点 per_page 上限为 25（传 50 返回 8000024 Invalid list options），
    # 故上限写死并夹紧；条数不够时靠 result_info.total_count 判断是否还有下一页。
    per_page = max(1, min(per_page, 25))
    path = ("/accounts/%s/pages/projects/%s/deployments?per_page=%d"
            % (cfg["account_id"], cfg["project_name"], per_page))
    d = _api(cfg, "GET", path)
    if not d.get("success"):
        raise SystemExit("读取部署列表失败：%s" % json.dumps(d.get("errors"), ensure_ascii=False))
    out = list(d.get("result") or [])
    total = ((d.get("result_info") or {}).get("total_count") or len(out))
    page = 2
    while len(out) < total:
        p2 = "%s&page=%d" % (path, page)
        d2 = _api(cfg, "GET", p2)
        if not d2.get("success"):
            break
        batch = d2.get("result") or []
        if not batch:
            break
        out.extend(batch)
        page += 1
    return out


def current_production_id(cfg):
    """当前生产分支指向的部署 id —— 任何情况下都不删。

    latest_deployment 与 canonical_deployment 都取（不同项目可能只回填其一），
    两个都返回才认为识别成功；都拿不到时返回 None，调用方会退化为「不额外保护」，
    但保留窗口仍按时间倒序取最新 N 条，不会误删正在用的版本。
    """
    path = "/accounts/%s/pages/projects/%s" % (cfg["account_id"], cfg["project_name"])
    d = _api(cfg, "GET", path)
    if not d.get("success"):
        raise SystemExit("读取项目信息失败：%s" % json.dumps(d.get("errors"), ensure_ascii=False))
    r = d.get("result") or {}
    ids = {((r.get("latest_deployment") or {}).get("id")),
           ((r.get("canonical_deployment") or {}).get("id"))}
    ids.discard(None)
    return ids or None


def prune_deployments(cfg, keep):
    """只留最近 keep 条部署记录（按创建时间倒序）。

    硬保护：当前生产部署永不删除——删掉它会让线上站点失去当前版本。
    删除失败不视为致命：部署记录清理是 housekeeping，不该让每日链路因它中断。
    """
    deps = list_deployments(cfg)
    if not deps:
        print("== 清理部署记录 ==\n   没有部署记录，无需清理。")
        return 0
    deps.sort(key=lambda x: x.get("created_on") or "", reverse=True)
    keep_ids = {d["id"] for d in deps[:keep]}
    protect = current_production_id(cfg) or set()
    keep_ids |= protect

    victims = [d for d in deps if d["id"] not in keep_ids]
    print("== 清理部署记录 ==")
    print("   共 %d 条，保留最近 %d 条%s"
          % (len(deps), keep, "（含当前生产部署）" if protect else ""))
    if not victims:
        print("   无需删除。")
        return 0

    ok = 0
    for d in victims:
        did = d["id"]
        if did in protect:
            continue
        path = ("/accounts/%s/pages/projects/%s/deployments/%s"
                % (cfg["account_id"], cfg["project_name"], did))
        # force=true：允许删除带活动别名的非生产部署（预览分支会占别名）
        path += "?force=true"
        try:
            r = _api(cfg, "DELETE", path)
            if r.get("success"):
                ok += 1
                print("   已删除 %s %s %s"
                      % (did[:8], d.get("environment"), (d.get("created_on") or "")[:19]))
            else:
                print("   删除失败 %s：%s"
                      % (did[:8], json.dumps(r.get("errors"), ensure_ascii=False)[:160]))
        except SystemExit as e:
            print("   %s" % e)
    print("   已删除 %d/%d 条。" % (ok, len(victims)))
    return ok


def main():
    ap = argparse.ArgumentParser(description="部署发布包到 Cloudflare Pages")
    ap.add_argument("--dir", help="包目录，默认 发布/ 下最新的整包")
    ap.add_argument("--preview", action="store_true", help="部署到预览环境")
    ap.add_argument("--prune-only", action="store_true",
                    help="不部署，只清理旧部署记录")
    ap.add_argument("--keep-deployments", type=int, default=DEFAULT_KEEP_DEPLOYMENTS,
                    help="保留最近 N 条部署记录（默认 %d）" % DEFAULT_KEEP_DEPLOYMENTS)
    ap.add_argument("--no-prune", action="store_true", help="部署后不清理部署记录")
    args = ap.parse_args()

    cfg = load_config()
    keep = max(1, args.keep_deployments)

    if not args.prune_only:
        pkg = Path(args.dir) if args.dir else latest_package()
        if not pkg.is_absolute():
            pkg = ROOT / pkg
        deploy(pkg, cfg, args.preview)
        if not args.preview:
            verify_deployed(pkg, cfg, is_incremental=pkg.name.endswith("-inc"))
        if not args.no_prune:
            print("== 清理旧发布包 ==")
            prune_old_packages(pkg)

    if not args.no_prune:
        prune_deployments(cfg, keep)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)