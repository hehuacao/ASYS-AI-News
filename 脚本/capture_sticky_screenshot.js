/* 吸顶状态整屏截图（CDP + 本机 Chrome，零依赖）。
 * 用法：node cdp_sticky_shot.js <html路径> <端口> <cdp端口> <输出png>
 * 纪律：Page.captureScreenshot 的 clip 对 sticky 元素会退化错位，故抓整屏。
 */
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

const HTML = process.argv[2];
const PORT = process.argv[3] || "8951";
const CDP_PORT = Number(process.argv[4]) || 9341;
const OUT = process.argv[5] || "sticky.png";
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
  const profile = path.join(os.tmpdir(), "cdpshot" + CDP_PORT + "-" + Date.now());
  const chrome = spawn(CHROME, [
    "--headless=new", "--remote-debugging-port=" + CDP_PORT,
    "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
    "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
    "http://127.0.0.1:" + PORT + "/" + path.basename(HTML),
  ], { stdio: "ignore" });

  let wsUrl = null;
  for (let i = 0; i < 60 && !wsUrl; i++) {
    try {
      const list = await new Promise((res, rej) => {
        http.get("http://127.0.0.1:" + CDP_PORT + "/json/list", (r) => {
          let d = ""; r.on("data", (c) => d += c); r.on("end", () => res(JSON.parse(d)));
        }).on("error", rej);
      });
      const pg = list.find((t) => t.type === "page");
      if (pg) wsUrl = pg.webSocketDebuggerUrl;
    } catch (e) { /* 等 */ }
    if (!wsUrl) await sleep(250);
  }
  if (!wsUrl) { console.error("CDP 未就绪"); chrome.kill(); server.close(); process.exit(2); }

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
  await sleep(2500);

  const ev = async (e) => {
    const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };

  // 滚到第一张有内容的环节中部，确保节头处于吸顶态
  await ev(`(async()=>{const n=[...document.querySelectorAll('.node')].find(x=>x.querySelector('.card'));const H=document.documentElement.scrollHeight-innerHeight;const y=n.offsetTop+600;scrollTo(0,Math.min(y,H));await new Promise(r=>setTimeout(r,500));return scrollY})()`);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log("已保存 " + OUT);
  ws.close(); chrome.kill(); server.close();
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });