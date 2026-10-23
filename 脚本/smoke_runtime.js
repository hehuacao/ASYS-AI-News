/* 运行态薄壳降级路径测试（jsdom）
 *
 * 薄壳只内联「索引 + 最近完整日 24h」作首屏兜底，其余按需 fetch。
 * 分两种「读不到数据」的情形各起一个 JSDOM：
 *   A. HTTP 环境但数据目录不可达（fetch 全失败）→ 兜底 + 提示「未能读到 数据/视图/」，
 *      点选不可取数的日期要说明原因而不是静默失败；
 *   B. 以 file:// 直接打开 → 浏览器安全策略禁止读本地文件，
 *      页面应**完全不发请求**（避免控制台一堆必然失败的报错），直接兜底 + 提示「本地文件方式打开」。
 * 正常 fetch 路径需真实 HTTP 环境，不在本测试范围。
 */
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { JSDOM, VirtualConsole } = require("jsdom");

const file = process.argv[2];
const html = fs.readFileSync(file, "utf-8");
const sleep = ms => new Promise(r => setTimeout(r, ms));
const VIEWS_DIR = path.join(__dirname, "..", "数据", "视图");

const results = [];
const t = (name, ok, detail) =>
  { results.push((ok ? "PASS " : "FAIL ") + name + (detail ? " — " + detail : "")); };

function boot(url, fetchImpl){
  const errors = [], calls = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", e => errors.push("jsdomError: " + (e.stack || e.message).split("\n")[0]));
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url,
    virtualConsole: vc,
    beforeParse(window) {
      window.matchMedia = q => ({
        matches: false, media: q,
        addEventListener() {}, removeEventListener() {},
        addListener() {}, removeListener() {},
      });
      window.IntersectionObserver = class {
        constructor(cb) { this.cb = cb; }
        observe(el) { this.cb([{ isIntersecting: true, target: el }]); }
        unobserve() {} disconnect() {}
      };
      window.scrollTo = () => {};
      // 默认：记录请求并一律失败（模拟「数据目录不可达」）
      window.fetch = fetchImpl || (u => {
        calls.push(String(u));
        return Promise.reject(new Error("offline"));
      });
    },
  });
  return { dom, errors, calls };
}
/* 模拟「HTTP 服务正常」：把请求映射到磁盘上的 数据/视图/（页面位于 仪表盘/ 下，
   经项目根提供 HTTP 服务时，第一条候选根 ../数据/视图/ 即命中） */
function liveFetch(calls){
  return u => {
    calls.push(String(u));
    const name = decodeURIComponent(String(u).split("/").pop());
    const p = path.join(VIEWS_DIR, name);
    if (!fs.existsSync(p)) return Promise.reject(new Error("404 " + name));
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve(JSON.parse(fs.readFileSync(p, "utf-8"))),
    });
  };
}

