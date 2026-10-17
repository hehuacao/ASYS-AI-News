#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 L3 里的表现层「定义型资产」导出为前端资产（S2 支持件）。

**为什么生成而不是手写一份**
国旗画法、国家/地区中文名、信源分层名、节点名与英文名在 Python 渲染器里已有唯一
实现。前端纯函数若各自重写一遍，两份定义早晚漂移（同一面旗在两套产物里画法不同、
同一个国家两种译名）。故由本脚本从 Python **单一来源**导出
`脚本/assets/runtime_assets.js`，供前端纯函数与 Node 侧渲染共用。

导出内容（全部为「定义」，不含任何逻辑）：
  FLAG_SVGS / COUNTRY_NAMES / TIER_NAMES / NODE_META / IMPORTANCE_RANK
  + flagSvg(code, size) —— 与 Python `flag_svg` 逐字节同构的绘制函数

用法：
    python gen_runtime_assets.py            # 生成 脚本/assets/runtime_assets.js
    python gen_runtime_assets.py --check    # 只校验磁盘文件与当前定义一致（CI 用）
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

OUT = HERE / "assets" / "runtime_assets.js"
BUNDLE = HERE / "assets" / "render_runtime.js"
FRAGMENTS = HERE / "render_fragments.js"

EXPORT = """
/* Node 侧导出（浏览器内联时 `module` 不存在，自动跳过） */
if (typeof module !== "undefined" && module.exports) {
  module.exports = { FLAG_SVGS: FLAG_SVGS, COUNTRY_NAMES: COUNTRY_NAMES,
                     TIER_NAMES: TIER_NAMES, NODE_META: NODE_META,
                     NODE_ORDER: NODE_ORDER, WEEKDAYS: WEEKDAYS,
                     UI_TEXT: UI_TEXT, SPEC_VERSION: SPEC_VERSION,
                     flagSvg: flagSvg, globeSvg: globeSvg, fixed: fixed };
}
"""

HEADER = """/* 前端资产 —— **自动生成，请勿手改**（生成器：脚本/gen_runtime_assets.py）
 *
 * 来源：render_dashboard.py 的单一实现（FLAG_SVGS / COUNTRY_NAMES / TIER_NAMES /
 * NODE_META / IMPORTANCE_RANK / flag_svg）。改动请改 Python 侧后重新生成，
 * 保证离线单文件与运行态薄壳用的是同一份定义。
 */
"""


