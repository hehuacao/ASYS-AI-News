/* 吸顶层时序取证：axis-mini 显隐时机 vs filters 吸顶时机。
 * 回答一个具体问题：filters 吸在 axis-mini 下方后，会不会出现
 *「axis-mini 还没显示（opacity:0，透明占位）而 filters 已吸顶」的时段？
 * 用法：node probe_showcase.js [html路径]
 */
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

const BASE = path.resolve(__dirname, "..");
const HTML = process.argv[2] || path.join(BASE, "仪表盘", "ai_news_daily.html");
const PORT = 8965;
const CDP_PORT = 9355;
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
  const profile = path.join(os.tmpdir(), "probeshow" + Date.now());
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
    const mini = document.querySelector('.axis-mini');
    const filters = document.querySelector('.filters');
    const hero = document.querySelector('.axis-hero');
    const rows = [];
    const H = document.documentElement.scrollHeight - innerHeight;
    //逐 1%细扫，专门找「filters 已停靠62px」的起点
    for (let i = 0; i <= 100; i++) {
      const y = Math.round(H * i / 100);
      scrollTo(0, y); await sleep(45);
      const fr = filters.getBoundingClientRect();
      const mr = mini.getBoundingClientRect();
      const pinned = Math.abs(fr.top - 62) <= 2;
      rows.push({ y: y, pinned: pinned,
                  miniShown: mini.classList.contains('show'),
                  miniOpacity: getComputedStyle(mini).opacity,
                  fTop: Math.round(fr.top), mTop: Math.round(mr.top), mBot: Math.round(mr.bottom),
                  heroBottom: Math.round(hero.getBoundingClientRect().bottom) });
    }
    scrollTo(0, 0);
    return rows;
  })()`);

  ws.close(); chrome.kill(); server.close();

  const firstPinned = out.findIndex((r) => r.pinned);
  console.log("filters 首次停靠在 62px 的滚动位置：y =", firstPinned >= 0 ? out[firstPinned].y : "从未");
  console.log("\n关键区间（filters 停靠前后各 6 个采样）：");
  const from = Math.max(0, firstPinned - 6);
  console.log("   y  | pinned | mini.show | mini.opacity | filters.top | mini 区间");
  for (let i = from; i < Math.min(out.length, firstPinned + 7); i++) {
    const r = out[i];
    console.log(String(r.y).padStart(5) + " | " + String(r.pinned).padEnd(6) + " | " +
      String(r.miniShown).padEnd(9) + " | " + r.miniOpacity.padEnd(12) + " | " +
      String(r.fTop).padStart(10) + " | " + r.mTop + "~" + r.mBot);
  }
  // 关键判定：filters 停靠期间，mini 是否始终已 show
  const pinnedRows = out.filter((r) => r.pinned);
  const bad = pinnedRows.filter((r) => !r.miniShown);
  console.log("\n停靠样本共 " + pinnedRows.length + " 个；其中 mini 未 show 的有 " + bad.length + " 个");
  if (bad.length) console.log("  → 存在「mini 透明占位而 filters 已吸顶」时段，y =", bad.slice(0, 8).map((r) => r.y).join(", "));
  const collide = pinnedRows.filter((r) => r.fTop < r.mBot - 1);
  console.log("停靠时 filters 与 mini 竖直区间相交（重叠）的样本：" + collide.length + " / " + pinnedRows.length);
})().catch((e) => { console.error(e); process.exit(2); });