/* 真实浏览器吸顶几何断言（CDP + 本机 Chrome，零依赖）。
 *
 * 【为什么必须用真实浏览器】
 * jsdom 没有排版引擎：`getBoundingClientRect()` 恒返回 0，sticky 元素的
 * 实际停靠位置、CSS 变量写入、层间 z-index 与背景覆盖全都验不到。既有冒烟
 * 测试只对 CSS 文本做正则（「写了 top:calc(...) 就算对」），终检脚本里也
 * 没有任何吸顶断言——所以「吸顶层之间恒定 8px 透明缝隙」能一路绿灯
 * 通过：断言的是**样式声明存在**，不是**运行时几何正确**。
 *
 * 【吸顶栈只有三层（v1.20）】
 *   ① .topbar    顶栏          sticky top:0
 *   ② .axis-mini 快捷栏        fixed   top:topbar-h（迷你主轴，滚过主轴区才显示）
 *   ③ .filters   分区属性筛选栏 sticky top:topbar-h + axismini-h
 * 环节节头 .node-head **不吸顶**（v1.20 起），故不在断言栈内。
 *
 * 【断言五件事】
 *   ① 相邻吸顶层**不重叠**：gap >= 0
 *   ② 相邻吸顶层**无透明缝隙**：gap <= 1px
 *   ③ 吸顶层**背景不透明**
 *   ④ z-index 严格递减（上层压下层）
 *   ⑤ 必须真的量到「顶栏→快捷栏」「快捷栏→筛选栏」两对相邻关系（防断言空转）
 * 逐档字号 × 逐滚动位置量测（各层高度随 --fs 变化，单档必漏检）。
 *
 * 用法：node validate_sticky.js [html路径]
 * 退出码 0 = 通过；1 = 有断言失败。
 */
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

const BASE = path.resolve(__dirname, "..");
const HTML = process.argv[2] || path.join(BASE, "仪表盘", "ai_news_daily.html");
const PORT = 8961;
const CDP_PORT = 9351;
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const TOL = 1;   // 允许 1px 舍入误差

