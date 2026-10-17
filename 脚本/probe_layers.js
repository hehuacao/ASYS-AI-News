/* 吸顶层现状取证（一次性诊断，不做断言）。
 * 量出每一层的真实停靠位置、position、z-index、背景不透明度、是否可见，
 * 用来定位「哪两层压在一起」，而不是猜。
 * 用法：node probe_layers.js [html路径]
 */
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

const BASE = path.resolve(__dirname, "..");
const HTML = process.argv[2] || path.join(BASE, "仪表盘", "ai_news_daily.html");
const PORT = 8963;
const CDP_PORT = 9353;
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

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
  const server = await serve();
  const profile = path.join(os.tmpdir(), "probelay" + Date.now());
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
    } catch (e) { /* 等 Chrome */ }
    if (!wsUrl) await sleep(250);
  }
  const ws = new WebSocket(wsUrl);
  let id = 0; const pend = new Map();
  const send = (m, p) => new Promise((res) => { const n = ++id; pend.set(n, res); ws.send(JSON.stringify({ id: n, method: m, params: p || {} })); });
  await new Promise((r) => ws.addEventListener("open", r));
  ws.addEventListener("message", (m) => {
    const o = JSON.parse(m.data);
    if (o.id && pend.has(o.id)) { pend.get(o.id)(o.result); pend.delete(o.id); }
  });
  await send("Page.enable"); await send("Runtime.enable");
  await sleep(2600);

  const ev = async (e) => {
    const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };

  const out = await ev(`(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const SEL = ['.topbar', '.axis-mini', '.filters', '.node-head'];
    const info = el => {
      if (!el) return null;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const m = /rgba?\\(([^)]+)\\)/.exec(cs.backgroundColor);
      let alpha = 1;
      if (m) { const p = m[1].split(',').map(x => parseFloat(x)); if (p.length >= 4) alpha = p[3]; }
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height),
               pos: cs.position, z: cs.zIndex, cssTop: cs.top,
               alpha: alpha, opacity: cs.opacity,
               visible: cs.display !== 'none' && r.height > 0 && cs.visibility !== 'hidden',
               mb: cs.marginBottom, pt: cs.paddingTop, pb: cs.paddingBottom };
    };
    const rows = [];
    const H = document.documentElement.scrollHeight - innerHeight;
    for (const frac of [0, 0.02, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.5]) {
      const y = Math.round(H * frac);
      scrollTo(0, y); await sleep(140);
      const o = { y: y };
      for (const s of SEL) o[s] = info(document.querySelector(s));
      rows.push(o);
    }
    scrollTo(0, 0);
    return { rows: rows, vars: {
      topbarH: getComputedStyle(document.documentElement).getPropertyValue('--topbar-h'),
      filtersH: getComputedStyle(document.documentElement).getPropertyValue('--filters-h'),
      nodeheadH: getComputedStyle(document.documentElement).getPropertyValue('--nodehead-h'),
    }};
  })()`);

  ws.close(); chrome.kill(); server.close();

  console.log("CSS 变量：", JSON.stringify(out.vars));
  const L = (o, s) => !o[s] ? "—" :
    (o[s].visible ? `top=${String(o[s].top).padStart(4)} bot=${String(o[s].bottom).padStart(4)} h=${String(o[s].h).padStart(3)}` : "(不可见)");
  console.log("\ny      | .topbar            | .axis-mini          | .filters            | .node-head");
  for (const r of out.rows) {
    console.log(String(r.y).padStart(5) + " | " + L(r, ".topbar").padEnd(18) + " | " +
      L(r, ".axis-mini").padEnd(19) + " | " + L(r, ".filters").padEnd(19) + " | " + L(r, ".node-head"));
  }
  console.log("\n--- 首个 scroll>0 处的完整属性 ---");
  const s = out.rows.find((r) => r.y > 0);
  for (const k of [".topbar", ".axis-mini", ".filters", ".node-head"]) {
    if (s[k]) console.log(k.padEnd(12), JSON.stringify(s[k]));
  }
})().catch((e) => { console.error(e); process.exit(2); });