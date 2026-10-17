/* 前端渲染纯函数（S2）——输入 VIEW-01 投影，输出 HTML 片段。
 *
 * 设计约束
 * - **纯函数**：不碰 DOM、不读全局状态，输入投影 → 输出字符串。同一份实现既用于
 *   离线单文件（Python 构建时逐段比对）也用于运行态薄壳（浏览器内联渲染）。
 * - **只吃投影**：节点归属、地域判定、重要度、排序与序号、信源归组全部由 L1/L2
 *   产出，本层不做任何业务推算（规范第三篇 §8.2）。
 * - **定义来自资产**：国旗画法 / 地球徽标 / 国家中文名 / 节点元数据 / 小图标 /
 *   百分比格式化取自 `assets/runtime_assets.js`（由 gen_runtime_assets.py 从 Python
 *   单一实现导出），不在本文件重写。
 * - 与 Python 侧的对应实现（render_dashboard.py）保持**逐字节同构**：包括转义规则、
 *   属性顺序、空白与换行，故比对脚本做的是字符串相等而不是「看起来一样」。
 */
var FRAGMENTS = (function () {
  "use strict";

  /* HTML 转义：与 Python `esc()` 同规则（& < > "，& 先转） */
  function esc(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* 取域名（去 www.）：与 Python `url_domain()` 同构，非法 URL 落到兜底文案 */
  function urlDomain(url) {
    try {
      return new URL(url || "").hostname.replace(/^www\./, "") || "";
    } catch (_e) {
      return "";
    }
  }

  /* 国家/地区中文名（未知代码回落到 ISO 码，再回落到「未知」） */
  function countryName(code) {
    return COUNTRY_NAMES[code || ""] || code || "未知";
  }

  /* 生成时间 → 「10.15 03:12」（与 Python `short_gen()` 同构） */
  function shortGen(gen) {
    if (!gen) return "—";
    const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/
      .exec(String(gen).slice(0, 19));
    if (!m) return String(gen).slice(0, 16);
    return m[2] + "." + m[3] + " " + m[4] + ":" + m[5];
  }

  /* 来源明细按「信源」归组：同一信源多条只算一组（与 `source_count` 同口径）。
     返回 [{key, country, reports: [...]}]，顺序按成员首次出现。 */
  function sourceGroups(members) {
    const groups = [], index = {};
    (members || []).forEach(function (m) {
      const key = m.source_id || m.source_name || m.item_id;
      if (index[key] === undefined) {
        index[key] = groups.length;
        groups.push({ key: key, country: m.country || "", reports: [] });
      }
      groups[index[key]].reports.push(m);
    });
    return groups;
  }

  /* ---------------------------------------------------------------- L1 总览 */

  /* Hero：入档条数为视觉主体，日期/地域构成/meta 行/分布面板为辅 */
  function hero(v, winCounts) {
    const total = v.items.length;
    const meta = v.meta || {};
    const cn = (v.stats || {}).china || 0;
    const win = winCounts || {};
    const w24 = win["24"] === undefined ? total : win["24"];
    const w48 = win["48"] === undefined ? total : win["48"];
    const rows = (v.nodes || []).map(function (n) {
      const pct = total ? n.count * 100.0 / total : 0.0;
      return '<div class="hd-row" style="--nc:' + NODE_META[n.key].dark + '">' +
        '<span class="hd-name">' + esc(n.name) + "</span>" +
        '<span class="hd-bar"><i style="width:' + fixed(pct, 1) + '%"></i></span>' +
        '<span class="hd-num"><b>' + n.count + "</b><em>" +
        fixed(pct, 0) + "%</em></span></div>";
    });
    const gen = v.generated_at;
    const liveBadge = v.live
      ? '<span class="live-badge" title="该自然日尚未结束；本数据集生成于 ' +
        esc(gen || "—") + '，此后新发布的内容将在下次抓取后补入">进行中 · 截至 ' +
        esc((gen || "").slice(11, 16) || "—") + "</span>"
      : "";
    return '<section class="hero" aria-label="当日总览">' +
      '<div class="hero-main">' +
      '<div class="hero-topline">' +
      '<p class="hero-eyebrow"><span class="hero-pulse" aria-hidden="true"></span>' +
      "DAILY AI BRIEFING · 每日晨报</p>" +
      '<p class="hero-date-mini"><b>' + esc(meta.md) + "</b>" +
      "<span>" + esc(meta.full) + " " + esc(meta.weekday) + " · 北京时间 UTC+8</span>" +
      liveBadge + "</p>" +
      "</div>" +
      '<div class="hero-figure">' +
      '<span class="hero-num stat-num" data-target="' + total + '">0</span>' +
      '<span class="hero-unit">条</span>' +
      '<span class="hero-fig-label"><b>今日入档 AI 资讯</b>' +
      "<i>TODAY&#8217;S FILED ITEMS</i></span>" +
      '<span class="hero-region" aria-label="入档资讯地域构成">' +
      '<span class="hr-sep" aria-hidden="true"></span>' +
      '<span class="hr-item hr-cn" title="当日涉及中国的入档资讯总条数' +
      '（按内容主体判定，含非交叉报道；是总条数的子集拆解）">' +
      flagSvg("CN", 16) + "<b>" + cn + "</b> 涉及中国</span>" +
      '<span class="hr-item hr-global" title="当日入档的非中国主体资讯条数' +
      '（与涉及中国相加 = 入档总条数）">' +
      globeSvg(16) + "<b>" + (total - cn) + "</b> 全球资讯</span>" +
      "</span>" +
      "</div>" +
      '<div class="hero-meta">' +
      '<span class="hm-item hm-win">' +
      '<span class="hw-label">时间窗口</span>' +
      '<span class="hw-switch' + (v.window_hours === 48 ? " on-48" : "") +
      '" role="group" aria-label="日报窗口口径">' +
      '<span class="hw-thumb" aria-hidden="true"></span>' +
      '<button type="button" class="hw-btn' + (v.window_hours === 24 ? " is-on" : "") +
      '" data-window="24" ' +
      'title="当日整日（' + esc(meta.md) + " 00:00 ~ 次日 00:00），共 " +
      esc(String(w24)) + ' 条">24<small>H</small></button>' +
      '<button type="button" class="hw-btn' + (v.window_hours === 48 ? " is-on" : "") +
      '" data-window="48" ' +
      'title="前一日 + 当日整日（48 小时），共 ' + esc(String(w48)) +
      ' 条">48<small>H</small></button>' +
      "</span></span>" +
      '<span class="hm-right">' +
      '<span class="hm-fact" title="当日入档资讯涉及的启用信源数量">' +
      ICON_SOURCE + "信源 · <b>" + (v.stats || {}).sources + "</b>个</span>" +
      "<i></i>" +
      '<span class="hm-fact" title="整理依据：AI资讯体系规范 AIIS-01（展现两层架构）">' +
      ICON_SPEC + "规范 · <b>AIIS-01</b></span>" +
      "<i></i>" +
      '<span class="hm-fact hm-gen" title="本日报数据的生成时间（北京时间 UTC+8）">' +
      ICON_CLOCK + '生成时间 · <span class="hm-tval">' + esc(shortGen(gen)) +
      "</span></span>" +
      "</span>" +
      "</div>" +
      "</div>" +
      '<aside class="hero-dist" aria-label="当日五环节分布">' +
      '<div class="hd-title">当日分布<i>BY VALUE-CHAIN NODE</i></div>' +
      '<div class="hd-rows">' + rows.join("\n      ") + "</div>" +
      "</aside>" +
      "</section>";
  }

  /* 五节点主轴（核心看点）：大卡 + 序号 + 计数 + 定义 + 头条旗标 */
  function axisHero(v) {
    const nodes = (v.nodes || []).map(function (n, i) {
      const flag = n.headline
        ? '<span class="ahn-flag" title="今日头条">头条</span>' : "";
      return '<button type="button" class="ah-node" data-node="' + esc(n.key) +
        '" data-total="' + n.count + '" style="--nc:' + NODE_META[n.key].dark +
        '" aria-current="false">' +
        '<span class="ahn-top"><span class="ahn-index">' +
        String(i + 1).padStart(2, "0") + "</span>" +
        '<span class="ahn-count">' + n.count + " 条</span></span>" +
        '<span class="ahn-names"><b>' + esc(n.name) + "</b><i>" + esc(n.en) +
        "</i></span>" +
        '<span class="ahn-desc">' + esc(n.short) + "</span>" + flag +
        "</button>";
    });
    return '<nav class="axis-hero" aria-label="AI 产业化价值链">' +
      '<div class="ah-head">' +
      '<div class="ah-title">' +
      '<span class="ah-icon" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" ' +
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">' +
      '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 ' +
      '1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>' +
      "</svg></span>" +
      '<span class="ah-title-text"><b>AI 产业化价值链</b>' +
      "<i>AI INDUSTRIALIZATION VALUE CHAIN · 五环节主线</i></span>" +
      "</div>" +
      "</div>" +
      '<div class="ah-track">' +
      '<div class="ah-flow" aria-hidden="true"></div>' +
      nodes.join("\n      ") +
      "</div>" +
      "</nav>";
  }

  /* 迷你主轴：滚动后常驻顶栏下方 */
  function axisMini(v) {
    const btns = (v.nodes || []).map(function (n) {
      const dot = n.headline ? '<em class="am-flag" title="今日头条">头条</em>' : "";
      return '<button type="button" class="am-btn" data-node="' + esc(n.key) +
        '" data-total="' + n.count + '" style="--nc:' + NODE_META[n.key].dark +
        '" aria-current="false">' +
        '<i aria-hidden="true"></i><span>' + esc(n.name) + "</span><em>" +
        n.count + "</em>" + dot + "</button>";
    });
    return '<nav class="axis-mini" aria-label="价值链快捷导航">' +
      '<div class="am-inner"><span class="am-brand">AI 价值链 · AI VALUE CHAIN</span>' +
      btns.join("") + "</div></nav>";
  }

  /* 热点横条：标题右侧「交叉热点」统计 + 每条名称后来源国旗 */
  function hotbar(events) {
    events = events || [];
    const stats = '<div class="hotbar-stats">' +
      '<span class="hs-chip hs-hot" title="多信源交叉报道的事件数' +
      '（同一事件 ≥2 个信源报道）">' +
      "<b>" + events.length + "</b>" +
      '<span class="hs-t">交叉热点<i>CROSS-SOURCED</i></span></span>' +
      "</div>";
    let body;
    if (!events.length) {
      body = '<p class="hot-empty">今日暂无多信源交叉事件。</p>';
    } else {
      const out = events.map(function (ev) {
        const groups = sourceGroups(ev.members);
        // 涉及中国：与卡片 .card-region 同一措辞、同一视觉。
        // 判定口径由 L2 给出（取面板落点条目的 region），展现层不自行推算——
        // 否则会出现「热点条标了中国、点进去的卡片却没有标记」的矛盾。
        const cnTag = ev.china
          ? '<span class="hot-cn" title="该事件的入档条目涉及中国">' +
            flagSvg("CN", 11) + "涉及中国</span>"
          : "";
        const names = [], flags = [];
        groups.forEach(function (g) {
          const cname = countryName(g.country);
          const sname = g.reports[0].source_name || "";
          names.push(sname + "（" + cname + "）");
          flags.push('<span class="hot-flag" title="' + esc(sname) + " · " +
            esc(cname) + '">' + flagSvg(g.country, 16) + "</span>");
        });
        const flagHtml = '<span class="hot-flags" title="涉及信源：' +
          esc(names.join("、")) + '">' + flags.join("") + "</span>";
        let rows = "";
        groups.forEach(function (g) {
          const cname = countryName(g.country);
          let pri = 0;
          g.reports.forEach(function (m, k) {
            if ((m.authority || 0) > (g.reports[pri].authority || 0)) pri = k;
          });
          const ps = g.reports[pri];
          let more = "";
          g.reports.forEach(function (x, k) {
            if (k === pri) return;
            more += '<a class="hot-more" href="' + esc(x.url) + '" target="_blank" ' +
              'rel="noopener noreferrer" title="' + esc(ps.source_name || "") +
              ' 就同一事件的另一条收录">' +
              esc(urlDomain(x.url) || "另一条收录") + "</a>";
          });
          rows += "<li>" + flagSvg(g.country, 14) +
            '<a href="' + esc(ps.url) + '" target="_blank" ' +
            'rel="noopener noreferrer">' + esc(ps.source_name) + "</a>" +
            '<span class="hot-src-meta">' + esc(cname) + " · 权威度 " +
            esc(ps.authority) + "</span>" + more + "</li>";
        });
        // 热点 → 面板的落点：所属环节 + 在该环节（实为当日编号）里的序号。
        // 由 L2 给出（canonical_*），展现层只负责画，不自行推算。
        const nodeName = ev.canonical_node_name || "";
        const jump = ev.canonical_item
          ? '<button type="button" class="hot-jump" data-target="' +
            esc(ev.canonical_item) + '"' +
            (ev.canonical_node
              ? ' style="--nc:var(--accent-' + esc(ev.canonical_node) + ')"' : "") +
            ' title="该事件在下方「' + esc(nodeName) + '」环节第 ' +
            esc(String(ev.canonical_num)) + ' 条 — 点击定位到这一条">' +
            '<i aria-hidden="true"></i>' + esc(nodeName) +
            "<b>" + esc(String(ev.canonical_num)) + "</b></button>"
          : '<span class="hot-nopanel" title="该多信源事件在本窗口没有入档条目' +
            '（成员均未入档），面板中没有对应卡片">未入档</span>';
        return '<div class="hot-item" data-event="' + esc(ev.event_id) + '">' +
          '<div class="hot-row">' +
          '<button class="hot-head" type="button" aria-expanded="false">' +
          '<span class="hot-count">' +
          (ev.source_count === undefined ? groups.length : ev.source_count) +
          " 信源</span>" +
          // 热点标题的对照译文：来自入档代表条目，与卡片同一份译文
          '<span class="hot-title"' +
          (ev.canonical_title_alt
            ? ' data-lang="' + esc(ev.canonical_lang || "") + '" data-title-alt="' +
              esc(ev.canonical_title_alt) + '"'
            : "") +
          ">" + esc(ev.canonical_title) + "</span>" +
          flagHtml + cnTag +
          '<svg class="hot-arrow" viewBox="0 0 24 24" width="14" height="14" ' +
          'fill="none" stroke="currentColor" stroke-width="2">' +
          '<path d="M6 9l6 6 6-6"/></svg></button>' +
          jump + "</div>" +
          '<ul class="hot-timeline" hidden>' + rows + "</ul>" +
          "</div>";
      });
      body = out.join("\n      ");
    }
    return '<section class="hotbar" aria-label="今日热点">' +
      '<div class="hotbar-head">' +
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2c1 ' +
      '4-2 5-2 8a4 4 0 0 0 8 0c0-1-.5-2-1-3 3 2 5 5 5 8a8 8 0 1 1-16 0c0-5 4-7 ' +
      '6-13z"/></svg>' +
      '<div class="hotbar-title"><b>今日热点</b>' +
      "<i>CROSS-SOURCED · 多信源交叉报道，点击展开来源</i></div>" +
      stats +
      "</div>" + body + "</section>";
  }

  /* 分区与属性筛选（标签词表来自投影 stats.by_tag，不再自行归纳）
     data-ui 指向术语表键：悬停时显示另一语种，不另占版面（见外壳的悬停对照层）。 */
  function filters(v) {
    const tags = Object.keys((v.stats || {}).by_tag || {}).sort();
    const tagchips = tags.map(function (t) {
      return '<button type="button" class="tagchip" data-tag="' + esc(t) +
        '" aria-pressed="false">' + esc(t) + "</button>";
    }).join("");
    return '<div class="filters" role="toolbar" aria-label="筛选">' +
      '<span class="filter-label" data-ui="region">分区<i>REGION</i></span>' +
      '<div class="seg" role="group" aria-label="地域分区">' +
      '<button type="button" data-region="all" data-ui="all" aria-pressed="true">全部</button>' +
      '<button type="button" data-region="global" data-ui="global" aria-pressed="false">全球</button>' +
      '<button type="button" data-region="china" data-ui="china" aria-pressed="false">中国</button>' +
      "</div>" +
      '<span class="filter-label" data-ui="tags">属性<i>TAGS</i></span>' +
      tagchips +
      '<button type="button" class="filter-reset" data-ui="clear" hidden>清除筛选</button>' +
      "</div>";
  }

  /* 单张卡片（L1 正文条目）；k = 本分区内序号（渐进加载用，缺省即不收起） */
  function card(it, k) {
    const tags = (it.tags_b || []).slice(0, 3).map(function (t) {
      return '<span class="chip chip-b">' + esc(t) + "</span>";
    }).join("");
    const hot = it.importance === "头条"
      ? '<span class="badge-hot" data-ui="headline" title="头条资讯">头条</span>'
      : (it.importance === "重要"
        ? '<span class="badge-imp" data-ui="important">重要</span>' : "");
    /* 双语：原文仍是卡片主体（规范「标题不改写」），译文只作为**附加层**随条目下发，
       由外壳在悬停 / 对照模式 / 触屏点按时按需取用，默认不占版面、不改布局。 */
    const alt = (it.title_alt || it.summary_alt)
      ? ' data-lang="' + esc(it.lang || "") + '"' +
        ' data-title-alt="' + esc(it.title_alt || "") + '"' +
        ' data-summary-alt="' + esc(it.summary_alt || "") + '"' +
        // v1.15：同时带上原文，目标语模式下悬停取原文（浮层方向随语言模式对调）
        ' data-title-orig="' + esc(it.title || "") + '"' +
        ' data-summary-orig="' + esc(it.summary || "") + '"'
      : "";
    const mirror = it.mirror_url
      ? '<a class="card-mirror" href="' + esc(it.mirror_url) + '" target="_blank" ' +
        'rel="noopener noreferrer" title="聚合镜像页" ' +
        'onclick="event.stopPropagation()">镜像</a>'
      : "";
    const srcTitle = COUNTRY_NAMES[it.country || ""] || it.country || "未知地区";
    // 所属环节（主轴五环节之一）：卡片置右，一眼看出这条在价值链上的位置
    const nodeMeta = NODE_META[it.node] || {};
    const nodeName = nodeMeta.name || it.node_name || "";
    const nodeChip = nodeName
      ? '<span class="card-node"' +
        (it.node ? ' style="--nc:var(--accent-' + esc(it.node) + ')"' : "") +
        ' title="所属环节：' + esc(nodeName) +
        '（AI 产业化价值链：能力→产品→产业→治理→趋势）">' +
        '<i aria-hidden="true"></i>' + esc(nodeName) + "</span>"
      : "";
    // 交叉热点标记：本条是多信源事件的入档代表，点击回到上方热点条目
    const hotBadge = it.hot_event
      ? '<button type="button" class="card-hot" data-target="' + esc(it.hot_event) +
        '" title="本条是上方「交叉热点」的入档代表：该事件由 ' + it.hot_sources +
        ' 个信源同时报道，详情「相关报道」列出全部信源；点击回到上方热点条目">' +
        "交叉热点 · " + it.hot_sources + " 信源</button>"
      : "";
    // 原文链接指向哪一个信源：多信源事件只链入档代表那一条，其余见详情
    const linkTitle = it.hot_event
      ? "原文：本条入档代表（" + (it.source_name || "") + "，权威度 " +
        (it.authority || "?") + "）的链接；同事件另有 " + Math.max(0, it.hot_sources - 1) +
        " 个信源，见详情「相关报道」"
      : "原文：" + (it.source_name || "") + " 的链接";
    return '<article class="card" data-id="' + esc(it.id) + '" data-node="' +
      esc(it.node || "") + '" data-region="' + esc(it.region || "") +
      '" data-country="' + esc(it.country || "") +
      '" data-tags="' + esc((it.tags_b || []).join(",")) + '" data-importance="' +
      esc(it.importance || "") + '" data-title="' + esc(it.title || "") +
      '" data-summary="' + esc(it.summary || "") + '"' + alt +
      (k === undefined ? "" : ' data-pidx="' + k + '"' +
        (k >= INIT_SHOWN ? " hidden" : "")) +
      ' style="--i:' + k + '"' +
      ' tabindex="0" role="button" aria-label="查看详情：' + esc(it.title) + '">' +
      '<div class="card-top">' +
      '<span class="card-num">' + it.num + "</span>" + hot +
      (it.region === "china"
        ? '<span class="card-region" data-ui="china">' + flagSvg("CN", 11) +
          "涉及中国</span>" : "") +
      hotBadge + nodeChip +
      "</div>" +
      '<h3 class="card-title">' + esc(it.title) + "</h3>" +
      '<p class="card-summary">' + esc(it.summary || "") + "</p>" +
      '<div class="card-chips">' + tags + "</div>" +
      '<div class="card-meta">' +
      '<div class="card-meta-row">' +
      '<span class="chip chip-src" title="' + esc(srcTitle) + " · 权威度 " +
      esc(it.authority || "?") + '/10">' + flagSvg(it.country, 16) +
      esc(it.source_name || "") + '<i class="tier">' + esc(it.source_tier || "") +
      "</i></span>" +
      "</div>" +
      '<div class="card-links">' +
      '<time class="card-time">' + esc(it.published_bj || "") + "<i>" +
      esc(it.time_basis || "") + "</i></time>" +
      '<span class="cl-links">' +
      '<a class="card-link" href="' + esc(it.url || "") + '" target="_blank" ' +
      'rel="noopener noreferrer" title="' + esc(linkTitle) + '" ' +
      'onclick="event.stopPropagation()">' +
      '原文<svg viewBox="0 0 24 24" width="12" height="12" fill="none" ' +
      'stroke="currentColor" stroke-width="2"><path d="M7 17L17 7M9 7h8v8"/>' +
      "</svg></a>" + mirror +
      "</span>" +
      "</div>" +
      "</div>" +
      "</article>";
  }

  /* 渐进加载（v1.14）：一次渲染全部卡片，超出「已展开」的用 hidden 收起，
     由外壳按批次增量放开——**不再提供「查看全部」**：100+ 条一次铺开，收起时
     文档高度骤减，视口必然乱跳。批次大小随断点（桌面 24 / 移动 10）。 */
  var INIT_SHOWN = 8;
  function moreBar(key, total) {
    return '<div class="more-bar" data-node="' + esc(key) + '" data-shown="' +
      INIT_SHOWN + '" data-total="' + total + '">' +
      '<span class="mb-count" data-ui="shown">已展开 <b>' + INIT_SHOWN + "</b> / 共 " +
      total + " 条</span>" +
      '<button type="button" class="more-btn" data-act="more" data-ui="showmore">' +
      "展开更多</button>" +
      '<button type="button" class="more-btn mb-less" data-act="less" ' +
      'data-ui="collapse" hidden>收起</button>' +
      "</div>";
  }

  /* 五节点正文分区（容器带节点色，与主轴呼应） */
  function sections(v) {
    const out = NODE_ORDER.map(function (key, i) {
      const m = NODE_META[key];
      const items = (v.items || []).filter(function (it) { return it.node === key; });
      let grid;
      if (items.length) {
        // 第 k 张卡片带 pidx（分区内序号）：外壳据此决定「已展开到第几条」
        grid = '<div class="grid" data-node="' + esc(key) + '">' +
          items.map(function (it, k) { return card(it, k); }).join("\n      ") +
          "</div>" +
          (items.length > INIT_SHOWN ? moreBar(key, items.length) : "");
      } else {
        grid = '<p class="node-empty" data-ui="nodeempty">今日该环节无重要动态——' +
          "这条链上今天没有动静，亦是信息。</p>";
      }
      return '<section class="node" data-node="' + esc(key) + '" style="--nc:' +
        m.dark + '" aria-label="' + esc(m.name) + " " + esc(m.en) + '">' +
        '<div class="node-head-bar" aria-hidden="true"></div>' +
        '<header class="node-head">' +
        '<div class="node-title-row">' +
        '<span class="node-index">' + String(i + 1).padStart(2, "0") + "</span>" +
        '<span class="node-names"><h2>' + esc(m.name) + "</h2><i>" + esc(m.en) +
        "</i></span>" +
        '<p class="node-desc">' + esc(m.desc) + "</p>" +
        '<span class="node-count" data-total="' + items.length + '">' +
        "<b>" + items.length + "</b><i>条</i></span>" +
        "</div>" +
        "</header>" +
        grid +
        "</section>";
    });
    return out.join("\n    ");
  }

  /* 脚注单行（三列版式）：① 中文标签（4 汉字）② 英文标签（≤12 字符）③ 内容。
     三列宽度由 CSS 变量固定，四行严格对齐、一律左对齐；本函数只出标记。 */
  function footRow(zh, en, val) {
    return '<div class="foot-row">' +
      '<span class="foot-label">' + esc(zh) + "</span>" +
      '<span class="foot-en">' + esc(en) + "</span>" +
      '<span class="foot-val">' + esc(val) + "</span></div>";
  }

  /* 信源脚注：当日信源 / 数据口径 / 规范版本 / 数据来源 */
  function footer(v) {
    const bySrc = new Map();
    (v.items || []).forEach(function (it) {
      bySrc.set(it.source_name, (bySrc.get(it.source_name) || 0) + 1);
    });
    const srcLine = Array.from(bySrc.entries())
      .sort(function (a, b) { return b[1] - a[1]; })
      .map(function (kv) { return kv[0] + " ×" + kv[1]; }).join(" · ");
    const st = v.stats || {};
    return '<footer class="footer">' +
      footRow("当日信源", "SOURCE MIX", srcLine) +
      footRow("数据口径", "DATA SCOPE",
        "统计窗口 " + v.window_hours + " 小时 · 入档 " + (v.items || []).length +
        " 条（另有 " + (st.review || 0) + " 条待人工裁决、" +
        (st.unclassified || 0) + " 条待归类，不计入展示）· 生成时间 " +
        (v.generated_at || "") + "（北京时间）") +
      footRow("规范版本", "SPEC", SPEC_VERSION + " · 展现遵循 P-03 两层架构") +
      footRow("数据来源", "ORIGIN",
        "AI HOT（aihot.news）及注册信源体系，原始快照存档于 数据/快照/" +
        (v.date || "") + "/") +
      "</footer>";
  }

  /* 日区块内容（不含外层 .day 容器）：段落顺序与空白固定 */
  function dayInner(v, ctx){
    const NL = String.fromCharCode(10);
    const S = SECTIONS;
    return '    ' + S.hero(v, ctx) + NL + '    ' + S.axis_hero(v) + NL + '    ' +
      S.axis_mini(v) + NL + '    ' + S.hotbar(v) + NL + '    ' + S.filters(v) + NL +
      '    <p class="no-result">没有匹配的资讯——试试更换关键词或清除筛选。</p>' + NL +
      '    <main>' + NL + '    ' + S.sections(v) + NL + '    </main>' + NL + '    ' +
      S.footer(v) + NL + '  ';
  }

  /* 完整日区块（外壳容器 + 内容）：校验脚本据此对产物做结构断言 */
  function dayBlock(v, ctx){
    return '<div class="day" data-date="' + esc(v.date) + '" data-window="' +
      v.window_hours + '">' + String.fromCharCode(10) + dayInner(v, ctx) + '</div>';
  }

  /* 段落注册表：每段接收**整份投影**（+ 可选上下文），比对脚本按名字逐段校验 */
  const SECTIONS = {
    hero: function (v, ctx) { return hero(v, (ctx || {}).winCounts); },
    axis_hero: function (v) { return axisHero(v); },
    axis_mini: function (v) { return axisMini(v); },
    hotbar: function (v) { return hotbar(v.hot_events); },
    filters: function (v) { return filters(v); },
    sections: function (v) { return sections(v); },
    footer: function (v) { return footer(v); }
  };

  return { esc: esc, urlDomain: urlDomain, countryName: countryName,
           shortGen: shortGen, sourceGroups: sourceGroups, hero: hero,
           axisHero: axisHero, axisMini: axisMini, hotbar: hotbar,
           filters: filters, card: card, sections: sections, footer: footer,
           dayInner: dayInner, dayBlock: dayBlock, SECTIONS: SECTIONS };
})();
