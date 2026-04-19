from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import init_db
from app.schemas import (
    InvestmentJobCreateResponse,
    InvestmentJobRequest,
    InvestmentJobStatusResponse,
    InvestmentMemoResponse,
    MarketOhlcvResponse,
)
from app.services.job_service import (
    check_dependencies_health,
    create_investment_job,
    get_job_market_ohlcv_response,
    get_investment_job_status,
    get_investment_memo_response,
    get_job_memo,
    get_legacy_report_response,
    list_investment_jobs,
    search_job_evidence,
    wait_for_job_completion,
)
from app.services.redis_queue import subscribe_job_events
from app.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
app = FastAPI(title="Investment Research Multi-Agent Platform", version="2.0.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")


@app.on_event("startup")
def startup_event() -> None:
    init_db(reset=settings.reset_database_on_startup)


@app.get("/", include_in_schema=False, response_model=None)
def user_dashboard() -> FileResponse | JSONResponse:
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "Frontend build not found.", "frontend_expected_path": str(index_path)})


@app.get("/developer", include_in_schema=False, response_model=None)
def developer_dashboard() -> FileResponse | JSONResponse:
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "Frontend build not found."})


@app.get("/health")
def health_check() -> dict[str, Any]:
    return check_dependencies_health()


@app.post("/investment-jobs", response_model=InvestmentJobCreateResponse)
def create_job(request: InvestmentJobRequest) -> InvestmentJobCreateResponse:
    return create_investment_job(request.company_name)


@app.get("/investment-jobs/{job_id}", response_model=InvestmentJobStatusResponse)
def get_job(job_id: str) -> InvestmentJobStatusResponse:
    status = get_investment_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Investment job not found.")
    return status


@app.get("/investment-jobs")
def get_jobs(limit: int = 20) -> list[dict[str, Any]]:
    return [item.model_dump() for item in list_investment_jobs(limit)]


@app.get("/investment-jobs/{job_id}/events")
def stream_job_events(job_id: str) -> StreamingResponse:
    if get_investment_job_status(job_id) is None:
        raise HTTPException(status_code=404, detail="Investment job not found.")

    def event_stream():
        initial = get_investment_job_status(job_id)
        if initial:
            yield f"data: {json.dumps({'type': 'snapshot', 'status': initial.model_dump()}, ensure_ascii=False)}\n\n"
        last_ping = time.time()
        for payload in subscribe_job_events(job_id):
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if payload.get("type") in {"job_status", "job_failed"} and payload.get("status") in {"partial", "succeeded", "failed"}:
                break
            if time.time() - last_ping >= 15:
                yield "event: ping\ndata: {}\n\n"
                last_ping = time.time()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/investment-memos/{memo_id}", response_model=InvestmentMemoResponse)
def get_memo(memo_id: str) -> InvestmentMemoResponse:
    memo = get_investment_memo_response(memo_id)
    if memo is None:
        raise HTTPException(status_code=404, detail="Investment memo not found.")
    return memo


@app.get("/investment-jobs/{job_id}/evidence")
def get_job_evidence(job_id: str, agent: str | None = Query(default=None), category: str | None = Query(default=None)) -> dict[str, Any]:
    evidence = search_job_evidence(job_id, agent_name=agent, category=category)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Investment job not found.")
    return evidence.model_dump()


@app.get("/investment-jobs/{job_id}/ohlcv", response_model=MarketOhlcvResponse)
def get_job_ohlcv(job_id: str) -> MarketOhlcvResponse:
    response = get_job_market_ohlcv_response(job_id)
    if response is None:
        raise HTTPException(status_code=404, detail="OHLCV data not found for the investment job.")
    return response


@app.post("/analyze")
def analyze_company(request: InvestmentJobRequest) -> dict[str, Any]:
    response = create_investment_job(request.company_name)
    status = wait_for_job_completion(response.job_id, settings.blocking_analyze_timeout_seconds)
    if status is None:
        raise HTTPException(status_code=404, detail="Investment job was not found after creation.")
    if status.status in {"partial", "succeeded"} and status.memo_id:
        memo = get_job_memo(response.job_id)
        if memo:
            return memo.model_dump()
    return {
        "job": response.model_dump(),
        "status": status.model_dump(),
    }


# Deprecated v1 compatibility aliases.
@app.post("/research-jobs", deprecated=True)
def create_job_legacy(request: InvestmentJobRequest) -> dict[str, Any]:
    response = create_investment_job(request.company_name)
    return response.model_dump()


@app.get("/research-jobs/{job_id}", deprecated=True)
def get_job_legacy(job_id: str) -> dict[str, Any]:
    status = get_investment_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Research job not found.")
    payload = status.model_dump()
    payload["planner_output"] = payload.pop("research_brief", None)
    payload["module_runs"] = [
        {
            "module": item["agent_name"],
            "status": item["status"],
            "summary": item["summary"],
            "warning": item["warning"],
            "error": item["error"],
            "started_at": item["started_at"],
            "finished_at": item["finished_at"],
            "duration_ms": item["duration_ms"],
        }
        for item in payload.pop("agent_runs", [])
    ]
    payload["report_id"] = payload.pop("memo_id", None)
    return payload


@app.get("/research-jobs", deprecated=True)
def get_jobs_legacy(limit: int = 20) -> list[dict[str, Any]]:
    items = []
    for item in list_investment_jobs(limit):
        payload = item.model_dump()
        payload["report_id"] = payload.pop("memo_id", None)
        items.append(payload)
    return items


@app.get("/research-jobs/{job_id}/events", deprecated=True)
def stream_job_events_legacy(job_id: str) -> StreamingResponse:
    return stream_job_events(job_id)


@app.get("/research-jobs/{job_id}/ohlcv", deprecated=True)
def get_job_ohlcv_legacy(job_id: str) -> dict[str, Any]:
    return get_job_ohlcv(job_id).model_dump()


@app.get("/reports/{report_id}", deprecated=True)
def get_report_legacy(report_id: str) -> dict[str, Any]:
    report = get_legacy_report_response(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report
