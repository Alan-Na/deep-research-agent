[English](README.md) | [简体中文](README_zh.md)

---

# Deep Research Platform

这是一个可本地完整演示的企业研究平台，技术栈为 `FastAPI + LangGraph + PostgreSQL/pgvector + Redis + React`。

## 升级后的能力

项目已不再是单个同步接口 Demo，而是包含：

- 异步研究任务
- 独立 Worker
- PostgreSQL 持久化 jobs / reports / documents / chunks / citations / evaluations
- Redis 队列和实时事件流
- `price / filing / website / news` 并行执行
- 带 citation 的最终报告
- 质量评估分数与 warning
- Vite + React 前端，支持实时进度、历史任务、用户视图和开发者 JSON 视图

## 系统流程

1. `POST /research-jobs` 创建任务并推入 Redis。
2. `app.worker` 消费任务并执行研究 graph。
3. Graph 顺序为：
   - planner
   - 并行模块执行
   - 证据归一化
   - 覆盖度检查
   - 最终综合
   - citation 绑定与评估
4. 结果写入 PostgreSQL。
5. 前端通过 REST API 和 `/research-jobs/{id}/events` 的 `SSE` 展示进度与结果。

## 主要接口

- `POST /research-jobs`
- `GET /research-jobs/{job_id}`
- `GET /research-jobs/{job_id}/events`
- `GET /research-jobs?limit=20`
- `GET /reports/{report_id}`
- `POST /analyze`
  - 兼容旧接口
  - 内部会创建 job，并在限定时间内等待结果，超时则返回当前 job 状态

## 本地运行

### 1. 准备环境变量

```bash
cp .env.example .env
```

建议至少填写：

- `OPENAI_API_KEY`
- `NEWSAPI_KEY`
- `SEC_USER_AGENT`，并带上有效邮箱

### 2. Docker 一键启动

```bash
docker compose up --build
```

启动后：

- API：`http://localhost:8000`
- 前端：`http://localhost:3000`
- Swagger：`http://localhost:8000/docs`

### 3. 非 Docker 方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
```

准备好本地 Postgres 和 Redis 后再执行：

```bash
uvicorn app.main:app --reload
python -m app.worker
npm --prefix frontend run dev
```

## 数据表

- `research_jobs`
- `module_runs`
- `reports`
- `documents`
- `chunks`
- `citations`
- `evaluation_runs`

## 降级与容错

- 没有 `OPENAI_API_KEY` 时，planner / synthesis / embedding 会走启发式降级
- 没有 `NEWSAPI_KEY` 时，news 模块返回 `partial`
- 单模块失败不会中断整单
- 最终报告会尽量给每条结论绑定 citation
- 评估结果会输出 groundedness / freshness / coverage

## 检查命令

```bash
source .venv/bin/activate
pytest -q
python - <<'PY'
import app.main
import app.worker
print("imports ok")
PY
npm --prefix frontend run build
```