def build():
    """读取 Python 侧定义，产出 JS 文本（确定性输出：键序固定、缩进固定）。"""
    import render_dashboard as RD

    node_meta = {k: {"name": v["name"], "en": v["en"], "desc": v["desc"],
                     "short": v["short"], "dark": v["dark"], "light": v["light"]}
                 for k, v in RD.NODE_META.items()}

    def js(obj):
        # 紧凑单行，避免体积膨胀；键序按定义顺序稳定
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    parts = [HEADER]
    parts.append("const FLAG_SVGS = %s;\n" % js(RD.FLAG_SVGS))
    parts.append("const COUNTRY_NAMES = %s;\n" % js(RD.COUNTRY_NAMES))
    parts.append("const TIER_NAMES = %s;\n" % js(RD.TIER_NAMES))
    # 界面术语表：{key: [中文, English]}，供悬停显示另一语种 / 对照模式消费
    parts.append("const UI_TEXT = %s;\n" % js(RD.UI_TEXT))
    parts.append("const NODE_META = %s;\n" % js(node_meta))
    parts.append("const NODE_ORDER = %s;\n" % js(list(RD.NODE_ORDER)))
    parts.append("const WEEKDAYS = %s;\n" % js(RD.WEEKDAYS))
    parts.append("const SPEC_VERSION = %s;\n" % js(RD.SPEC_VERSION))
    parts.append("const ICON_SOURCE = %s;\n" % js(RD.ICON_SOURCE))
    parts.append("const ICON_SPEC = %s;\n" % js(RD.ICON_SPEC))
    parts.append("const ICON_CLOCK = %s;\n" % js(RD.ICON_CLOCK))
    parts.append("""
/* 国旗 SVG：与 Python `flag_svg(code, size)` 逐字节同构（未知代码返回空串） */
function flagSvg(code, size){
  size = (size === undefined) ? 12 : size;
  const body = FLAG_SVGS[code || ""];
  if (!body) return "";
  const h = Math.round(size * 2 / 3);
  return '<svg class="flag" viewBox="0 0 24 16" width="' + size + '" height="' + h +
         '" aria-hidden="true" focusable="false">' + body + "</svg>";
}

/* 全球地域徽标：与 Python `globe_svg(size)` 逐字节同构 */
function globeSvg(size){
  size = (size === undefined) ? 16 : size;
  return '<svg class="globe" viewBox="0 0 24 24" width="' + size + '" height="' + size +
         '" fill="none" stroke="currentColor" stroke-width="1.5" ' +
         'stroke-linecap="round" aria-hidden="true" focusable="false">' +
         '<circle cx="12" cy="12" r="8.6"/>' +
         '<ellipse cx="12" cy="12" rx="8.6" ry="3.6"/>' +
         '<path d="M12 3.4c-2.6 3.4-2.6 13.8 0 17.2' +
         'M12 3.4c2.6 3.4 2.6 13.8 0 17.2"/></svg>';
}

/* 百分比格式化：与 Python "%.Nf" 同语义（对 double 精确值做四舍六入五成双，
   JS 的 toFixed 在半值处「远离零」取舍，与 Python 不同，故显式实现） */
function fixed(x, digits){
  const f = Math.pow(10, digits), scaled = x * f;
  const fl = Math.floor(scaled), frac = scaled - fl;
  let r;
  if (Math.abs(frac - 0.5) < 1e-9) r = (fl % 2 === 0) ? fl : fl + 1;
  else r = Math.round(scaled);
  return (r / f).toFixed(digits);
}
""")
    return "\n".join(parts) + EXPORT


def build_bundle(assets_text):
    """打包件 = 资产 + 前端渲染纯函数（`render_fragments.js`）。

    页面内联与 Node 侧逐条比对都用这一个文件：一条实现路径，两种用法。
    """
    frag = FRAGMENTS.read_text(encoding="utf-8")
    tail = """
/* Node 侧导出：渲染纯函数（浏览器内联时 `module` 不存在，自动跳过） */
if (typeof module !== "undefined" && module.exports) {
  module.exports.Fragments = FRAGMENTS;
}
"""
    return assets_text + "\n\n" + frag + tail


def main():
    ap = argparse.ArgumentParser(description="导出前端资产（单一来源 = render_dashboard.py）")
    ap.add_argument("--check", action="store_true", help="只校验是否与当前定义一致")
    args = ap.parse_args()
    text = build()
    bundle = build_bundle(text)
    if args.check:
        ok = True
        for p, want in ((OUT, text), (BUNDLE, bundle)):
            cur = p.read_text(encoding="utf-8") if p.exists() else ""
            if cur != want:
                print("前端资产已过期——请运行：python 脚本/gen_runtime_assets.py")
                ok = False
        if ok:
            print("前端资产与 Python 定义一致：%s / %s" % (OUT.name, BUNDLE.name))
            return
        raise SystemExit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # 显式 LF：Windows 下 write_text 会写成 CRLF，会让「基于 \n 的样式校验」与逐字节比对失真
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    with open(BUNDLE, "w", encoding="utf-8", newline="\n") as f:
        f.write(bundle)
    print("已生成 %s（%.1f KB）" % (OUT, len(text.encode("utf-8")) / 1024))
    print("已生成 %s（%.1f KB）" % (BUNDLE, len(bundle.encode("utf-8")) / 1024))


if __name__ == "__main__":
    main()
