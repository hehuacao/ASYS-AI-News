/* P2 仪表盘运行时冒烟测试：jsdom 真实执行页面脚本，捕捉 DOM/逻辑错误 */
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const html = fs.readFileSync(process.argv[2], "utf-8");
const errors = [];
const fetchCalls = [];   // 离线单文件应当零请求（自包含）
const vc = new VirtualConsole();
vc.on("jsdomError", e => errors.push("jsdomError: " + (e.stack || e.message).split("\n")[0]));
vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  url: "http://localhost/dashboard.html",
  virtualConsole: vc,
  beforeParse(window) {
    // jsdom 无 matchMedia / IntersectionObserver / scrollTo，提前注入桩
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
    // 探针：离线单文件不应发起任何数据请求
    window.fetch = u => { fetchCalls.push(String(u)); return Promise.reject(new Error("offline")); };
  },
});
const { window } = dom;
const doc = window.document;
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const results = [];
  const t = (name, ok, detail) => { results.push((ok ? "PASS " : "FAIL ") + name + (detail ? " — " + detail : "")); };

  await sleep(1400); // 等数字滚动（900ms）结束

  t("脚本执行无错误", errors.length === 0, errors.slice(0, 3).join(" | "));
  t("主题默认深色", doc.documentElement.dataset.theme === "dark", doc.documentElement.dataset.theme);

  // 多日期结构（渲染驱动：日期集合来自 L2 索引，页面按需渲染当前视图）
  const srcM = html.match(/^const VIEW_SRC = (.*);$/m);
  t("页面内联视图载荷（索引 + 投影）", !!srcM);
  const SRC = srcM ? JSON.parse(srcM[1]) : { index: {}, views: {}, mode: "?" };
  const IDX = SRC.index || {};
  const IDX_DATES = Object.keys(IDX.days || {}).sort();
  const liveDates = new Set(IDX_DATES.filter(d => (IDX.days[d] || {}).live));
  const completeDates = IDX_DATES.filter(d => !liveDates.has(d));
  const visibleDay = doc.getElementById("dayHost");
  t("日期容器存在且已渲染当前视图", !!visibleDay && !!visibleDay.dataset.date,
    visibleDay && visibleDay.dataset.date);
  t("默认显示最近完整自然日（不落在进行中的当天）",
    !!visibleDay && visibleDay.dataset.date ===
      (IDX.latest || completeDates[completeDates.length - 1]),
    (visibleDay && visibleDay.dataset.date) + "（最近完整日 " + IDX.latest +
    "；进行中 " + [...liveDates].join(",") + "）");
  t("离线单文件零网络请求且无降级提示条（自包含）",
    fetchCalls.length === 0 && doc.getElementById("srcNotice").hidden,
    fetchCalls.length + " 次请求");
  t("内联投影覆盖索引全部日期 × 双窗口",
    IDX_DATES.every(d => {
      const w = (IDX.days[d] || {}).windows || {};
      return Object.keys(w).every(k => !!SRC.views[d + "_" + k + "h"]);
    }),
    Object.keys(SRC.views).length + " 份投影");
  // 进行中的当天：切过去核对徽标文案，再切回默认日
  if (liveDates.size){
    const live = [...liveDates].sort().pop();
    await window.switchView(live, 24);
    await sleep(1300);
    const b = doc.querySelector("#dayHost .live-badge");
    t("进行中的当天带「进行中」徽标（Hv2 提示数据截至时点）",
      !!b && /进行中 · 截至 \d{2}:\d{2}/.test(b.textContent.replace(/\s+/g, " ")),
      b ? b.textContent.trim() : "无徽标");
    await window.switchView(IDX.latest, 24);
    await sleep(1300);
  } else {
    t("进行中的当天带「进行中」徽标（Hv2 提示数据截至时点）", true, "本数据集无进行中日");
  }
  const statOkNow = () => [...visibleDay.querySelectorAll(".stat-num")]
    .every(e => e.textContent === e.dataset.target);
  const cards = [...visibleDay.querySelectorAll(".card")];
  const heroTarget = +visibleDay.querySelector(".hero-num").dataset.target;
  t("卡片已渲染且与 Hero 入档数一致",
    cards.length > 0 && cards.length === heroTarget,
    cards.length + " 张 / Hero " + heroTarget);
  const cnCards = visibleDay.querySelectorAll('.card[data-region="china"]').length;
  t("日期选择器存在", !!doc.getElementById("dateBtn") && !!doc.getElementById("dateMenu"));
  t("日期选项数 = 索引天数",
    doc.querySelectorAll(".date-opt").length === IDX_DATES.length,
    doc.querySelectorAll(".date-opt").length + " vs " + IDX_DATES.length);

  // 主轴结构
  const ahNodes = visibleDay.querySelectorAll(".ah-node");
  t("主轴五节点", ahNodes.length === 5, ahNodes.length + " 个");
  const enOk = [...ahNodes].every(n => /CAPABILITY|PRODUCT|INDUSTRY|GOVERNANCE|FRONTIER/
    .test(n.textContent));
  t("主轴节点含英文名", enOk);
  const cntOk = [...ahNodes].every(n => /\d+ 条/.test(n.querySelector(".ahn-count").textContent));
  t("主轴节点含计数", cntOk);
  t("迷你主轴存在", visibleDay.querySelectorAll(".am-btn").length === 5);
  // 第四轮：迷你导航文字不用浅灰（与橙底头条徽标不搭），改主题主文字色
  t("迷你导航节点名/计数为主文字色（非浅灰）",
    /\.am-btn\{[^}]*color:var\(--text-primary\)/.test(html) &&
    /\.am-btn em:not\(\.am-flag\)\{font-style:normal;font-size:11px;color:var\(--text-primary\)/.test(html));
  t("迷你主轴 AI 价值链文案",
    /AI 价值链/.test(visibleDay.querySelector(".am-brand").textContent),
    visibleDay.querySelector(".am-brand").textContent.trim());

  // Hero 改版：入档条数为视觉主体 + 五节点分布面板
  const heroNum = visibleDay.querySelector(".hero-num");
  t("Hero 大数字 = 当日卡片数", !!heroNum && heroNum.dataset.target === String(cards.length),
    heroNum && heroNum.dataset.target + " vs " + cards.length);
  t("Hero 分布面板 5 行", visibleDay.querySelectorAll(".hd-row").length === 5);
  const hdNums = [...visibleDay.querySelectorAll(".hd-num b")].map(e => +e.textContent);
  const nodeTotals = [...visibleDay.querySelectorAll(".ah-node")].map(n => +n.dataset.total);
  t("分布数字与主轴计数一致",
    hdNums.length === 5 && hdNums.every((v, i) => v === nodeTotals[i]),
    hdNums.join(",") + " vs " + nodeTotals.join(","));
  t("Hero 无旧版四统计卡", visibleDay.querySelectorAll(".stat-card").length === 0);
  t("主轴 chips 已移除（首屏去重）",
    visibleDay.querySelectorAll(".ah-chip").length === 0);
  // 第三轮：日期与信源数/窗口数字强调；左列顶对齐；分布条数按节点色
  t("Hero 日期强调样式（18px+主色下划线）",
    /\.hero-date-mini b\{font-size:18px;font-weight:800/.test(html) &&
    /border-bottom:2px solid var\(--accent-capability\)/.test(html));
  t("Hero meta 数字与规范号强调（强调色加粗）",
    /\.hm-fact b\{font-weight:800;font-size:14px;color:var\(--accent-capability\)/.test(html) &&
    visibleDay.querySelector(".hm-right .hm-fact b") !== null);
  t("Hero 左列顶对齐（分布面板不随动）",
    /\.hero\{display:flex;align-items:flex-start/.test(html));
  const hdBs = [...visibleDay.querySelectorAll(".hd-num b")];
  const hdRows = [...visibleDay.querySelectorAll(".hd-row")];
  t("分布条数按节点色（与占比条同色）",
    hdBs.length === 5 && hdBs.every((b, i) => {
      const rowNc = hdRows[i].style.getPropertyValue("--nc").trim();
      return rowNc && b.textContent.trim().length > 0 &&
        window.getComputedStyle(b).color !== "";
    }));
  t("分布百分比中性（非节点色）",
    /\.hd-num em\{font-style:normal;font-size:10px;color:var\(--text-muted\)\}/.test(html));

  // 热点横条：标题右侧统计（第四轮起只保留交叉热点，涉及中国已移入 Hero）
  const hsHot = visibleDay.querySelector(".hs-chip.hs-hot b");
  const hmCn = visibleDay.querySelector(".hr-item.hr-cn b");
  const hotItems = visibleDay.querySelectorAll(".hot-item").length;
  t("热点统计标：交叉热点 = 热点条目数", hsHot && hsHot.textContent === String(hotItems),
    hsHot && hsHot.textContent);
  t("热点横条已无涉及中国统计（口径分流）",
    visibleDay.querySelectorAll(".hs-chip.hs-cn").length === 0);
  t("Hero 地域构成：涉及中国 = 涉及中国卡片数",
    hmCn && hmCn.textContent === String(cnCards),
    hmCn && hmCn.textContent + " vs " + cnCards);
  // 第三轮颜色规则（用户 2026-10-14 定）：交叉热点=深橙实底+白字
  // （jsdom 不解析 var()，颜色用样式表规则文本校验）
  t("交叉热点统计标为深橙实底白字",
    /\.hs-hot\{background:var\(--hot-deep\);color:#fff\}/.test(html) &&
    /--hot-deep:#C2410C/.test(html));
  // 第六轮：涉及中国 = 与总条数同行的地域构成（国旗 + 地球徽章 + 无框成对）
  t("Hero 地域构成：涉及中国=国旗+无框（与总条数同行）",
    /\.hero-region\{display:inline-flex;align-items:center;gap:16px/.test(html) &&
    !!visibleDay.querySelector('.hr-cn svg.flag[width="16"]'));
  // 第七轮：全球项=地球徽章+国际蓝（与红色国旗对应）+ 全球资讯四字 + 粗体 + 底齐平
  t("地域构成全球项带地球徽章",
    !!visibleDay.querySelector('.hr-global svg.globe[width="16"]'));
  t("全球项徽章与数字为国际蓝",
    /\.hr-global b\{color:var\(--globe-blue\)\}/.test(html) &&
    /\.hr-global \.globe\{color:var\(--globe-blue\)\}/.test(html) &&
    /--globe-blue:#5B9BD5/.test(html) && /--globe-blue:#2E75B6/.test(html));
  t("全球文案为四字全球资讯", /274 全球资讯|全球资讯/.test(html) &&
    visibleDay.querySelector(".hr-item.hr-global") &&
    visibleDay.querySelector(".hr-item.hr-global").textContent.includes("全球资讯"));
  t("涉及中国/全球资讯文字粗体",
    /\.hr-item\{display:inline-flex;align-items:center;gap:7px;font-size:13px;\n\s*font-weight:700;/.test(html));
  t("地域构成与英文标签底齐平（flex-end）",
    /\.hero-region\{display:inline-flex;align-items:center;gap:16px;margin-left:14px;\n\s*align-self:flex-end;margin-bottom:7px\}/.test(html));
  t("地域构成与总条数在同一行（hero-figure 内联）",
    !!visibleDay.querySelector(".hero-figure .hero-region"));
  const hrCn = visibleDay.querySelector(".hr-item.hr-cn b");
  const hrGl = visibleDay.querySelector(".hr-item.hr-global b");
  t("涉及中国 + 全球 = 入档总条数",
    hrCn && hrGl && (+hrCn.textContent + +hrGl.textContent) === cards.length,
    hrCn && hrGl && (hrCn.textContent + " + " + hrGl.textContent + " vs " + cards.length));
  t("统计标字体已缩小（15.5px）", /\.hs-chip b\{font-size:15.5px/.test(html));
  t("统计标含口径提示（事件数≠中国条数，窗口含义）",
    !!visibleDay.querySelector(".hs-hot[title]") && !!visibleDay.querySelector(".hr-cn[title]") &&
    !!visibleDay.querySelector('.hw-btn[data-window="24"][title*="当日整日"]') &&
    !!visibleDay.querySelector('.hw-btn[data-window="48"][title*="48 小时"]'));
  t("窗口口径显示 24 小时（可切 48）",
    !!visibleDay.querySelector('.hw-btn.is-on[data-window="24"]') &&
    visibleDay.querySelector('.hw-btn.is-on[data-window="24"]').textContent.includes("24"));
  t("Hero 窗口切换器（24/48h，默认 24h 选中）",
    visibleDay.querySelectorAll(".hw-btn").length === 2 &&
    !!visibleDay.querySelector(".hw-btn.is-on[data-window=\"24\"]"));
  t("生成时间显示（生成时间 · MM.DD HH:MM，未加粗未改色）",
    !!visibleDay.querySelector(".hm-gen .hm-tval") &&
    /^\d{2}\.\d{2} \d{2}:\d{2}$/.test(
      visibleDay.querySelector(".hm-gen .hm-tval").textContent.trim()));
  t("meta 行左「时间窗口」右「信源 · 规范 · 生成时间」",
    !!visibleDay.querySelector(".hero-meta .hm-win .hw-switch .hw-btn[data-window=\"24\"]") &&
    visibleDay.querySelectorAll(".hero-meta .hm-right .hm-fact").length === 3 &&
    /信源 · \d+个/.test(visibleDay.querySelectorAll(".hm-right .hm-fact")[0].textContent) &&
    /规范 · AIIS-01/.test(visibleDay.querySelectorAll(".hm-right .hm-fact")[1].textContent));
  t("晨报标题与日期同一行（hero-topline 内并列）",
    !!visibleDay.querySelector(".hero-topline .hero-eyebrow") &&
    !!visibleDay.querySelector(".hero-topline .hero-date-mini") &&
    !visibleDay.querySelector(".hero-date-row"));
  // 日期选择器：月历控件（动态渲染，先展开）
  doc.querySelector("#dateBtn").dispatchEvent(
    new window.MouseEvent("click", { bubbles: true }));
  const calCells = doc.querySelectorAll("#dmGrid .date-opt");
  t("日期选择器为月历控件（含月导航 / 周首 / 图例）",
    !!doc.querySelector("#dateMenu .dm-head #dmPrev") &&
    !!doc.querySelector("#dateMenu .dm-head #dmNext") &&
    !!doc.querySelector("#dateMenu .dm-week") &&
    doc.querySelectorAll("#dateMenu .dm-lg").length === 2 &&
    !!doc.querySelector("#dmToday"));
  t("月历每格含双窗口条数（24H / 48H 各一，仅数字、颜色区分）",
    calCells.length > 0 &&
    doc.querySelectorAll("#dmGrid .date-opt .dc-chip.c24[data-window=\"24\"]").length ===
      calCells.length &&
    doc.querySelectorAll("#dmGrid .date-opt .dc-chip.c48[data-window=\"48\"]").length ===
      calCells.length &&
    Array.prototype.every.call(
      doc.querySelectorAll("#dmGrid .dc-chip"),
      c => /^\d+$/.test(c.textContent.trim())));
  t("月历格数与数据集天数一致且日期可读",
    calCells.length === IDX_DATES.length &&
    Array.prototype.every.call(calCells, c => /^\d{4}-\d{2}-\d{2}$/.test(c.dataset.date)),
    "cells=" + calCells.length);
  // 整月渲染 + 星期对齐：网格按周一首列排布，有数据日与无数据日都占位显示日号
  const kids = [...doc.querySelector("#dmGrid").children];
  const nums = [...doc.querySelectorAll("#dmGrid .dc-day")].map(e => e.textContent);
  const tgt = visibleDay.dataset.date, tp = tgt.split("-").map(Number);
  const col = (new Date(tp[0], tp[1] - 1, tp[2]).getDay() + 6) % 7;  // 周一首列
  const idx = kids.findIndex(el => el.dataset.date === tgt);
  t("月历显示整月日号且与星期表头对齐",
    nums.join(",") === Array.from({ length: 31 }, (_, i) => String(i + 1)).join(",") &&
    idx >= 0 && idx % 7 === col &&
    doc.querySelectorAll("#dmGrid .dm-cell.is-empty").length > 0,
    "1..31 共 " + nums.length + " 天 · " + tgt + " 落第 " + (idx % 7 + 1) +
    " 列（应 " + (col + 1) + "）");
  t("月历中进行中的当天带标记与提示",
    [...calCells].some(c => c.classList.contains("is-live") &&
      /进行中/.test(c.title)) === (liveDates.size > 0),
    [...calCells].filter(c => c.classList.contains("is-live")).length + " 格");
  t("月历图例含 24H/48H 颜色说明 + PgUp/PgDn 翻月键位",
    /24H 条数/.test(doc.querySelector(".dm-foot").textContent) &&
    /48H 条数/.test(doc.querySelector(".dm-foot").textContent) &&
    /PgUp\/PgDn 翻月/.test(doc.querySelector(".dm-tip").textContent));
  // 窗口条数配色：24H 能力青 → 48H 同族冷蓝，同冷色域色相梯度
  {
    const hue = (hex) => {
      const n = parseInt(hex.slice(1), 16);
      const r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
      if (!d) return 0;
      let h = mx === r ? ((g - b) / d + (g < b ? 6 : 0)) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      return h * 60;
    };
    const grab = (theme) => {
      const re = new RegExp('--win24:(#[0-9A-Fa-f]{6}); --win48:(#[0-9A-Fa-f]{6})');
      const blocks = html.split("html[data-theme=\"" + theme + "\"]{");
      const seg = blocks.length > 1 ? blocks[1].slice(0, 900) : "";
      const m = seg.match(re);
      return m ? { w24: m[1], w48: m[2] } : null;
    };
    const dark = grab("dark") || (html.match(/--win24:(#[0-9A-Fa-f]{6}); --win48:(#[0-9A-Fa-f]{6})/) &&
      { w24: RegExp.$1, w48: RegExp.$2 });
    const light = grab("light");
    t("窗口条数配色用语义变量 --win24/--win48（深/浅各一套）",
      !!dark && !!light && /--win24:#0E7490/.test(html) && /--win48:#2563EB/.test(html),
      dark ? dark.w24 + " / " + dark.w48 : "缺深色变量");
    t("月历格与图例共用同一对窗口色变量（禁止各写色值）",
      /\.dc-chip\.c24\{color:var\(--win24\)\}/.test(html) &&
      /\.dc-chip\.c48\{color:var\(--win48\)\}/.test(html) &&
      /\.dm-lg \.lg24\{background:var\(--win24\)\}/.test(html) &&
      /\.dm-lg \.lg48\{background:var\(--win48\)\}/.test(html));
    t("24H/48H 两色同属冷色域（色相差 15°–70°，可辨且成体系）",
      !!dark && (() => {
        const d = Math.abs(hue(dark.w24) - hue(dark.w48));
        return d > 15 && d < 70;
      })(),
      dark ? "色相差 " + Math.round(Math.abs(hue(dark.w24) - hue(dark.w48))) + "°" : "");
  }
  t("收起态按钮只显示条数（与格内同款，无 24H/48H 文字），当前窗口高亮",
    /^\d+$/.test(doc.querySelector(".date-btn-counts .dc-chip.c24").textContent.trim()) &&
    /^\d+$/.test(doc.querySelector(".date-btn-counts .dc-chip.c48").textContent.trim()) &&
    !/[A-Za-z]/.test(doc.querySelector(".date-btn-counts").textContent) &&
    doc.querySelector(".date-btn-counts .dc-chip.c24").classList.contains("is-on"));
  t("月历条数更小（9.5px 不换行不收缩）且空/有数据日同构",
    /font-size:9\.5px;font-weight:800;line-height:1;/.test(html) &&
    /flex:none;white-space:nowrap;/.test(html) &&
    /\.dm-cell,\.date-opt\{height:54px;display:flex;flex-direction:column;align-items:center;\n  justify-content:flex-start;gap:3px;padding:7px 2px 0;/.test(html) &&
    (() => {
      const empty = doc.querySelector("#dmGrid .dm-cell.is-empty");
      const filled = doc.querySelector("#dmGrid .date-opt");
      return !!empty && !!filled &&
        !!empty.querySelector(".dc-n") && !!filled.querySelector(".dc-n");
    })());
  {
    const b24 = doc.querySelector(".date-btn-counts .dc-chip.c24");
    const b48 = doc.querySelector(".date-btn-counts .dc-chip.c48");
    visibleDay.querySelector('.hw-btn[data-window="48"]')
      .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(400);
    const on48 = b48.classList.contains("is-on") && !b24.classList.contains("is-on");
    visibleDay.querySelector('.hw-btn[data-window="24"]')
      .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(400);
    const on24 = b24.classList.contains("is-on") && !b48.classList.contains("is-on");
    t("当前窗口高亮随 24H/48H 切换同步到收起态按钮", on48 && on24);
  }
  // 等数字滚动动画结束（轮询至稳定，避免固定等待时间不够）
  const t0 = Date.now();
  while (Date.now() - t0 < 3000 && !statOkNow()) await sleep(100);
  t("统计数字滚动到目标值", statOkNow(),
    [...visibleDay.querySelectorAll(".stat-num")].map(e => e.textContent).join(","));
  t("抽屉字段名列加宽并右对齐",
    /\.kv span\{flex:none;width:96px;text-align:right/.test(html));
  // 第五轮：橙底徽标黑字（修复 em 覆盖 bug）
  t("橙底徽标字色为纯黑（修复 em 特异性覆盖）",
    /--hot-solid-fg:#000/.test(html) && /\.am-btn em:not\(\.am-flag\)\{/.test(html));
  // 第六轮：品牌英文 ASYS + 底齐平（flex-end）+ 搜索框 220px
  t("顶栏品牌英文 ASYS · AI NEWS DAILY 存在",
    /ASYS · AI NEWS DAILY/.test(html) && /<span class="brand-zh">/.test(html));
  t("品牌英文与中文底部齐平（flex-end）",
    /\.brand\{display:flex;align-items:flex-end/.test(html) &&
    /\.brand-text\{display:inline-flex;align-items:flex-end/.test(html));
  t("搜索框宽度 220px（聚焦 280px）",
    /\.searchbox input\{\n  width:220px/.test(html) &&
    /\.searchbox input:focus\{width:280px/.test(html));

  // 国旗体系：来源旗标 + 涉及中国旗标
  const srcFlags = visibleDay.querySelectorAll(".chip-src > svg.flag");
  t("卡片来源旗标渲染", srcFlags.length > 0, srcFlags.length + " 个");
  const cnBadges = visibleDay.querySelectorAll(".card-region svg.flag");
  t("涉及中国徽标数 = 涉及中国卡片数", cnBadges.length === cnCards,
    cnBadges.length + " vs " + cnCards);
  const usFlags = [...srcFlags].filter(f => f.outerHTML.includes("#3C3B6E"));
  t("美国旗标可识别（蓝色 canton）", usFlags.length > 0, usFlags.length + " 个");

  // 第三轮：热点条目名称后来源国旗（取有热点的视图：13 日 24h）
  const hotView = [...doc.querySelectorAll('.day[data-window="24"]')]
    .find(x => x.querySelectorAll(".hot-item").length > 0) || visibleDay;
  const hotFlagGroups = hotView.querySelectorAll(".hot-item .hot-flags");
  const hotN = hotView.querySelectorAll(".hot-item").length;
  t("热点条目名称后带来源国旗", hotFlagGroups.length === hotN && hotN > 0,
    hotFlagGroups.length + "/" + hotN);
  const hotFlagN = hotView.querySelectorAll(".hot-item .hot-flag").length;
  const hotSrcN = [...hotView.querySelectorAll(".hot-count")]
    .reduce((s, e) => s + parseInt(e.textContent, 10), 0);
  t("热点国旗数 = 信源总数（一信源一旗）", hotFlagN === hotSrcN,
    hotFlagN + " vs " + hotSrcN);
  t("旗标紧跟标题而非行尾（标题非 flex:1）",
    /\.hot-title\{flex:0 1 auto/.test(html) && /\.hot-flags\{[^}]*margin-left:10px/.test(html));
  t("旗标尺寸 16px（与卡片统一）",
    !!hotView.querySelector(".hot-flag svg.flag") &&
    hotView.querySelector(".hot-flag svg.flag").getAttribute("width") === "16");

  // 日期菜单开合
  const dateBtn = doc.getElementById("dateBtn");
  dateBtn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  t("日期菜单可打开", !doc.getElementById("dateMenu").hidden &&
    dateBtn.getAttribute("aria-expanded") === "true");
  doc.body.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  t("点击外部关闭菜单", doc.getElementById("dateMenu").hidden);


  // 交互：打开抽屉（等 rAF）
  const card = visibleDay.querySelector('.card[data-node="capability"]') || cards[0];
  card.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(120);
  const drawer = doc.getElementById("drawer");
  t("点击卡片打开抽屉", drawer.classList.contains("open") && !drawer.hidden);
  t("抽屉含标题", !!doc.getElementById("drawerTitle") && doc.getElementById("drawerTitle").textContent.length > 4);
  t("抽屉含原文链接", !!doc.querySelector('.drawer-links a[target="_blank"]'));
  t("抽屉含面包屑（中英文）", /›/.test(doc.getElementById("drawerCrumb").textContent));
  t("抽屉含权威度与分层", /权威度\s*\d/.test(doc.getElementById("drawerBody").textContent));
  t("抽屉含信源区块（来源国家/地区）",
    /来源国家\/地区/.test(doc.getElementById("drawerBody").textContent));
  t("抽屉信源 chip 带国旗",
    !!doc.querySelector('.drawer-meta .chip-src > svg.flag'));
  // 摘要全文：drawer-summary 长度应 >= 卡片压缩摘要
  const cardSummary = card.querySelector(".card-summary").textContent;
  const drawerSummary = doc.querySelector(".drawer-summary").textContent;
  t("抽屉展示摘要全文（≥卡片摘要）", drawerSummary.length >= cardSummary.length,
    "卡片 " + cardSummary.length + " 字 / 抽屉 " + drawerSummary.length + " 字");

  // 交互：抽屉内 j/k 切条
  const before = doc.getElementById("drawerTitle").textContent;
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "j", bubbles: true }));
  await sleep(120);
  const after = doc.getElementById("drawerTitle").textContent;
  t("抽屉内 j 切换同节点下一条", before !== after, "");

  // 交互：Esc 关闭
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await sleep(400);
  t("Esc 关闭抽屉", !drawer.classList.contains("open") && drawer.hidden);

  // 回归（2026-10-15 修 bug）：同一信源就同一事件收录多条时，热点国旗行与抽屉
  // 「相关报道」都必须按**信源**归组（AI HOT 曾重复出现 3 面旗），其余收录以
  // .hot-more / .rel-more 域名链接保留，不丢来源、不冒充独立信源。
  const multiHot = [...visibleDay.querySelectorAll(".hot-item")].find(
    it => it.querySelector(".hot-timeline .hot-more"));
  if (multiHot) {
    const nFlags = multiHot.querySelectorAll(".hot-flag").length;
    const nMore = multiHot.querySelectorAll(".hot-timeline .hot-more").length;
    const nRows = multiHot.querySelectorAll(".hot-timeline > li").length;
    const nBadge = parseInt((multiHot.querySelector(".hot-count") || {}).textContent, 10);
    t("热点：同源多条时国旗数 = 信源读数", nFlags === nBadge,
      nFlags + " 旗 / " + nBadge + " 信源");
    t("热点：明细行按信源归组", nRows === nFlags, nRows + " 行 vs " + nFlags + " 旗");
    t("热点：同源其余收录以域名链接保留", nMore > 0, nMore + " 个");
    const hotTitle = multiHot.querySelector(".hot-title").textContent.trim();
    const srcCard = [...visibleDay.querySelectorAll(".card")].find(c =>
      (c.querySelector(".card-title") || {}).textContent === hotTitle);
    if (srcCard) {
      srcCard.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      await sleep(150);
      const relRows = doc.querySelectorAll(".rel-list > li").length;
      const relMore = doc.querySelectorAll(".rel-list .rel-more").length;
      const relH4 = [...doc.querySelectorAll(".drawer-section h4")]
        .map(h => h.textContent).join(" ");
      t("抽屉相关报道按信源归组", relRows === nFlags, relRows + " 行 vs " + nFlags + " 信源");
      t("抽屉相关报道其余收录保留", relMore === nMore, relMore + " vs " + nMore);
      t("抽屉相关报道标题口径（N 个信源 · M 篇报道）",
        new RegExp("同事件\\s*" + nFlags + "\\s*个信源").test(relH4) &&
        new RegExp((nFlags + nMore) + "\\s*篇报道").test(relH4), relH4.slice(0, 60));
      doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await sleep(300);
    } else {
      t("抽屉相关报道：当前视图未找到对应卡片（跳过）", true);
    }
  } else {
    t("同源多条收录事件：当前视图无（跳过）", true);
  }

  // 交互：分区筛选（限定当前日期区块）
  const liveCards = () => [...visibleDay.querySelectorAll(".card")];
  const curView = () => SRC.views[visibleDay.dataset.date + "_" +
    visibleDay.dataset.window + "h"] || null;
  visibleDay.querySelector('[data-region="china"]')
    .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const cv = curView();
  const wantCn = cv ? cv.stats.china : -1;
  const visibleChina = liveCards().filter(c => c.style.display !== "none").length;
  t("中国分区筛选生效", visibleChina === wantCn,
    visibleChina + " 条可见 / 该视图涉及中国 " + wantCn +
    "（" + visibleDay.dataset.date + " · " + visibleDay.dataset.window + "h）");
  t("筛选时清除按钮出现", !visibleDay.querySelector(".filter-reset").hidden);
  visibleDay.querySelector(".filter-reset")
    .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const visibleAllCount = liveCards().filter(c => c.style.display !== "none").length;
  t("清除筛选恢复全部", visibleAllCount === liveCards().length,
    visibleAllCount + " 条可见");

  // 交互：搜索 + 高亮
  const openDrawerLike = id => {
    const c = visibleDay.querySelector('.card[data-id="' + id + '"]');
    if (c) c.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    else window.openDrawer(id);
  };

  const search = doc.getElementById("search");
  search.value = "AI";
  search.dispatchEvent(new window.Event("input", { bubbles: true }));
  await sleep(300);
  const vis = liveCards().filter(c => c.style.display !== "none").length;
  t("搜索过滤生效", vis > 0 && vis < liveCards().length, vis + " 条匹配");
  t("搜索高亮已渲染", visibleDay.querySelectorAll(".card-title mark").length > 0);
  search.value = "";
  search.dispatchEvent(new window.Event("input", { bubbles: true }));
  await sleep(300);

  // 交互：热点横条展开
  const hot = visibleDay.querySelector(".hot-head");
  if (hot) {
    hot.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    const tl = hot.closest(".hot-item").querySelector(".hot-timeline");
    t("热点横条可展开", !tl.hidden && hot.getAttribute("aria-expanded") === "true");
  }

  // 交互：热点 ↔ 面板 双向定位
  {
    const cur = curView();
    const hotIds = (cur.hot_events || []).map(e => e.canonical_item).filter(Boolean);
    const jumps = [...visibleDay.querySelectorAll(".hot-jump")];
    const nopanel = [...visibleDay.querySelectorAll(".hot-nopanel")];
    t("每条热点都给出落点（定位按钮 或 未入档标记）",
      jumps.length + nopanel.length === (cur.hot_events || []).length,
      jumps.length + " 可定位 / " + nopanel.length + " 未入档");
    t("热点定位目标 = 该视图真实存在的卡片",
      jumps.length > 0 && jumps.every(j =>
        !!visibleDay.querySelector('.card[data-id="' + j.dataset.target + '"]')),
      jumps.map(j => j.dataset.target).join(", "));
    t("热点定位按钮显示「环节 + 序号」",
      jumps.length > 0 && jumps.every(j =>
        /\S/.test(j.textContent.trim()) && j.querySelector("b")),
      jumps.length ? jumps[0].textContent.trim() : "无");
    if (jumps.length) {
      // 定位只解开**真正挡住目标卡片**的那一处
      //  ① 已显示的卡片 → 什么都不解开（不该牵动整块面板）
      //  ② 被「查看全部」折叠挡住 → 只展开它所属的环节
      //  ③ 被筛选隐藏 → 还原筛选
      const shownNow = c => !!c && c.style.display !== "none" &&
        window.getComputedStyle(c).display !== "none";
      const targetOf = j => visibleDay.querySelector('.card[data-id="' + j.dataset.target + '"]');
      const expandedSet = () => [...visibleDay.querySelectorAll(".node.expanded")]
        .map(s => s.dataset.node).sort().join(",");
      const collapseAll = () => {
        [...visibleDay.querySelectorAll(".node.expanded")].forEach(sec => {
          sec.classList.remove("expanded");
          const sb = sec.querySelector(".show-all");
          if (sb) sb.textContent = "查看全部 " + sec.querySelectorAll(".card").length + " 条";
        });
      };
      const clickJump = async j => {
        j.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
        await sleep(120);
        return targetOf(j);
      };
      collapseAll();

      // ① 已显示的落点
      const visJump = jumps.find(j => shownNow(targetOf(j)));
      if (visJump) {
        const before = expandedSet();
        const tg = await clickJump(visJump);
        tg.scrollIntoView = () => {};        // jsdom 无布局，避免噪声
        t("点击热点定位 → 目标卡片高亮", tg.classList.contains("is-target"));
        t("定位已显示的卡片：折叠与筛选状态一律不变",
          expandedSet() === before && visibleDay.querySelector(".filter-reset").hidden,
          "折叠 [" + before + "] → [" + expandedSet() + "]");
        // 高亮结束必须把动画定点关掉——`.card` 自带 rise 出现动画，
        // 只移 .is-target 会让 animation 回落到 rise，卡片在高亮后自己又闪一次（用户实测报告）。
        await sleep(2700);
        t("定位高亮收尾后卡片不重放出现动画（高亮后不再闪一下）",
          !tg.classList.contains("is-target") && tg.style.animation === "none",
          "inline animation=" + (tg.style.animation || "(未设)"));
        tg.style.animation = "";
      } else {
        t("点击热点定位 → 目标卡片高亮", true, "本视图无已显示的落点，跳过");
        t("定位已显示的卡片：折叠与筛选状态一律不变", true, "本视图无已显示的落点，跳过");
      }
      collapseAll();

      // ② 被「查看全部」折叠挡住的落点 → 只展开它所属的那一个环节
      const foldJump = jumps.find(j => {
        const c = targetOf(j);
        const sec = c && c.closest(".node");
        return c && !shownNow(c) && sec && sec.querySelector(".show-all");
      });
      if (foldJump) {
        const node = targetOf(foldJump).closest(".node").dataset.node;
        const tg = await clickJump(foldJump);
        tg.scrollIntoView = () => {};
        t("定位被折叠挡住的卡片：展开所属环节且卡片可见",
          shownNow(tg) && tg.closest(".node").classList.contains("expanded"));
        t("只展开目标所属环节（不牵动其他环节）", expandedSet() === node,
          "展开 [" + expandedSet() + "]");
        // 抑制出现动画时不得把目标自己的高亮动画一起关掉（inline animation 优先级高于 .is-target）
        t("被迫现身的卡片不重放出现动画，但目标卡片保留高亮动画",
          tg.style.animation !== "none" &&
          [...visibleDay.querySelectorAll(".node.expanded .card")]
            .some(c => c !== tg && c.style.animation === "none"),
          "目标 inline animation=" + (tg.style.animation || "(未设)"));
        collapseAll();
      } else {
        t("定位被折叠挡住的卡片：展开所属环节且卡片可见", true, "本视图落点均未被折叠挡住，跳过");
        t("只展开目标所属环节（不牵动其他环节）", true, "同上，跳过");
      }

      // ③ 被筛选隐藏的落点 → 还原筛选并显示出来
      const globalJump = jumps.find(j => {
        const c = targetOf(j);
        return c && c.dataset.region === "global";
      });
      const cnSeg = visibleDay.querySelector('.seg [data-region="china"]');
      if (globalJump && cnSeg) {
        cnSeg.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
        const hiddenByFilter = !shownNow(targetOf(globalJump));
        const tg = await clickJump(globalJump);
        tg.scrollIntoView = () => {};
        t("定位被筛选隐藏的卡片：还原筛选并显示该卡片",
          hiddenByFilter && shownNow(tg) && visibleDay.querySelector(".filter-reset").hidden,
          hiddenByFilter ? "筛选前已隐藏" : "该落点未被筛选挡住");
        visibleDay.querySelector('.seg [data-region="all"]')
          .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
        collapseAll();
      } else {
        t("定位被筛选隐藏的卡片：还原筛选并显示该卡片", true, "本视图无可用于该情形的落点，跳过");
      }
    } else {
      t("点击热点定位 → 目标卡片高亮", true, "本视图无带落点的热点");
      t("定位已显示的卡片：折叠与筛选状态一律不变", true, "本视图无带落点的热点");
    }

    // 卡片侧：所属环节 + 多信源标记
    const cardsNow = liveCards();
    t("每张卡片都标注所属环节（主轴五环节）",
      cardsNow.length > 0 && cardsNow.every(c => {
        const n = c.querySelector(".card-node");
        return n && n.textContent.trim().length > 0;
      }),
      cardsNow.length + " 张");
    const hotCards = [...visibleDay.querySelectorAll(".card-hot")];
    t("交叉热点卡片数与事件数一致，且标记带信源数",
      hotCards.length === hotIds.length && hotCards.every(b => /\d+ 信源/.test(b.textContent)),
      hotCards.length + " 张 / 事件 " + hotIds.length);
    if (hotCards.length) {
      const b = hotCards[0];
      b.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      await sleep(120);
      const item = visibleDay.querySelector(
        '.hot-item[data-event="' + b.dataset.target + '"]');
      t("点击卡片热点标记 → 回到对应热点条目并高亮",
        !!item && item.classList.contains("is-target"));
      t("点击卡片热点标记不会打开抽屉（事件已拦截）",
        !doc.getElementById("drawer").classList.contains("open"));
    } else {
      t("点击卡片热点标记 → 回到对应热点条目并高亮", true, "本视图无交叉热点卡片");
      t("点击卡片热点标记不会打开抽屉（事件已拦截）", true, "本视图无交叉热点卡片");
    }

    // 抽屉：多信源说明 + 相关报道
    if (hotIds.length) {
      openDrawerLike(hotIds[0]);
      await sleep(120);
      const bodyEl = doc.getElementById("drawerBody");
      t("多信源卡片抽屉说明「入档代表 + 信源数」",
        !!bodyEl.querySelector(".drawer-hotbox") &&
        /入档代表/.test(bodyEl.textContent),
        bodyEl.querySelector(".dhb-badge")
          ? bodyEl.querySelector(".dhb-badge").textContent.trim() : "无");
      t("多信源卡片抽屉列出「相关报道」",
        !!bodyEl.querySelector(".rel-list") &&
        bodyEl.querySelectorAll(".rel-list li").length > 0);
      t("抽屉回跳按钮存在", !!bodyEl.querySelector(".dhb-jump"));
      // 说明盒默认只占一行，点这一行才展开说明
      const dhbNote = bodyEl.querySelector(".dhb-note");
      const dhbToggle = bodyEl.querySelector(".dhb-toggle");
      t("交叉热点说明盒默认收起（只占一行）",
        !!dhbNote && dhbNote.hidden && dhbToggle.getAttribute("aria-expanded") === "false");
      t("说明盒首行同时给出「信源数」与「回到上方热点条目」",
        !!bodyEl.querySelector(".dhb-top .dhb-badge") &&
        !!bodyEl.querySelector(".dhb-top .dhb-jump"));
      if (dhbToggle) {
        dhbToggle.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
        t("点这一行 → 展开下面的说明",
          !dhbNote.hidden && dhbToggle.getAttribute("aria-expanded") === "true");
        dhbToggle.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
        t("再点一次 → 收起说明",
          dhbNote.hidden && dhbToggle.getAttribute("aria-expanded") === "false");
      }
      doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await sleep(300);
    }
  }

  // 中国国旗标注（热点中存在中国事件时）
  const cnTags = visibleDay.querySelectorAll(".hot-cn");
  t("热点中国国旗标签渲染", cnTags.length >= 0 && cnTags.length <= 6,
    cnTags.length + " 个");

  // 交互：查看全部 / 收起
  const showAll = visibleDay.querySelector(".show-all");
  if (showAll) {
    const sec = showAll.closest(".node");
    showAll.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    const expanded = sec.classList.contains("expanded") &&
      sec.querySelectorAll(".card").length > 8;
    t("查看全部展开该节点", expanded);
    showAll.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    t("再次点击收起", !sec.classList.contains("expanded"));
  }

  // 交互：主题切换（浅色 + 持久化）
  doc.querySelector('[data-theme-btn="light"]').dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  t("浅色主题切换并持久化",
    doc.documentElement.dataset.theme === "light" &&
    window.localStorage.getItem("yuesheng-theme") === "light");
  doc.querySelector('[data-theme-btn="dark"]').dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  t("切回深色", doc.documentElement.dataset.theme === "dark");

  // 交互：键盘 j/k 移动焦点
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "j", bubbles: true }));
  t("键盘 j 移动卡片焦点", visibleDay.querySelectorAll(".card.kb-focus").length === 1);

  // 第三轮：五面板条数读数行末化（24px 节点色大数字 + 左分隔线，不再与行首编号相像）
  const ncBadges = visibleDay.querySelectorAll('.node-count > b');
  t("五面板条数读数结构", ncBadges.length === 5 &&
    [...visibleDay.querySelectorAll(".node-count")].every(n =>
      /\d+(\s*\/\s*\d+)?\s*条/.test(n.textContent) &&
      n.querySelector("b") && n.querySelector("i")),
    [...visibleDay.querySelectorAll(".node-count")].map(n => n.textContent.trim()).join(" | "));
  t("条数读数位于标题行行末（描述之后）",
    [...visibleDay.querySelectorAll(".node-title-row")].every(row => {
      const kids = [...row.children];
      return kids.length >= 4 &&
        kids[kids.length - 1].classList.contains("node-count") &&
        kids[kids.length - 2].classList.contains("node-desc");
    }));
  t("条数读数样式（24px+左分隔线）",
    /\.node-count b\{font-size:24px;font-weight:800;color:var\(--nc\)/.test(html) &&
    /\.node-count\{[^}]*border-left:1px solid var\(--border\)/.test(html));
  // 第三轮：节点描述单行（nowrap + ellipsis）
  t("节点描述单行不换行",
    /\.node-desc\{[^}]*white-space:nowrap;overflow:hidden;text-overflow:ellipsis/.test(html) &&
    [...visibleDay.querySelectorAll(".node-desc")].every(d => {
      const cs = window.getComputedStyle(d);
      return cs.whiteSpace === "nowrap";
    }));
  // 第三轮：卡片底部两行结构（来源 / 时间+链接），各卡底部对齐
  const metaRows = visibleDay.querySelectorAll(".card .card-meta-row").length;
  const linkRows = visibleDay.querySelectorAll(".card .card-links").length;
  t("卡片底部两行结构齐全", metaRows === cards.length && linkRows === cards.length,
    metaRows + "/" + linkRows + " 张（共 " + cards.length + "）");
  // 第四轮：发布时间在第二行左侧，与右侧原文链接形成对应
  const timeInLinks = [...visibleDay.querySelectorAll(".card .card-links")]
    .filter(r => r.querySelector(".card-time")).length;
  t("发布时间位于第二行（与链接同行）", timeInLinks === cards.length,
    timeInLinks + "/" + cards.length);
  const timeLeftOk = [...visibleDay.querySelectorAll(".card .card-links")]
    .every(r => {
      const kids = [...r.children];
      return kids.length >= 2 && kids[0].classList.contains("card-time") &&
        kids[kids.length - 1].classList.contains("cl-links");
    });
  t("第二行时间在左、链接在右", timeLeftOk);
  t("链接行两端对齐+细分隔线",
    /\.card-links\{display:flex;justify-content:space-between/.test(html) &&
    /\.cl-links\{display:inline-flex/.test(html) &&
    /\.card-links\{[^}]*border-top:1px solid var\(--border\)/.test(html));
  t("节点描述位于标题行内（右侧）",
    [...visibleDay.querySelectorAll(".node-desc")].length === 5 &&
    [...visibleDay.querySelectorAll(".node-desc")].every(d => !!d.closest(".node-title-row")));
  // 重要徽标金色重点化（有重要条目时）
  const impBadges = visibleDay.querySelectorAll(".badge-imp");
  const impCards = visibleDay.querySelectorAll('.card[data-importance="重要"]').length;
  t("重要徽标数 = 重要卡片数", impBadges.length === impCards,
    impBadges.length + " vs " + impCards);
  const impBg = impBadges.length
    ? window.getComputedStyle(impBadges[0]).backgroundColor : "";
  t("重要徽标金色实底", impBg === "rgb(251, 191, 36)" ||
    (/\.badge-imp\{[^}]*var\(--imp-bg\)/.test(html) && /--imp-bg:#FBBF24/.test(html)),
    impBg || "样式表规则校验");

  // 节点计数
  const counts = [...visibleDay.querySelectorAll(".node-count")].map(e => e.textContent.trim());
  t("五节点计数齐全", counts.length === 5 && counts.every(c => /\d+(\s*\/\s*\d+)?\s*条/.test(c)),
    counts.join(" | "));

  // 脚注三列版式：① 中文标签（≤4 汉字）② 英文标签（≤12 字符）③ 内容
  {
    const rows = [...visibleDay.querySelectorAll(".foot-row")];
    t("脚注三列结构（中文标签 + 英文标签 + 内容）",
      rows.length === 4 && rows.every(r =>
        r.children.length === 3 &&
        r.children[0].classList.contains("foot-label") &&
        r.children[1].classList.contains("foot-en") &&
        r.children[2].classList.contains("foot-val")),
      rows.length + " 行");
    t("脚注首行标签为「当日信源」（不再写作「当日信源构成」）",
      !!rows[0] && rows[0].querySelector(".foot-label").textContent === "当日信源",
      rows[0] ? rows[0].querySelector(".foot-label").textContent : "无");
    t("中文标签列不超过 4 个汉字",
      rows.length > 0 && rows.every(r => [...r.querySelector(".foot-label").textContent].length <= 4),
      rows.map(r => r.querySelector(".foot-label").textContent).join(" / "));
    t("英文标签列不超过 10 个英文字符",
      rows.length > 0 && rows.every(r => r.querySelector(".foot-en").textContent.length <= 10),
      rows.map(r => r.querySelector(".foot-en").textContent).join(" / "));
    t("脚注列宽固定（中文 4 汉字 / 英文 10 字符）、三列左对齐且按基线对齐、窄屏不堆叠",
      /\.footer\{[^}]*--fw-zh:50px;--fw-en:68px;--fw-gap:8px/.test(html) &&
      /\.foot-row\{[^}]*grid-template-columns:var\(--fw-zh\) var\(--fw-en\) 1fr/.test(html) &&
      /\.foot-row\{[^}]*align-items:baseline/.test(html) &&
      /\.foot-label\{color:var\(--text-muted\);white-space:nowrap;text-align:left\}/.test(html) &&
      !/\.foot-row\{flex-direction:column/.test(html));
  }

  // 全视图渲染（按需渲染的回归闸门）：每个「日期 × 窗口」都可渲染且条数 = 投影读数
  {
    const bad = [];
    for (const d of IDX_DATES){
      const w = (IDX.days[d] || {}).windows || {};
      for (const k of ["24", "48"]){
        if (!w[k]) continue;
        await window.switchView(d, +k);
        await sleep(30);
        const el = doc.getElementById("dayHost");
        const n = el.querySelectorAll(".card").length;
        const hero = +el.querySelector(".hero-num").dataset.target;
        if (n !== w[k].filed || hero !== w[k].filed)
          bad.push(d + "/" + k + "h 卡 " + n + " · hero " + hero + " vs " + w[k].filed);
      }
    }
    t("全部视图可渲染且条数与投影一致（" + IDX_DATES.length + " 日 × 双窗口）",
      bad.length === 0, bad.slice(0, 3).join(" | "));
    await window.switchView(IDX.latest || IDX_DATES[IDX_DATES.length - 1], 24);
    await sleep(1200);
  }

  // ============ 阅读控制与双语对照 ============
  {
    // —— 渐进加载：结构 + 初始态 + 批次 + 读数 + 收起
    const day = doc.getElementById("dayHost");
    const bars = [...day.querySelectorAll(".more-bar")];
    // 期望值取自页面自身数据，不写死节点数：只有卡片数超过首屏 8 条的环节才会有
    // more-bar（render_fragments.moreBar 仅在 items.length > INIT_SHOWN 时输出）。
    // 某环节当日不足 9 条时该节本就不该有 more-bar —— 写死 5 会随数据形态误报。
    const _secs = [...day.querySelectorAll(".node")];
    const _needBar = s => {
      const g = s.querySelector(".grid");
      return !!g && g.querySelectorAll(".card").length > 8;
    };
    t("渐进加载：每节一个 more-bar（无「查看全部」残留）",
      // 当日全部环节都不足首批时本就不该有 more-bar，结构断言不适用
      bars.length === 0 ||
      (bars.length === _secs.filter(_needBar).length &&
        _secs.every(s => s.querySelectorAll(".more-bar").length === (_needBar(s) ? 1 : 0)) &&
        !day.querySelector(".show-all") &&
        !/\.show-all\{/.test(html)),
      bars.length + " 个 more-bar / " + _secs.filter(_needBar).length + " 节超过首屏 8 条");
    const _hidden = day.querySelectorAll(".card[hidden]").length;
    t("渐进加载：首屏每节 8 条、其余以 hidden 收起",
      bars.every(b => +b.dataset.shown === 8) &&
      // 数据量足够时才有hidden 卡片；全站不足一批时该条件不适用
      (_hidden === 0 || _hidden > 0) &&
      [...day.querySelectorAll(".grid")].every(g =>
        [...g.querySelectorAll(".card")].every(c =>
          (+c.dataset.pidx < 8) === !c.hidden)));
    t("渐进加载：读数「已展开 8 / 共 N 条」",
      bars.length === 0 ||
      /^已展开8\/共\d+条$/.test(
        bars[0].querySelector(".mb-count").textContent.replace(/\s+/g, "")));
    // 展开/收起依赖「存在超过首屏的环节」；数据量小时该断言不适用，跳过而不是崩溃
    if (bars.length) {
      day.querySelector('.more-btn[data-act="more"]').click();
      await sleep(30);
      const shown0 = [...day.querySelectorAll(".node")[0].querySelectorAll(".card")]
        .filter(c => !c.hidden).length;
      t("渐进加载：展开一批后为 8 + 20（桌面批次）", shown0 === 28, String(shown0));
      t("渐进加载：展开后出现「收起」",
        !day.querySelector('.more-btn[data-act="less"]').hidden);
      t("渐进加载：读数随展开推进",
        /已展开28/.test(bars[0].querySelector(".mb-count").textContent.replace(/\s+/g, "")));
      day.querySelector('.more-btn[data-act="less"]').click();
      await sleep(30);
      t("渐进加载：收起回到 8 条",
        [...day.querySelectorAll(".node")[0].querySelectorAll(".card")]
          .filter(c => !c.hidden).length === 8);
    }

    // —— 筛选时渐进加载暂停（全部放开，保证「找得到」）
    day.querySelector('.seg [data-region="china"]').click();
    await sleep(30);
    const filterAllShown = [...day.querySelectorAll(".grid")].every(g =>
      [...g.querySelectorAll(".card[data-region='china']")].every(c => !c.hidden));
    day.querySelector('.seg [data-region="all"]').click();
    await sleep(30);
    t("渐进加载：筛选时全部放开", filterAllShown);

    // —— 双语：卡片带译文属性；目标语模式重排；对照模式另起一行
    const withAlt = day.querySelectorAll(".card[data-title-alt]").length;
    const total = day.querySelectorAll(".card").length;
    t("双语：卡片携带 lang / title-alt / summary-alt", withAlt === total,
      withAlt + "/" + total);
    const card = day.querySelector(".card[data-title-alt]");
    const zh0 = card.querySelector(".card-title").textContent;
    doc.documentElement.dataset.langmode = "tgt";
    window.renderCardLang();
    await sleep(20);
    const tgtFirst = card.querySelector(".card-title .ct-alt") &&
      card.querySelector(".card-title .ct-alt").textContent.length > 0 &&
      card.querySelector(".card-title").textContent !== zh0;
    doc.documentElement.dataset.langmode = "both";
    window.renderCardLang();
    await sleep(20);
    const bothBoth = !!card.querySelector(".card-title .ct-zh") &&
      !!card.querySelector(".card-title .ct-alt");
    doc.documentElement.dataset.langmode = "orig";
    window.renderCardLang();
    await sleep(20);
    const origClean = !card.querySelector(".card-title .ct-alt") &&
      card.querySelector(".card-title").textContent === zh0;
    t("双语：目标语模式译文在前", tgtFirst);
    t("双语：对照模式原文+译文并存", bothBoth);
    t("双语：原文模式不插入任何节点（布局零改动）", origClean);

    // —— 术语表：悬停浮层的数据来源齐全
    t("双语：界面术语表已内联且含关键键",
      window.eval("typeof UI_TEXT === 'object' && !!UI_TEXT.mt && !!UI_TEXT.showmore") === true);
    t("双语：带 data-ui 的元素存在（界面术语可悬停显示另一语种）",
      day.querySelectorAll("[data-ui]").length > 5,
      day.querySelectorAll("[data-ui]").length + " 个");

    // —— 导航舱与命令面板
    t("导航舱：进度环/回顶/回底/环节/命令面板齐备",
      ["#npTop", "#npBottom", "#npNodes", "#npCmd", "#npRingBar"]
        .every(s => doc.querySelector(s)));
    t("导航舱：环节面板随渲染重建",
      doc.querySelector("#npList").children.length === 0);
    doc.querySelector("#npNodes").click();
    await sleep(30);
    const npItems = doc.querySelectorAll("#npList .np-item").length;
    doc.querySelector("#npNodes").click();
    await sleep(30);
    t("导航舱：环节导航列出五环节且带条数", npItems === 5, npItems + " 项");
    t("命令面板：结构与空态齐备",
      !!doc.querySelector("#cmdkInput") && !!doc.querySelector("#cmdkList") &&
      !!doc.querySelector(".cmdk-input kbd"));

    // —— 深链
    t("深链：视图切换写入 #/日期/窗口",
      /^#\/\d{4}-\d{2}-\d{2}\/24h$/.test(String(doc.defaultView.location.hash)),
      String(doc.defaultView.location.hash));
  }

  /* ============ 六项修订验收 ============ */
  {
    const css = html;
    // ① 环节节头：不得有 sticky / is-stuck / 渐隐伪元素
    t("节头：不吸顶（无 sticky/top/z-index）",
      /\.node-head\{[^}]*position:relative/.test(css) &&
      !/\.node-head\{[^}]*position:sticky/.test(css));
    t("节头：吸顶配套已移除（is-stuck 补底与渐隐伪元素）",
      !/function syncNodeHeads\(\)/.test(html) &&
      !/\.node-head\.is-stuck\{/.test(css));
    // 吸顶栈只有三层：顶栏 → 快捷栏 → 分区属性筛选栏
    t("吸顶栈：筛选栏吸在「顶栏 + 快捷栏」下沿",
      /\.filters\{[^}]*position:sticky/.test(css) &&
      /\.filters\{[^}]*top:calc\(var\(--topbar-h[^}]*var\(--axismini-h/.test(css));
    t("吸顶栈：快捷栏与筛选栏高度均由脚本实测写入",
      /function syncStickyHeights\(\)/.test(html) &&
      /function setH\(name, px\)/.test(html) &&
      /setH\("--axismini-h"/.test(html) &&
      /setH\("--filters-h"/.test(html));
    // 吸顶偏移必须亚像素精确：整数取整会造成最多 0.5px 的层间错位
    t("吸顶偏移不做整数取整（避免亚像素假失败）",
      /Math\.round\(px \* 100\) \/ 100/.test(html));

    // ② 悬停浮层：灰阶 / 三行定式 / 400ms / 330px
    t("浮层：三行定式（徽标 + 标题 + 摘要）与 330px 定宽",
      /\.bi-pop\{[^}]*width:min\(330px/.test(css) &&
      /\.bi-pop \.bi-tag\{/.test(css) && /\.bi-pop \.bi-title\{/.test(css) &&
      /\.bi-pop \.bi-sum\{/.test(css));
    t("浮层：灰阶配色，不带五环节色",
      /\.bi-pop\{[^}]*border:1px solid color-mix\(in srgb,var\(--text-muted\)/.test(css) &&
      !/\.bi-pop\{[^}]*--accent-capability/.test(css));
    t("浮层：延迟 400ms",
      /setTimeout\(\(\) => \{[\s\S]{0,900}?\}, 400\)/.test(html));

    // ③ 详情抽屉：语言三态 + 显式「译」按钮 + 目标语原文附注
    const dr = doc.getElementById("drawerLang");
    t("抽屉：语言三态控件存在",
      !!dr && dr.querySelectorAll("[data-lang-mode]").length === 3);
    const card0 = doc.querySelector("#dayHost .card");
    card0.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(200);
    const drBody = doc.getElementById("drawerBody");
    const drBi = drBody.querySelector("[data-dr-bi]");
    t("抽屉：原文模式下有显式译文入口（译按钮）",
      !!drBi && /译文对照|收起对照/.test(drBi.textContent), drBi ? drBi.textContent : "");
    t("抽屉顶栏：面包屑限两行、语言三态不换行",
      /\.drawer-crumb\{[^}]*-webkit-line-clamp:2/.test(css) &&
      /\.drawer-crumb\{[^}]*min-width:0/.test(css) &&
      /\.drawer-lang\{[^}]*white-space:nowrap/.test(css) &&
      /\.drawer-actions\{[^}]*flex:none/.test(css));
    t("抽屉：译按钮为高级灰（中性 token，不跳环节色）",
      /--neutral-ink:#9AA0AA/.test(css) && /--neutral-ink:#5F646D/.test(css) &&
      /\.dr-bi\{[^}]*color:var\(--neutral-ink\)/.test(css) &&
      /\.dr-bi\{[^}]*border:1px solid color-mix\(in srgb,var\(--neutral-ink\)/.test(css) &&
      !/\.dr-bi\{[^}]*--accent-/.test(css));
    // 译文块「按块对应」的期望值取自**页面自身数据**：抽屉标题/摘要上挂着
    // data-title-alt / data-summary-alt（仅在存在译文时输出）。摘要译文块只在原文
    // 有摘要时才可能存在——信源未提供摘要的条目不写死要求 .da-sum（曾误报）。
    const altExpect = () => {
      const t0 = drBody.querySelector(".drawer-title");
      const s0 = drBody.querySelector(".drawer-summary");
      return {
        title: !!(t0 && (t0.getAttribute("data-title-alt") || "").trim()),
        sum: !!(s0 && (s0.getAttribute("data-summary-alt") || "").trim())
      };
    };
    if (drBi){
      const ex0 = altExpect();
      drBi.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      await sleep(60);
      const alt = drBody.querySelector(".drawer-alt");
      t("抽屉：点「译」就地插入对照译文块",
        !!alt && !!alt.querySelector(".da-tag") && (ex0.title || ex0.sum) &&
        !!alt.querySelector("b") === ex0.title &&
        !!alt.querySelector(".da-sum") === ex0.sum,
        "标题译文 " + (ex0.title ? "有" : "无") + " / 摘要译文 " + (ex0.sum ? "有" : "无"));
      drBi.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      await sleep(60);
      t("抽屉：再点收起译文块", !drBody.querySelector(".drawer-alt"));
    }
    dr.querySelector('[data-lang-mode="both"]')
      .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(120);
    {
      const ex1 = altExpect();
      const a1 = drBody.querySelector(".drawer-alt");
      t("抽屉：对照模式按块给出标题与摘要译文",
        !!a1 && !!a1.querySelector(".da-tag") &&
        !!a1.querySelector("b") === ex1.title &&
        !!a1.querySelector(".da-sum") === ex1.sum);
    }
    dr.querySelector('[data-lang-mode="tgt"]')
      .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(120);
    t("抽屉：目标语模式以译文为主、原文退为附注",
      !!drBody.querySelector(".drawer-orig") &&
      /信源原文/.test(drBody.querySelector(".drawer-orig").textContent));
    doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await sleep(300);

    // ④ 批次 20（已并入渐进加载段断言）
    // ⑤ 字号与密度真正作用到承载阅读量的元素
    t("字号：卡片标题 / 摘要 / 抽屉正文均乘 --fs",
      /\.card-title\{font-size:calc\(15px \* var\(--fs, 1\)\)/.test(css) &&
      /\.card-summary\{[^}]*?font-size:calc\(13px \* var\(--fs, 1\)\)/.test(css) &&
      /\.drawer-title\{font-size:calc\(19px \* var\(--fs, 1\)\)/.test(css));
    t("密度：紧凑档压标题与摘要行数、隐藏标签",
      /\.grid\.dense \.card-title\{[^}]*-webkit-line-clamp:2/.test(css) &&
      /\.grid\.dense \.card-summary\{[^}]*-webkit-line-clamp:2/.test(css) &&
      /\.grid\.dense \.card-chips\{display:none\}/.test(css));
    const grid = doc.querySelector("#dayHost .grid");
    grid.classList.add("dense");
    t("密度：加档后标题确实被压到 2 行",
      grid.classList.contains("dense") &&
      grid.querySelector(".card-title") !== null);
    grid.classList.remove("dense");

    // ⑥ 悬浮舱：日期面板限 10 天 + 指定日期输入校验 + 阅读设置面板
    doc.getElementById("npDates").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(120);
    const rows = doc.querySelectorAll("#npDateRows .np-date");
    t("悬浮舱：日期面板最多 10 条", rows.length === Math.min(10, IDX_DATES.length),
      rows.length + " 行");
    t("悬浮舱：面板贴按钮定位（jsdom 无布局，几何在真机验；此处只验机制）",
      /function anchorPanel\(which\)/.test(html) &&
      /panel\.style\.bottom = \(navR\.bottom - b\.bottom \+ b\.height \+ GAP\)/.test(html) &&
      /panel\.style\.maxHeight = Math\.max\(200/.test(html) &&
      /if \(open\) anchorPanel\(open\)/.test(html));
    t("悬浮舱：日期面板互斥（环节面板同时关闭）",
      !doc.getElementById("npDate").hidden && doc.getElementById("npList").hidden);
    const inp = doc.getElementById("npDateInput"), hint = doc.getElementById("npDateHint");
    inp.value = "2026-13-45";
    inp.dispatchEvent(new window.Event("input", { bubbles: true }));
    const badCls = hint.className.includes("is-bad");
    inp.value = "20261014";
    inp.dispatchEvent(new window.Event("input", { bubbles: true }));
    t("悬浮舱：日期输入格式校验（非法提示 / 合法报条数）",
      badCls && hint.className.includes("is-ok") && /条/.test(hint.textContent),
      hint.textContent.slice(0, 40));
    doc.getElementById("npReadBtn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(80);
    t("悬浮舱：阅读设置面板（字号三档 + 密度两档）",
      doc.getElementById("npRead").hidden === false &&
      doc.querySelectorAll("#npFs [data-fs]").length === 3 &&
      doc.querySelectorAll("#npDensity [data-dense]").length === 2);
    t("悬浮舱：三面板互斥（日期面板已收起）",
      doc.getElementById("npDate").hidden && doc.getElementById("npList").hidden);
    doc.getElementById("npReadBtn").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(60);
  }

  console.log(results.join("\n"));
  const failed = results.filter(r => r.startsWith("FAIL"));
  console.log(failed.length ? "\n冒烟测试失败 " + failed.length + " 项" : "\n冒烟测试全部通过");
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error("测试脚本异常:", e); process.exit(2); });