function serve() {
  return new Promise((res) => {
    const s = http.createServer((req, r) => {
      const p = path.join(path.dirname(HTML), decodeURIComponent(req.url.split("?")[0]));
      fs.readFile(p, (e, b) => {
        if (e) { r.writeHead(404); r.end(); return; }
        r.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        r.end(b);
      });
    });
    s.listen(PORT, "127.0.0.1", () => res(s));
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  if (!fs.existsSync(HTML)) { console.error("找不到产物：" + HTML); process.exit(2); }
  const server = await serve();
  const profile = path.join(os.tmpdir(), "stickyval" + Date.now());
  const chrome = spawn(CHROME, [
    "--headless=new", "--remote-debugging-port=" + CDP_PORT,
    "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
    "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
    "http://127.0.0.1:" + PORT + "/" + path.basename(HTML),
  ], { stdio: "ignore" });

  let wsUrl = null;
  for (let i = 0; i < 80 && !wsUrl; i++) {
    try {
      const list = await new Promise((res, rej) => {
        http.get("http://127.0.0.1:" + CDP_PORT + "/json/list", (r) => {
          let d = ""; r.on("data", (c) => d += c); r.on("end", () => res(JSON.parse(d)));
        }).on("error", rej);
      });
      const pg = list.find((t) => t.type === "page");
      if (pg) wsUrl = pg.webSocketDebuggerUrl;
    } catch (e) { /* 等 Chrome 起来 */ }
    if (!wsUrl) await sleep(250);
  }
  if (!wsUrl) { console.error("Chrome/CDP 未就绪"); chrome.kill(); server.close(); process.exit(2); }

  const ws = new WebSocket(wsUrl);
  let id = 0; const pend = new Map();
  const send = (m, p) => new Promise((res) => { const n = ++id; pend.set(n, res); ws.send(JSON.stringify({ id: n, method: m, params: p || {} })); });
  await new Promise((r) => ws.addEventListener("open", r));
  ws.addEventListener("message", (m) => {
    const o = JSON.parse(m.data);
    if (o.id && pend.has(o.id)) { pend.get(o.id)(o.result); pend.delete(o.id); }
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await sleep(2600);

  const ev = async (e) => {
    const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails));
    return r.result.value;
  };

  const rows = await ev(`(async () => {
    const out = [];
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    /* 三层的取法各不相同，不能一律按「sticky 是否停靠」筛：
       · .topbar    sticky top:0      —— 判| top-0 | <= 2 即停靠
       · .axis-mini fixed  top:topbar —— **恒定**停靠，无需判停靠；
         但它靠 .show 控制显隐，不可见时不参与配对（否则下方正文会被算成「缝隙」）
       · .filters   sticky top:topbar+axismini —— 判 | top-cs.top | <= 2 即停靠 */
    const read = el => {
      if (!el) return null;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (cs.display === 'none' || r.height <= 0) return null;
      const m = /rgba?\\(([^)]+)\\)/.exec(cs.backgroundColor);
      let alpha = 1;
      if (m) { const p = m[1].split(',').map(x => parseFloat(x)); if (p.length >= 4) alpha = p[3]; }
      return { top: r.top, bottom: r.bottom, h: r.height, pos: cs.position,
               z: cs.zIndex, alpha: alpha, opacity: parseFloat(cs.opacity),
               transform: cs.transform };
    };
    /* 采样必须发生在**动画静止后**。
       .axis-mini 显隐带 transform:translateY(-6px) → none 的滑入过渡，
       淡入途中它仍悬在最终位置之上（实测中途采样得到 -0.94px 的假重叠）。
       故要求 opacity 已到位且 transform 已是单位矩阵，才算「静止可测」。 */
    const atRest = info => {
      if (!info) return false;
      if (info.opacity < 0.99) return false;
      const t = info.transform;
      return !t || t === 'none' || t === 'matrix(1, 0, 0, 1, 0, 0)';
    };
    const stuck = (cs, info) => {
      if (!info || info.pos !== 'sticky') return false;
      const stop = parseFloat(cs.top);
      if (!isFinite(stop)) return false;
      if (Math.abs(info.top - stop) > 2) return false;            // 尚未停靠
      return info.bottom > 0 && info.top < innerHeight;           // 在视口内
    };

    const fsBtns = Array.from(document.querySelectorAll('#npFs [data-fs]'));
    const stops = fsBtns.length ? fsBtns : [null];
    const H = document.documentElement.scrollHeight - innerHeight;
    const nodeHeads = Array.from(document.querySelectorAll('.node-head'));

    for (const fb of stops) {
      if (fb) { fb.click(); await sleep(300); }
      const fsLabel = fb ? fb.getAttribute('data-fs') : 'default';
      for (let i = 0; i <= 24; i++) {
        const y = Math.round(H * i / 24);
        scrollTo(0, y);
        // 需长于 .axis-mini 的过渡时长（.2s），否则会采到滑入途中的位置
        await sleep(280);

        const topEl = document.querySelector('.topbar');
        const miniEl = document.querySelector('.axis-mini');
        const filtEl = document.querySelector('.filters');
        const top = read(topEl), mini = read(miniEl), filt = read(filtEl);

        const topCs = topEl && getComputedStyle(topEl);
        const filtCs = filtEl && getComputedStyle(filtEl);
        const topPinned  = stuck(topCs, top) && atRest(top);
        const filtPinned = stuck(filtCs, filt) && atRest(filt);
        const miniShown  = !!(mini && miniEl.classList.contains('show')
                              && atRest(mini) && mini.bottom > 0);

        // 配对一：顶栏 → 快捷栏（快捷栏可见时才有意义）
        if (topPinned && miniShown){
          out.push({ fs: fsLabel, y: y, pair: 'topbar|mini',
                     upper: '.topbar', lower: '.axis-mini',
                     gap: mini.top - top.bottom,
                     upperOpaque: top.alpha >= 0.95, lowerOpaque: mini.alpha >= 0.95,
                     zUpper: top.z, zLower: mini.z });
        }
        // 配对二：快捷栏 → 筛选栏（筛选栏停靠且快捷栏已显示）
        if (filtPinned && miniShown){
          out.push({ fs: fsLabel, y: y, pair: 'mini|filters',
                     upper: '.axis-mini', lower: '.filters',
                     gap: filt.top - mini.bottom,
                     upperOpaque: mini.alpha >= 0.95, lowerOpaque: filt.alpha >= 0.95,
                     zUpper: mini.z, zLower: filt.z });
        }
        // 反向断言：筛选栏停靠时，绝不允许与快捷栏竖直区间相交
        if (filtPinned && mini){
          out.push({ fs: fsLabel, y: y, pair: 'intersect',
                     upper: '.axis-mini', lower: '.filters',
                     gap: mini.bottom - filt.top,   // > 0 表示相交（重叠）
                     intersect: filt.top < mini.bottom - 1 && mini.top < filt.bottom - 1,
                     miniShown: miniShown,
                     upperOpaque: true, lowerOpaque: true,
                     zUpper: mini.z, zLower: filt.z });
        }
        // 环节节头必须完全不吸顶：任何一档字号、任何滚动位置都不应停在栈顶
        for (const nh of nodeHeads){
          const cs = getComputedStyle(nh);
          const r = nh.getBoundingClientRect();
          const stackTop = (topPinned ? top.bottom : 0);
          out.push({ fs: fsLabel, y: y, pair: 'nodehead',
                     isSticky: cs.position === 'sticky',
                     pinnedAtTop: r.height > 0 && Math.abs(r.top - stackTop) <= 2
                                  && r.bottom > 0 && r.top < innerHeight,
                     hasStuckClass: nh.classList.contains('is-stuck'),
                     upperOpaque: true, lowerOpaque: true, zUpper: 0, zLower: 0 });
        }
      }
    }
    scrollTo(0, 0);
    return out;
  })()`);

  ws.close(); chrome.kill(); server.close();

  // ---- 断言 ----
  const fails = [];
  const pass = (name, ok, detail) => {
    console.log((ok ? "  [PASS] " : "  [FAIL] ") + name + (detail ? "  " + detail : ""));
    if (!ok) fails.push(name);
  };

  const pairs = rows.filter((r) => r.pair !== 'nodehead' && r.pair !== 'intersect');
  const inter = rows.filter((r) => r.pair === 'intersect');
  const nh = rows.filter((r) => r.pair === 'nodehead');

  console.log("=== 吸顶几何断言（真实排版 · %d 样本）===", rows.length);
  if (!pairs.length) {
    pass("采集到吸顶层相邻样本", false, "未采到任何停靠中的相邻吸顶层，断言无效");
    process.exit(1);
  }

  const overlaps = pairs.filter((r) => r.gap < 0);
  const gaps = pairs.filter((r) => r.gap > TOL);
  const translucent = pairs.filter((r) => !r.upperOpaque || !r.lowerOpaque);
  const badZ = pairs.filter((r) => Number(r.zUpper) <= Number(r.zLower));

  pass("相邻吸顶层无重叠", overlaps.length === 0,
    overlaps.length ? "最严重 " + Math.min(...overlaps.map((r) => r.gap)) + "px @ "
      + overlaps[0].upper + "→" + overlaps[0].lower : "0 样本重叠");
  pass("相邻吸顶层无透明缝隙", gaps.length === 0,
    gaps.length ? "最大缝隙 " + Math.max(...gaps.map((r) => r.gap)) + "px @ "
      + gaps[0].upper + "→" + gaps[0].lower : "全部 ≤" + TOL + "px");
  pass("吸顶层背景不透明", translucent.length === 0,
    translucent.length ? translucent.length + " 样本半透明" : "");
  pass("吸顶层 z-index 严格递减（上层压下层）", badZ.length === 0,
    badZ.length ? badZ[0].upper + "(" + badZ[0].zUpper + ") → "
      + badZ[0].lower + "(" + badZ[0].zLower + ")" : "");

  // 针对性断言：快捷栏与筛选栏不得相交（这是本轮修复的核心）
  const collide = inter.filter((r) => r.intersect);
  pass("快捷栏与筛选栏不发生竖直重叠（叠字根因）", collide.length === 0,
    collide.length ? collide.length + " 个样本相交，"
      + Math.min(...collide.map((r) => r.gap)) + "px @ y=" + collide[0].y
      : inter.length + " 个停靠样本全部不相交");

  // 针对性断言：环节节头完全不吸顶
  const nhSticky = nh.filter((r) => r.isSticky);
  const nhPinned = nh.filter((r) => r.pinnedAtTop);
  const nhClass = nh.filter((r) => r.hasStuckClass);
  pass("环节节头不吸顶（position 非 sticky）", nhSticky.length === 0,
    nhSticky.length ? nhSticky.length + " 个样本为 sticky" : "检查 " + nh.length + " 个样本");
  pass("环节节头从不占据栈顶位置", nhPinned.length === 0,
    nhPinned.length ? nhPinned.length + " 个样本停在栈顶" : "");
  pass("环节节头无 is-stuck 残留类", nhClass.length === 0,
    nhClass.length ? nhClass.length + " 个样本带 is-stuck" : "");

  // 覆盖度：必须真的量到了两对相邻关系
  const seen = new Set(pairs.map((r) => r.pair));
  pass("量到顶栏→快捷栏相邻关系", seen.has('topbar|mini'), [...seen].join(" | "));
  pass("量到快捷栏→筛选栏相邻关系", seen.has('mini|filters'));
  pass("采到筛选栏停靠样本", inter.length > 0, inter.length + " 个");

  if (fails.length) {
    console.log("\n吸顶几何断言失败 " + fails.length + " 项。");
    process.exit(1);
  }
  console.log("\n吸顶几何断言全部通过。");
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(2); });