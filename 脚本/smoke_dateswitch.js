/* 日期 × 窗口切换专项测试（渲染驱动形态）：
 * 校验「按需渲染」下的日期切换、窗口切换、旗标一致性与进行中标记。
 * 期望值一律取自页面内联的 L2 投影载荷（VIEW_SRC），不另立一套口径。
 */
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const html = fs.readFileSync(process.argv[2], "utf-8");
const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", e => errors.push("jsdomError: " + (e.stack || e.message).split("\n")[0]));
vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  url: "http://localhost/dashboard.html",
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
  },
});
const { window } = dom;
const doc = window.document;
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const results = [];
  const t = (name, ok, detail) => { results.push((ok ? "PASS " : "FAIL ") + name + (detail ? " — " + detail : "")); };

  await sleep(1400);

  const srcM = html.match(/^const VIEW_SRC = (.*);$/m);
  const SRC = srcM ? JSON.parse(srcM[1]) : { index: {}, views: {} };
  const IDX = SRC.index || {};
  const dates = Object.keys(IDX.days || {}).sort();
  const host = doc.getElementById("dayHost");
  const view = () => SRC.views[host.dataset.date + "_" + host.dataset.window + "h"];

  t("脚本执行无错误", errors.length === 0, errors.slice(0, 3).join(" | "));
  t("索引含多日与双窗口条数", dates.length >= 1 &&
    dates.every(d => {
      const w = (IDX.days[d] || {}).windows || {};
      return w["24"] && w["48"];
    }), dates.length + " 天：" + dates.join(", "));

  const liveDates = dates.filter(d => (IDX.days[d] || {}).live);
  const completeDates = dates.filter(d => !liveDates.includes(d));
  const defaultDate = IDX.latest || (completeDates[completeDates.length - 1] || dates[dates.length - 1]);
  t("默认显示最近完整自然日（进行中的当天不默认）",
    host.dataset.date === defaultDate,
    host.dataset.date + "（进行中 " + (liveDates.join(",") || "无") + "）");

  // 逐日期 × 双窗口：切换后核对「涉及中国」统计与卡片徽标一致、热点旗标在名称后
  const bad = [];
  for (const d of dates) {
    for (const w of ["24", "48"]) {
      await window.switchView(d, +w);
      await sleep(60);
      const v = view();
      if (!v) { bad.push(d + "/" + w + "h 无投影"); continue; }
      const badges = host.querySelectorAll(".card-region").length;
      if (String(badges) !== String(v.stats.china))
        bad.push(d + "/" + w + "h 中国徽标 " + badges + " vs " + v.stats.china);
      if (![...host.querySelectorAll(".hot-cn")].every(x => !!x.closest(".hot-head")))
        bad.push(d + "/" + w + "h 热点旗标位置错");
      const nCards = host.querySelectorAll(".card").length;
      if (nCards !== v.stats.filed)
        bad.push(d + "/" + w + "h 卡片 " + nCards + " vs " + v.stats.filed);
      // Hero 滑轨按钮的提示条数 = 该窗口入档数
      const btn = host.querySelector('.hw-btn[data-window="' + w + '"]');
      if (btn && !btn.title.includes("共 " + v.stats.filed + " 条"))
        bad.push(d + "/" + w + "h 滑轨提示条数不符");
    }
  }
  t("全部 " + dates.length + " 日 × 双窗口：统计与渲染一致", bad.length === 0,
    bad.slice(0, 3).join(" | "));

  // 进行中的当天：切过去应带「进行中 · 截至 HH:MM」
  if (liveDates.length) {
    await window.switchView(liveDates[liveDates.length - 1], 24);
    await sleep(120);
    const b = host.querySelector(".live-badge");
    t("进行中的当天带「进行中 · 截至 HH:MM」", !!b &&
      /进行中 · 截至 \d{2}:\d{2}/.test(b.textContent.replace(/\s+/g, " ")),
      b ? b.textContent.trim() : "无徽标");
  } else {
    t("进行中的当天带「进行中 · 截至 HH:MM」", true, "无进行中日");
  }

  // 日期菜单切换（UI 路径）：与默认日不同的那一天
  await window.switchView(defaultDate, 24);
  await sleep(200);
  const prev = [...dates].reverse().find(d => d !== defaultDate);
  if (prev) {
    const mdBefore = doc.getElementById("dateBtnMd").textContent;
    doc.getElementById("dateBtn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    const opt = doc.querySelector('.date-opt[data-date="' + prev + '"]');
    t("日期菜单含全部选项（= 索引天数）",
      !!opt && doc.querySelectorAll(".date-opt").length === dates.length,
      doc.querySelectorAll(".date-opt").length + " vs " + dates.length);
    opt.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(400);
    t("切换日期后容器与投影同步",
      host.dataset.date === prev && !!view() && view().date === prev,
      host.dataset.date + " / " + (view() ? view().date : "无投影"));
    t("顶栏日期按钮已更新",
      doc.getElementById("dateBtnMd").textContent !== mdBefore,
      doc.getElementById("dateBtnMd").textContent);
    t("日期菜单已关闭", doc.getElementById("dateMenu").hidden);
    t("菜单选中态跟随",
      opt.getAttribute("aria-selected") === "true" &&
      doc.querySelector('.date-opt[data-date="' + defaultDate + '"]')
        .getAttribute("aria-selected") === "false");
    t("文档标题含切换后日期", doc.title.includes(prev), doc.title);
    t("切换后抽屉可用（curData 随视图更新）", await (async () => {
      const card = host.querySelector(".card");
      card.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      await sleep(150);                     // 抽屉开合依赖 rAF
      const open = doc.getElementById("drawer").classList.contains("open");
      const title = doc.getElementById("drawerTitle");
      doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await sleep(300);
      return open && !!title && title.textContent.length > 0;
    })());
  } else {
    t("日期菜单含全部选项（= 索引天数）", true, "数据集仅一天，跳过切换用例");
  }

  // 回到最新日
  await window.switchView(defaultDate, 24);
  await sleep(200);
  t("切回最新日", host.dataset.date === defaultDate, host.dataset.date);
  t("脚本执行无错误（全程）", errors.length === 0, errors.slice(0, 3).join(" | "));

  console.log(results.join("\n"));
  const failed = results.filter(r => r.startsWith("FAIL"));
  console.log(failed.length ? "\n专项测试失败 " + failed.length + " 项" : "\n专项测试全部通过");
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error("测试脚本异常:", e); process.exit(2); });
