# 信源注册表

`sources.json` 是本项目全部信源的唯一事实源，字段与新增流程见下。

## 字段速查

| 字段 | 说明 |
|---|---|
| `id` | 信源标识，脚本按此分目录存快照 |
| `name` | 信源名称 |
| `tier` | 权威度分层：T0 官方一手 / T1 学术基准 / T2 专业媒体 / T3 聚合策展 / T4 社区观点 |
| `channel` | 接入通道：A 免费结构化 API / B RSS / C 受限付费（只登记）/ D 人工巡检 |
| `type` | 解析类型：rss / atom / json_api / api / html / dataset / manual |
| `domains` | 适用主线节点：capability 能力 / product 产品 / industry 产业 / governance 治理 / frontier 趋势 / general 综合 |
| `authority` | 权威度 1–10，作为重要度分级的输入 |
| `region` | global / china / both |
| `country` | 来源国家或地区（ISO 3166-1 alpha-2，用于国旗区分；EU 表示欧盟） |
| `language` | 主要语言 |
| `url` | 抓取地址，支持 `{today}` / `{yesterday}` 占位符按北京时间日期展开 |
| `enabled` | 是否纳入每日巡检 |
| `status` | trial 试用期 / active 转正 / retired 已注销 |
| `registered_at` / `trial_until` | 登记日期与试用期截止日期 |
| `notes` | 一句话信源定位与当前状态 |

`last_ok`、`fail_streak` 等运行时字段由 `fetch_sources.py` 自动回写，请勿手工修改。

## 新增一个信源

1. 在 `sources.json` 的 `sources` 数组追加条目
2. 单点测试，确认可正常返回且字段完整：
   ```bash
   python 脚本/fetch_sources.py --only <id>
   ```
3. 置 `enabled: true`、`status: "trial"`、`registered_at` 为当天、`trial_until` 为两周后
4. 试用期结束后按实际质量转正（`active`）或注销（`retired`）

## 巡检

```bash
python 脚本/fetch_sources.py            # 巡检全部启用信源
python 脚本/fetch_sources.py --status   # 只看状态
```

快照落在 `数据/快照/<抓取日>/<信源id>.json`，与信源注册表分离：注册表是配置，快照是数据，两者不混放。