(async () => {
  const srcM = html.match(/^const VIEW_SRC = (.*);$/m);
  const SRC = srcM ? JSON.parse(srcM[1]) : {};
  const IDX_DAYS = Object.keys((SRC.index || {}).days || {});
  const total = IDX_DAYS.length;

  t("薄壳为运行态形态（mode=runtime）", SRC.mode === "runtime", String(SRC.mode));
  t("仅内联首屏兜底投影", Object.keys(SRC.views || {}).length === 1,
    Object.keys(SRC.views || {}).join(","));

  // ---------------- A. HTTP 但数据目录不可达 ----------------
  {
    const { dom, errors, calls } = boot("http://localhost/dashboard.html");
    await sleep(1500);
    const doc = dom.window.document;
    const host = doc.getElementById("dayHost");
    const notice = doc.getElementById("srcNotice");
    const cards = host ? host.querySelectorAll(".card").length : 0;

    t("A 脚本无未捕获错误", errors.length === 0, errors.slice(0, 2).join(" | "));
    t("A 已尝试探测数据根（候选根逐个 index.json）",
      calls.filter(u => /index\.json$/.test(u)).length >= 1,
      calls.slice(0, 2).join(" | "));
    t("A 仍渲染内联首屏（默认 = 最近完整日）",
      !!host && host.dataset.date === SRC.index.latest && cards > 0,
      (host && host.dataset.date) + " · " + cards + " 张卡片");
    t("A 兜底视图的条数与投影一致", (() => {
      const v = SRC.views[SRC.index.latest + "_24h"];
      return !!v && cards === v.stats.filed;
    })());
    t("A 提示条说明「未能读到数据目录」并给出替代方案",
      !!notice && !notice.hidden &&
      /未能读到 数据\/视图\//.test(notice.textContent) &&
      /离线单文件版/.test(notice.textContent),
      notice ? notice.textContent.slice(0, 60) + "…" : "无提示条");
    t("A 月历仍按索引列出全部日期，未连通者标 is-off",
      doc.querySelectorAll(".date-opt").length === total &&
      doc.querySelectorAll(".date-opt.is-off").length === total - 1,
      doc.querySelectorAll(".date-opt").length + " 格 · is-off " +
      doc.querySelectorAll(".date-opt.is-off").length);
    t("A 点选不可取数的日期会说明原因（不静默失败）", await (async () => {
      const off = doc.querySelector(".date-opt.is-off");
      if (!off) return false;
      notice.hidden = true;
      off.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
      await sleep(300);
      // 判据是「说明了**该日期**取不到」这一实质，而非整站不可读的话术：
      // 「某日数据缺失」与「数据目录整体不可读」是两回事，本断言守的是前者。
      // 反向验证记录：曾写成 `/读不到 .* 的数据|未能读到/`，而 `未能读到` 分支
      // 恰好能匹配旧的整体不可读文案 → 注入「静默失败」缺陷后仍然 PASS，断言失效。
      // 故此处只认日期专属文案，不留可被整体不可读文案满足的旁路。
      return !notice.hidden &&
        new RegExp("读不到 " + off.dataset.date + " 的数据").test(notice.textContent);
    })());
  }

  // ---------------- B. file:// 直接打开 ----------------
  {
    const { dom, errors, calls } = boot(pathToFileURL(file).href);
    await sleep(1500);
    const doc = dom.window.document;
    const host = doc.getElementById("dayHost");
    const notice = doc.getElementById("srcNotice");
    const cards = host ? host.querySelectorAll(".card").length : 0;

    t("B file:// 下不发任何数据请求（不产生必然失败的网络报错）",
      calls.length === 0, calls.join(", ") || "0 次请求");
    t("B 提示条为「本地文件方式打开」口径并给出替代方案",
      !!notice && !notice.hidden &&
      /本地文件方式打开（file:\/\/）/.test(notice.textContent) &&
      /离线单文件版/.test(notice.textContent),
      notice ? notice.textContent.slice(0, 60) + "…" : "无提示条");
    t("B 仍渲染内联首屏（默认 = 最近完整日）",
      !!host && host.dataset.date === SRC.index.latest && cards > 0,
      (host && host.dataset.date) + " · " + cards + " 张卡片");
    t("B 脚本无未捕获错误", errors.length === 0, errors.slice(0, 2).join(" | "));
  }

  // ---------------- C. 数据根连通（HTTP 正常）：全部日期 × 双窗口可切换 ----------------
  {
    const calls0 = [];
    const { dom, errors } = boot("http://localhost/dashboard.html", liveFetch(calls0));
    await sleep(1500);
    const doc = dom.window.document;
    const host = doc.getElementById("dayHost");
    const notice = doc.getElementById("srcNotice");
    const idx = (() => { try { return JSON.parse(fs.readFileSync(
      path.join(VIEWS_DIR, "index.json"), "utf-8")); } catch (e) { return {}; } })();
    const days = Object.keys(idx.days || {}).sort();

    t("C 候选根探测命中第一条即固定（只请求一次 index.json）",
      calls0.filter(u => /index\.json$/.test(u)).length === 1,
      calls0.filter(u => /index\.json$/.test(u)).join(", "));
    t("C 连通后无降级提示条", !!notice && notice.hidden);
    t("C 全部日期均可切换（无 is-off）",
      doc.querySelectorAll(".date-opt.is-off").length === 0,
      doc.querySelectorAll(".date-opt.is-off").length + " 个 is-off");
    t("C 脚本无未捕获错误", errors.length === 0, errors.slice(0, 2).join(" | "));

    const bad = [];
    for (const d of days){
      for (const w of [24, 48]){
        const rec = ((idx.days[d] || {}).windows || {})[String(w)];
        if (!rec) continue;
        await dom.window.switchView(d, w);
        await sleep(30);
        const n = host.querySelectorAll(".card").length;
        if (n !== rec.filed) bad.push(d + "/" + w + "h " + n + "≠" + rec.filed);
      }
    }
    t("C 全部日期 × 双窗口按需取数并渲染正确（" + days.length + " 日）",
      bad.length === 0, bad.slice(0, 3).join(" | "));
    /* 判据不写死具体是哪个根：候选顺序（ASCII 优先）是实现细节，会随托管环境调整，
       写死就会在改顺序时假失败（踩过：ASCII 前置后此处曾误报）。
       可验证的实质是：① 探测只发一次 index.json（上面已单列断言）；
                     ② 之后所有请求落在**同一个**根上 —— 即 VIEW_BASE 一经固定即复用。
       注意夹具 liveFetch 把任意根都映射到同一磁盘目录，故「多根」在夹具里不可触发；
       真正的防回归由 validate_dashboard 的候选顺序断言 + 线上 Chrome 实测承担。 */
    const roots = [...new Set(calls0.map(u => String(u).slice(0, String(u).lastIndexOf("/") + 1)))];
    t("C 按需取数全程复用同一个探测到的数据根（" + calls0.length + " 次请求 · " +
        roots.length + " 个根）",
      roots.length === 1 && calls0.length >= 1,
      roots.length !== 1 ? "出现多个数据根：" + roots.join(" , ")
                          : "根为 " + roots[0] + " · " + calls0.slice(0, 3).join(" | "));
  }

  console.log(results.join("\n"));
  const failed = results.filter(r => r.startsWith("FAIL"));
  console.log(failed.length ? "\n运行态降级测试失败 " + failed.length + " 项"
                            : "\n运行态降级测试全部通过");
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error("测试脚本异常:", e); process.exit(2); });
