# ASYS · AI 资讯日报

从公开信源自动采集每日 AI 资讯，按 **AI 产业化价值链五节点**（能力 → 产品 → 产业 → 治理 → 趋势）归类打标、去重分级，产出**可离线双击打开的单文件 HTML 日报**与**纯静态发布包**。

- **零第三方依赖**：全链路仅用 Python 标准库，页面不引 CDN、外部字体与统计脚本
- **零服务端**：产物是静态文件，没有接口、数据库与环境变量，部署即上传文件
- **单一实现**：渲染逻辑只有一份（`脚本/render_fragments.js`），离线版与运行态版共用
- **可核查**：每条资讯可回溯原始快照，统计口径由自动化校验守护

---

## 目录结构

仓库只收录源码与文档。运行时数据与产物不入库，由脚本在本机生成。

```
ASYS-AI-News/
├── 脚本/                     流水线脚本（详见 脚本/README.md）
│   ├── fetch_sources.py      信源抓取巡检
│   ├── backfill_sources.py   历史日期回溯补抓
│   ├── rebuild_days.py       按数据范围重建受影响自然日
│   ├── classify.py           分类打标 · 事件合并 · 噪声闸门
│   ├── queue_dump.py         导出待人工裁决队列
│   ├── adjudicate.py         内容裁决
│   ├── translate_items.py    生成对照译文（可选）
│   ├── view_projection.py    视图投影（数据契约 VIEW-01）
│   ├── render_dashboard.py   装配日报页面
│   ├── render_fragments.js   渲染实现（唯一一份）
│   ├── gen_runtime_assets.py 导出前端资产
│   ├── export_spec_summary.py 由完整规范派生公开摘要
│   ├── release.py            打包发布
│   ├── validate_*.py          数据 / 投影 / 页面 / 吸顶几何校验
│   ├── smoke_*.js             页面冒烟测试（需 jsdom）
│   ├── probe_*.js             一次性取证脚本（真实浏览器量测）
│   └── assets/               导出的前端资产
├── 信源注册表/
│   ├── sources.json          信源清单（唯一事实源）
│   └── README.md             字段说明与新增信源流程
├── 规范标准/
│   └── 体系规范摘要.md       分类口径与数据契约
├── LICENSE                   MIT
└── README.md
```

### 本机运行后生成（不入库）

| 路径 | 内容 |
|---|---|
| `数据/快照/`、`数据/回溯/` | 每日原始快照（原文 + 抓取时间 + 校验值） |
| `数据/日报/` | 分类打标后的事实源，每自然日一份 JSON |
| `数据/翻译/` | 对照译文表（可选层） |
| `数据/视图/` | 页面消费的视图投影，24h / 48h 双窗口 |
| `仪表盘/` | `ai_news_daily.html`（离线单文件）、`runtime_shell.html`（按需取数） |
| `发布/` | 打包好的静态发布包 |

---

## 环境要求

| 用途 | 要求 |
|---|---|
| 跑流水线 | Python 3.11+，**仅标准库**，无需 `pip install` |
| 跑页面冒烟 | Node.js 22+ 与 `jsdom`（`npm i jsdom`，仅测试用） |
| 生成对照译文 | 一个 OpenAI 兼容的文本接口与密钥（见下） |

## 快速开始

```bash
# 1) 抓取信源快照 → 数据/快照/<日期>/
python 脚本/fetch_sources.py

# 2) 按数据范围重建受影响自然日（分类 → 噪声闸门 → 事件合并）
python 脚本/rebuild_days.py

# 3) 事实源 → 视图投影 → 数据/视图/
python 脚本/view_projection.py

# 4) 装配页面 → 仪表盘/
python 脚本/render_dashboard.py                  # 离线单文件，双击即用
python 脚本/render_dashboard.py --mode runtime  # 运行态薄壳，按需取数

# 5) 打包 → 发布/ai_news_daily-<日期>/
python 脚本/release.py --zip --ascii-only
```

`仪表盘/ai_news_daily.html` 数据全部内联，零网络请求，**双击即可打开**。

`仪表盘/runtime_shell.html` 只内联首屏兜底数据，其余按需读取 `数据/视图/`。浏览器禁止 `file://` 页面读取同目录数据文件，因此它**必须经 HTTP 访问**（取不到数据时页面会明确提示原因，不会静默失败）。本地预览：

```bash
cd 发布/ai_news_daily-<日期> && python 本地预览.py 8765   # → http://127.0.0.1:8765/
```

完整链路（含译文、裁决、校验、打包）见 [`脚本/README.md`](脚本/README.md)。

## 对照译文（可选）

`translate_items.py` 用一个 OpenAI 兼容接口生成标题与摘要的中文对照译文，作为附加层下发，**不替换原文**，页面上标注「机器译文 · 未校对」。不需要译文可跳过这一步，页面照常工作。

```bash
export AGNES_API_KEY=<你的密钥>       # 也可写进本机 config.json
python 脚本/translate_items.py
```

密钥只从环境变量或本机配置读取，仓库内不含任何凭据。

## 部署

产物是**静态文件**，只有两类：`index.html` 与数据目录 `data/views/*.json`。把它们按相对位置放到同一目录树下即可，用 GitHub Pages、Netlify、Cloudflare Pages、对象存储、nginx 或任意静态服务器都行——部署方式由使用者自行决定。

三类更新：

| 场景 | 命令 | 需要上传 |
|---|---|---|
| 首次部署 | `release.py` | 整包 |
| 日常数据更新 | `release.py --mode data` | 数据目录 |
| 界面改版 | `release.py --mode shell` | `index.html` |

**先传数据、后传界面**：界面按数据契约读取，两版错配会有一天的显示异常。`--ascii-only` 会把数据目录输出为 ASCII 路径的 `data/views/`（内容一致），便于在 URL 编码规则不一的托管环境上稳定取数。

发布包内含《部署说明.md》（上线步骤、更新与回滚方式）与 `本地预览.py`（零依赖静态服务，上线前自检用）；`release.json` 是文件校验清单。

## 校验

```bash
python 脚本/validate_data.py       # 数据审计：时间窗 / 去重 / 可溯 / 统计自洽
python 脚本/validate_view.py       # 投影校验：契约 / 与事实源逐条比对 / 校验值
python 脚本/validate_dashboard.py  # 页面终检：结构 / 外链 / 编号 / 对比度 / 发布包结构
python 脚本/gen_runtime_assets.py --check   # 前端资产与脚本定义是否一致
node 脚本/smoke_dashboard.js  仪表盘/ai_news_daily.html
node 脚本/smoke_dateswitch.js 仪表盘/ai_news_daily.html
node 脚本/smoke_runtime.js    仪表盘/runtime_shell.html
```

后三条需先 `npm i jsdom`。校验需要已有数据才有意义，无数据时会给出明确缺失提示，不会静默通过。

**jsdom 只验证结构、不执行布局动画**，全部通过不代表视觉没有问题——界面改动请在真实浏览器里复核。

## 规范摘要

`规范标准/体系规范摘要.md` 是**分类口径与数据契约**的公开摘要：主线节点定义、标签词表、去重与噪声规则、视图字段清单。它由 `脚本/export_spec_summary.py` 从项目的完整规范派生，**请勿手工编辑**；该派生脚本需要完整规范作为输入，此处未收录，因此在本仓库中它只对已入库的摘要做结构自检。

## 许可

[MIT](LICENSE)。可自由使用、修改、商用与再分发，只需保留版权声明与许可文本。
