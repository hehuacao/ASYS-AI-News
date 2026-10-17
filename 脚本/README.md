# 流水线脚本

全部为 **Python 标准库**实现，无第三方依赖。执行时不需要 `pip install`。

## 数据流

```
信源注册表/sources.json
        │  fetch_sources.py            backfill_sources.py（历史补抓）
        ▼
    数据/快照/<抓取日>/<信源id>.json    数据/回溯/<发布日>/<信源id>.json
        │  rebuild_days.py（→ classify.py → adjudicate.py）
        ▼
    数据/日报/<自然日>.json            事实源：分类打标 + 事件合并 + 噪声闸门
        │  translate_items.py（可选）
        ▼
    数据/翻译/译表.json                对照译文
        │  view_projection.py
        ▼
    数据/视图/index.json + <日期>_<窗口>.json      视图投影 VIEW-01
        │  render_dashboard.py
        ▼
    仪表盘/ai_news_daily.html            离线单文件
    仪表盘/runtime_shell.html             运行态薄壳
        │  release.py
        ▼
    发布/ai_news_daily-<日期>/           静态发布包
```

## 每日完整链路

```bash
python 脚本/fetch_sources.py                    # 1 抓取巡检
python 脚本/rebuild_days.py                     # 2 重建受影响自然日（分类 + 事件合并）
python 脚本/queue_dump.py <日期>                # 3a 查看待裁决条目（可选，需人工时）
python 脚本/adjudicate.py --date <日期> --decisions <裁决.json>   # 3b 落盘裁决
python 脚本/translate_items.py                  # 4 生成对照译文（可选）
python 脚本/view_projection.py                  # 5 生成视图投影
python 脚本/render_dashboard.py                 # 6a 离线单文件
python 脚本/render_dashboard.py --mode runtime  # 6b 运行态薄壳
python 脚本/validate_data.py                   # 7 校验（详见下文「校验」）
python 脚本/validate_view.py
python 脚本/validate_dashboard.py
python 脚本/gen_runtime_assets.py --check
node   脚本/smoke_dashboard.js  仪表盘/ai_news_daily.html
node   脚本/smoke_dateswitch.js 仪表盘/ai_news_daily.html
node   脚本/smoke_runtime.js    仪表盘/runtime_shell.html
python 脚本/release.py --zip --ascii-only        # 8 打包
```

**顺序要求**：译文必须在投影之前（译文经投影下发给页面）；校验必须在渲染之后（校验对象是产物）。

**`gen_runtime_assets.py`** 在表达层定义变更时才需要重跑（新增国家旗标、修改节点名称或界面文案、修改 `classify.py` 里的规范版本号）。日常链路只跑 `--check`。打包件内联了版本号，规范升版后必须重跑本脚本并重新渲染，否则 `release.py` 的资产一致性校验会中止。

**`--ascii-only`** 输出 ASCII 路径的数据目录 `data/views/`（内容与中文目录一致）。托管环境对 URL 编码与重写的处理不一，中文路径可能取不到数据；发布到托管平台时建议带上此参数。

---

## 采集

### `fetch_sources.py` — 信源抓取巡检

```bash
python 脚本/fetch_sources.py                # 巡检全部启用的信源
python 脚本/fetch_sources.py --only aihot   # 只巡检指定信源
python 脚本/fetch_sources.py --status       # 只看注册表状态
```

- 原始快照全量存档：`数据/快照/<抓取日>/<信源id>.json`（原文 + 抓取时间 + 校验值）
- 注册表运行时字段（最近成功时间、连续失败次数等）由脚本自动回写
- 失败分两类：**信源失效**（404/403/空 feed 等，计入失败）与 **环境不可达**（代理、DNS、TLS，
  只记录不计失败）
- 连续失败达到阈值且跨越多个日期才自动禁用，避免单日偶发失败误伤
- 产出巡检报告：`数据/快照/<抓取日>/巡检报告.md`

### `backfill_sources.py` — 历史日期补抓

```bash
python 脚本/backfill_sources.py --date 2026-10-11
python 脚本/backfill_sources.py --from 2026-10-11 --to 2026-10-12 --only arxiv-query
```

