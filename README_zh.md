[English](README.md) | [简体中文](README_zh.md)

---

# Investment Research Multi-Agent Platform

这是一个基于LangGraph开发的多 Agent 项目，主要应用是上市公司股票的投资分析，并且首版优先支持 A 股。

![Workflow](pipeline_flowchart.svg)

## 当前定位

- 输出投资备忘录，而不是泛化公司摘要
- 每个 agent 内部采用有界 `ReAct`
- 一等 agent 固定为：
  - `market`
  - `filing`
  - `web_intel`
  - `news_risk`
  - `critic_output`
- 使用 Redis 队列做异步任务，SSE 做实时进度流
- 使用 PostgreSQL 持久化 jobs、agent runs、memos、evidence documents、evidence chunks、citations、critic runs、event records
- 提供 Vite + React 前端，用于任务创建、实时 trace、memo 展示、citation explorer 和 developer JSON 视图

## 系统架构

顶层编排由 `LangGraph` 负责。

执行流程如下：

1. `POST /investment-jobs` 创建异步任务并推入 Redis。
2. `app.worker` 消费任务并启动 graph。
3. Graph 依次执行：
   - `intake_brief`
   - `parallel_research`
   - `evidence_index`
   - `critic_output`
   - `finalize`
4. 前四个研究 agent 并行执行：
   - `Market Agent`
     - 负责价格、收益率、成交量、波动率、估值快照
     - 通过本地 `market-data-mcp` 抽象访问市场数据
   - `Filing Agent`
     - 负责公告/财报发现与结构化抽取
     - 以 `A 股` 披露路径为主，SEC 路径为辅
   - `Web Intelligence Agent`
     - 负责官网、IR 页面、公司定位、产品和业务线索
   - `News/Risk Agent`
     - 负责新闻抓取、去重、聚类、事件分类、事件周期判断、impact/confidence 打分
5. `Critic & Output Agent` 只消费共享证据和前面 agent 的输出，它负责检查：
   - 立场是否被证据支撑
   - citation 覆盖率
   - 证据新鲜度
   - 跨 agent 一致性
   - 是否存在重复新闻导致的偏置
6. 最终结果保存为 `InvestmentMemo`。

## 最终输出

系统最终输出包含：

- `stance`：`bullish / neutral / bearish`
- `stance_confidence`
- `thesis`
- `bull_case`
- `bear_case`
- `key_catalysts`
- `key_risks`
- `valuation_view`
- `market_snapshot`
- `watch_items`
- `limitations`
- `agent_outputs`
- `events`
- `citations`
- `critic_summary`

如果证据不足，critic agent 会优先把立场降级到 `neutral`，并明确输出 limitations，而不是给出过强结论。

## 本地运行

### 1. 准备环境变量

```bash
cp .env.example .env
```

在 Docker 模式下，PostgreSQL 和 Redis 由 `docker-compose.yml` 直接提供。

### 2. Docker 一键启动

```bash
docker compose up --build
```

启动后：

- API：`http://localhost:8000`
- 前端：`http://localhost:3000`
- Swagger：`http://localhost:8000/docs`

注意：

- 当前 `docker-compose.yml` 给 API 设置了 `RESET_DATABASE_ON_STARTUP=true`
- 也就是说容器启动时会重建数据库 schema
- 本地 Docker 环境更适合演示，不适合作为持久化生产环境

### 3. 非 Docker 方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
```

然后准备本地 PostgreSQL 和 Redis，再执行：

```bash
uvicorn app.main:app --reload
python -m app.worker
npm --prefix frontend run dev
```

非 Docker 模式下，你需要自己提供带 `pgvector` 的 PostgreSQL 和一个 Redis 实例。

## 降级与容错

- 缺少 `OPENAI_API_KEY`
  - 规划、综合、部分排序步骤会降级为启发式行为
- 缺少 `NEWSAPI_KEY`
  - `news_risk` 可能返回 `partial`
- 单个 agent 失败不会直接中断整个 job
- 只要仍有足够可用证据，系统会尽量返回 `partial` 而不是 `failed`
- 在证据可匹配时，系统会给结论绑定 citation
- critic 当前会输出：
  - citation coverage
  - freshness
  - consistency
  - duplicate-event bias

## 当前限制

- v1 主要针对 `A 股` 优化
- 市场数据和新闻数据依赖的上游源有时不稳定
- 即使 graph 主链成功，外部数据源异常仍可能导致任务最终落为 `partial`
- `POST /analyze` 是兼容接口，不代表完整的异步 job 语义

## 检查命令

```bash
source .venv/bin/activate
pytest -q
python3 - <<'PY'
import app.main
import app.worker
print("imports ok")
PY
npm --prefix frontend run build
```
