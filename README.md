[English](README.md) | [简体中文](README_zh.md)

---

# Deep Research Platform

A local-demo-ready company research platform built with `FastAPI`, `LangGraph`, `PostgreSQL/pgvector`, `Redis`, and `React`.

## What changed

This repo is no longer a single synchronous demo endpoint. It now includes:

- asynchronous research jobs
- a worker process
- PostgreSQL persistence for jobs, reports, documents, chunks, citations, and evaluations
- Redis-backed job queue and live event streaming
- parallel research execution across `price`, `filing`, `website`, and `news`
- citation-grounded final reports with evaluation scores
- a Vite + React frontend for live progress, history, user report view, and developer JSON view

## Architecture

1. `POST /research-jobs` creates a job and pushes it to Redis.
2. `app.worker` consumes queued jobs and runs the research graph.
3. The graph performs:
   - planner
   - parallel module fan-out
   - evidence normalization
   - coverage check
   - final synthesis
   - citation binding + evaluation
4. Results are stored in PostgreSQL.
5. The frontend consumes REST APIs plus `SSE` from `/research-jobs/{id}/events`.

## APIs

- `POST /research-jobs`
- `GET /research-jobs/{job_id}`
- `GET /research-jobs/{job_id}/events`
- `GET /research-jobs?limit=20`
- `GET /reports/{report_id}`
- `POST /analyze`
  - compatibility endpoint
  - creates a job and blocks for a bounded time before returning either the final report or the current job status

## Local run

### 1. Configure environment

```bash
cp .env.example .env
```

Fill at least:

- `OPENAI_API_KEY` for LLM-based planning/synthesis/embeddings
- `NEWSAPI_KEY` for live news retrieval
- `SEC_USER_AGENT` with a valid contact email

### 2. Start the full stack

```bash
docker compose up --build
```

Services:

- API: `http://localhost:8000`
- Frontend: `http://localhost:3000`
- Swagger: `http://localhost:8000/docs`

### 3. Run without Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
```

Start dependencies locally, then run:

```bash
uvicorn app.main:app --reload
python -m app.worker
npm --prefix frontend run dev
```

## Storage model

PostgreSQL tables:

- `research_jobs`
- `module_runs`
- `reports`
- `documents`
- `chunks`
- `citations`
- `evaluation_runs`

## Quality and fallback behavior

- Missing `OPENAI_API_KEY`: planner/synthesis fall back to heuristic mode
- Missing `NEWSAPI_KEY`: news module degrades to `partial`
- Module failures do not abort the whole job
- Final reports attach citations where evidence can be matched
- Evaluation scores track groundedness, freshness, and coverage

## Tests and checks

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