只为没有当期巡检快照的历史自然日补抓，落到 `数据/回溯/<发布日>/`，结构与巡检快照一致。只使用信源官方接口自带的日期过滤参数；不支持回溯的信源（如 RSS）由相邻日期快照跨日合并覆盖。

---

## 加工

### `rebuild_days.py` — 按数据范围重建

```bash
python 脚本/rebuild_days.py            # 重建全部受影响自然日
python 脚本/rebuild_days.py --dry-run  # 只列范围与条数，不落盘
python 脚本/rebuild_days.py --from 2026-10-13
```

一次抓取会带回前一日发布的内容，因此重建范围按「每个快照日影响它当日与前一日」自动推算，天数由数据决定。重建会复用各日的裁决记录，对已不存在的条目告警跳过而不中断。

### `classify.py` — 分类器

```bash
python 脚本/classify.py --date 2026-10-13
python 脚本/classify.py --window-h 24
```

处理链：解析快照（RSS/Atom 与多个 JSON API）→ 归一化（发布时间统一为北京时间、标题不改写、摘要精简）→ 主线分类 → 属性打标 → 去重与事件合并 → 重要度分级 → 置信度分流。

- **主线分类**：标题关键词打分，标题无命中时才用摘要兜底；叠加信源先验，标题强信号可改判先验
- **去重**：同一 URL 或高度相似的标题判为同一事件，同一事件只保留一条入档代表，其余标记为事件成员
- **噪声闸门**：结构性噪音（如金融备案文件顺带提及 AI）显式排除并记录原因，保留在数据集中可追溯
- **分流**：高置信度直接入档，中低置信度进入待裁决队列
- **产物**：`数据/日报/<日期>.json` 与同目录的分类质检报告

### `queue_dump.py` / `adjudicate.py` — 内容裁决

```bash
python 脚本/queue_dump.py 2026-10-13         # 打印待裁决条目
python 脚本/queue_dump.py 2026-10-13 150      # 摘要截断字数
python 脚本/adjudicate.py --date 2026-10-13 --decisions 裁决.json
```

裁决结论写在 `数据/日报/<日期>_自然日裁决.json`，由 `adjudicate.py` 落盘并重算重要度与统计。裁决文件格式为 `{"条目id": ["file", "节点", "子方向", "理由"]}`，动作取 `file`（入档）、`exclude`（排除）、`event`（标记为事件成员）。

**待裁决队列非空是正常状态**：更宽的合并范围会持续带入新条目。硬性要求只有一条——队列中的条目 id 必须都存在于数据集中。

### `translate_items.py` — 对照译文（可选层）

```bash
python 脚本/translate_items.py --dry-run
python 脚本/translate_items.py --workers 2 --batch 6
python 脚本/translate_items.py --date 2026-10-13
```

- 预生成后随投影下发，页面仍是零网络请求，也没有在线翻译的隐私与限流风险
- 增量键为「条目 id + 原文指纹」，原文未变不重译，人工定稿的条目不覆盖
- 长摘要按句边界分段翻译后拼接；覆盖不全的条目标记为部分翻译
- 接口与密钥从环境变量 `AGNES_API_KEY`（或本机 `config.json`）读取，**不入库**
- 免费额度下高并发会触发限流，用 `--workers 2 --batch 6`；失败的条目不覆盖旧值，重跑只补这些
- 译文**永不替换原文**，页面出现处一律标注「机器译文 · 未校对」

---

## 投影与展现

### `view_projection.py` — 视图投影

```bash
python 脚本/view_projection.py          # 生成 数据/视图/
python 脚本/view_projection.py --clean  # 先清空再重建
```

- **为什么有这一层**：事实源含裁决队列、噪声原因、溯源字段等加工层内部结构，
  页面直读等于把业务逻辑泄到展现层；窗口合并与排序若两处各自实现也会漂移
- **口径唯一实现**：24h/48h 合并、自然日完整性判定、展现排序与编号都在本层，页面只消费不重算
- **契约**：`VIEW-01`，字段走白名单，投影不含样式与布局信息
- **产物**：`index.json`（各日条数与校验值、最近完整日）+ `<日期>_<窗口>.json`
- **落盘**：临时文件 + 原子替换，生成失败不会留下半个文件；陈旧投影自动清理

### `render_dashboard.py` — 页面装配

```bash
python 脚本/render_dashboard.py                  # 离线单文件 → 仪表盘/ai_news_daily.html
python 脚本/render_dashboard.py --mode runtime  # 运行态薄壳 → 仪表盘/runtime_shell.html
```

- 本脚本只装配外壳、样式与数据载荷，内容由渲染函数产出
- **离线单文件**内联全部投影：自包含、零请求、可嵌入 iframe，双击即用
- **运行态薄壳**只内联首屏兜底，其余按需读取 `数据/视图/`；**必须经 HTTP 访问**
  （浏览器禁止 `file://` 页面读取同目录数据文件）。取不到数据时页面按设计降级并在页首说明
  原因与替代方案，不会静默失败
- 多日期 × 双窗口按需生成，切换时即时渲染
- 页面功能包括：主线分区正文、卡片与详情抽屉、交叉热点联动、搜索与筛选、
  原文/对照译文三态切换、渐进加载、字号与密度设置、日期窗口切换、主题三态

### `render_fragments.js` — 渲染实现

页面的渲染逻辑**只有这一份**（纯函数，输入投影输出 HTML 片段，不操作 DOM、不做业务推算）。离线版与运行态版共用它；打包件 `assets/render_runtime.js` 由 `gen_runtime_assets.py`从 Python 侧的表达层定义合成，页面内联的与校验脚本用的都是它。

**改视觉改这个 js，改样式与外壳改 `render_dashboard.py`。**

---

## 校验

```bash
python 脚本/validate_data.py                # 数据审计：数量/去重/可溯/统计自洽
python 脚本/validate_view.py                # 投影校验：契约/与事实源比对/校验值
python 脚本/validate_dashboard.py           # 页面终检：结构/外链/编号/对比度/发布包
python 脚本/gen_runtime_assets.py --check    # 前端资产与定义是否一致
node 脚本/smoke_dashboard.js  仪表盘/ai_news_daily.html
node 脚本/smoke_dateswitch.js 仪表盘/ai_news_daily.html
node 脚本/smoke_runtime.js    仪表盘/runtime_shell.html
```

前四套需要已有数据才有意义；无数据时给出明确的缺失提示，不会静默通过。

**jsdom 只验证结构，不执行布局与动画。** 对齐、溢出、触达高度、半透明叠字这类问题必须在真实浏览器中复核，不能以冒烟测试全绿作为视觉结论。

写校验断言时不要写死条数与版本号，应与页面自身数据或投影读数比对，否则数据形态变化就会误报。

---

## 打包与其他

### `release.py` — 打包发布

```bash
python 脚本/release.py --zip --ascii-only       # 完整包
python 脚本/release.py --mode data              # 只打包数据目录
python 脚本/release.py --mode shell             # 只打包界面
python 脚本/release.py --out <目录>             # 指定输出目录
```

- 包内：`index.html`、`data/views/*.json`、`release.json`（文件校验清单）、
  《部署说明.md》、《本地预览.py》（零依赖静态服务，用于上线前自检）
- **zip 顶层必须直接是 `index.html`**，不能整套套在子目录里，否则站点根文档不存在
- 打包前强制校验数据与投影，任一不过即中止
- 写完清单后逐文件复算校验值，避免发出清单与实际不符的包

### `export_spec_summary.py` — 规范摘要派生

`规范标准/体系规范摘要.md` 由完整规范按章节白名单自动派生，请勿手工编辑。该脚本需要完整规范作为输入，此处未收录，因此在本仓库中只对已入库的摘要做结构自检。

### `gen_runtime_assets.py` — 前端资产导出

从 Python 单一来源导出国旗画法、国家名、节点元数据、界面文案等表达层定义，并与渲染函数合成打包件。日常只跑 `--check`；改动表达层定义时重跑（不带 `--check`）。
