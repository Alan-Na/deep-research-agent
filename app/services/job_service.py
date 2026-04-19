from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select

from app.db import get_db_session
from app.db.models import (
    AgentRunRecord,
    CriticRunRecord,
    EvidenceChunkRecord,
    EvidenceDocumentRecord,
    EventRecord,
    InvestmentJobRecord,
    InvestmentMemoRecord,
    MemoCitationRecord,
)
from app.graph import create_investment_graph
from app.research.retrieval import build_documents_and_chunks
from app.schemas import (
    AgentResult,
    AgentRunStatus,
    EvidenceResponseItem,
    EvidenceSearchResponse,
    InvestmentJobCreateResponse,
    InvestmentJobListItem,
    InvestmentJobStatusResponse,
    InvestmentMemo,
    InvestmentMemoResponse,
    MarketOhlcvResponse,
)
from app.services.market_ohlcv import get_job_market_ohlcv
from app.services.redis_queue import enqueue_job, get_redis_client, publish_job_event
from app.utils.logging import get_logger

logger = get_logger(__name__)
graph = create_investment_graph()


def create_investment_job(company_name: str) -> InvestmentJobCreateResponse:
    now = datetime.now(timezone.utc)
    with get_db_session() as session:
        job = InvestmentJobRecord(
            company_name=company_name,
            market="UNKNOWN",
            status="queued",
            created_at=now,
            updated_at=now,
            warnings=[],
            errors=[],
        )
        session.add(job)
        session.flush()
        response = InvestmentJobCreateResponse(
            job_id=job.id,
            status="queued",
            created_at=job.created_at.isoformat(),
        )

    enqueue_job(response.job_id)
    publish_job_event(
        response.job_id,
        {
            "type": "job_created",
            "job_id": response.job_id,
            "status": "queued",
            "company_name": company_name,
            "created_at": response.created_at,
        },
    )
    return response


def process_investment_job(job_id: str) -> None:
    with get_db_session() as session:
        job = session.get(InvestmentJobRecord, job_id)
        if not job:
            logger.warning("Job %s was not found in database.", job_id)
            return
        if job.status == "running":
            logger.info("Job %s is already running; skipping duplicate worker claim.", job_id)
            return
        started_at = datetime.now(timezone.utc)
        job.status = "running"
        job.started_at = started_at
        job.updated_at = started_at
        company_name = job.company_name

    try:
        result = graph.invoke(
            {
                "company_name": company_name,
                "agent_results": {},
                "evidence_items": [],
                "event_items": [],
                "warnings": [],
                "errors": [],
                "progress_callback": lambda payload: _handle_progress_event(job_id, payload),
            }
        )
        memo = InvestmentMemo.model_validate(result["memo"])
        _persist_completed_job(job_id, result, memo)
    except Exception as exc:
        logger.exception("Investment job %s failed during execution.", job_id)
        with get_db_session() as session:
            job = session.get(InvestmentJobRecord, job_id)
            if job:
                finished_at = datetime.now(timezone.utc)
                job.status = "failed"
                job.errors = [*(job.errors or []), str(exc)]
                job.finished_at = finished_at
                job.updated_at = finished_at
                if job.started_at:
                    job.duration_ms = int((finished_at - job.started_at).total_seconds() * 1000)
        publish_job_event(
            job_id,
            {
                "type": "job_failed",
                "status": "failed",
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


def get_investment_job_status(job_id: str) -> InvestmentJobStatusResponse | None:
    with get_db_session() as session:
        job = session.get(InvestmentJobRecord, job_id)
        if not job:
            return None
        agent_runs = session.scalars(
            select(AgentRunRecord).where(AgentRunRecord.job_id == job_id).order_by(AgentRunRecord.agent_name.asc())
        ).all()
        return InvestmentJobStatusResponse(
            job_id=job.id,
            company_name=job.company_name,
            market=job.market,  # type: ignore[arg-type]
            status=job.status,  # type: ignore[arg-type]
            research_brief=job.research_brief,
            agent_runs=[_agent_run_status_from_record(item) for item in agent_runs],
            warnings=list(job.warnings or []),
            memo_id=job.memo_id,
            created_at=_iso(job.created_at),
            updated_at=_iso(job.updated_at),
            started_at=_iso(job.started_at),
            finished_at=_iso(job.finished_at),
        )


def list_investment_jobs(limit: int = 20) -> list[InvestmentJobListItem]:
    with get_db_session() as session:
        rows = session.scalars(
            select(InvestmentJobRecord).order_by(desc(InvestmentJobRecord.created_at)).limit(max(limit, 1))
        ).all()
        return [
            InvestmentJobListItem(
                job_id=row.id,
                company_name=row.company_name,
                market=row.market,  # type: ignore[arg-type]
                status=row.status,  # type: ignore[arg-type]
                created_at=_iso(row.created_at),
                memo_id=row.memo_id,
            )
            for row in rows
        ]


def get_investment_memo_response(memo_id: str) -> InvestmentMemoResponse | None:
    with get_db_session() as session:
        record = session.get(InvestmentMemoRecord, memo_id)
        if not record:
            return None
        return InvestmentMemoResponse(
            memo_id=record.id,
            job_id=record.job_id,
            memo=InvestmentMemo.model_validate(record.payload),
        )


def search_job_evidence(job_id: str, agent_name: str | None = None, category: str | None = None) -> EvidenceSearchResponse | None:
    with get_db_session() as session:
        job = session.get(InvestmentJobRecord, job_id)
        if not job:
            return None

        statement = select(EvidenceDocumentRecord).where(EvidenceDocumentRecord.job_id == job_id)
        if agent_name:
            statement = statement.where(EvidenceDocumentRecord.agent_name == agent_name)
        if category:
            statement = statement.where(EvidenceDocumentRecord.category == category)
        rows = session.scalars(statement.order_by(EvidenceDocumentRecord.created_at.desc()).limit(50)).all()
        return EvidenceSearchResponse(
            job_id=job_id,
            items=[
                EvidenceResponseItem(
                    id=row.id,
                    agent_name=row.agent_name,
                    source_type=row.source_type,
                    category=row.category,
                    title=row.title,
                    url=row.url,
                    published_at=row.published_at,
                    content=row.content,
                    metadata=row.metadata_json or {},
                )
                for row in rows
            ],
        )


def get_job_market_ohlcv_response(job_id: str) -> MarketOhlcvResponse | None:
    payload = get_job_market_ohlcv(job_id)
    if payload is None:
        return None
    company_name, instrument, series = payload
    return MarketOhlcvResponse(
        job_id=job_id,
        company_name=company_name,
        market=instrument.market,
        instrument=instrument,
        series=series,
    )


def wait_for_job_completion(job_id: str, timeout_seconds: int) -> InvestmentJobStatusResponse | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = get_investment_job_status(job_id)
        if not status:
            return None
        if status.status in {"partial", "succeeded", "failed"}:
            return status
        time.sleep(1)
    return get_investment_job_status(job_id)


def get_job_memo(job_id: str) -> InvestmentMemo | None:
    with get_db_session() as session:
        job = session.get(InvestmentJobRecord, job_id)
        if not job or not job.memo_id:
            return None
        record = session.get(InvestmentMemoRecord, job.memo_id)
        if not record:
            return None
        return InvestmentMemo.model_validate(record.payload)


def check_dependencies_health() -> dict[str, Any]:
    db_ok = False
    redis_ok = False
    try:
        with get_db_session() as session:
            session.execute(select(1))
            db_ok = True
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)

    try:
        redis_ok = bool(get_redis_client().ping())
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)

    return {
        "database": "ok" if db_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
        "status": "ok" if db_ok and redis_ok else "degraded",
    }


def _handle_progress_event(job_id: str, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload.setdefault("job_id", job_id)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    event_type = payload.get("type")
    agent_name = payload.get("agent_name")
    with get_db_session() as session:
        job = session.get(InvestmentJobRecord, job_id)
        if job is None:
            publish_job_event(job_id, payload)
            return
        if event_type == "job_started":
            brief = payload.get("research_brief")
            if isinstance(brief, dict):
                job.research_brief = brief
                job.market = str(brief.get("market") or job.market)
        if event_type in {"agent_started", "tool_called", "observation_recorded", "agent_completed"} and isinstance(agent_name, str):
            row = session.scalar(
                select(AgentRunRecord).where(
                    AgentRunRecord.job_id == job_id,
                    AgentRunRecord.agent_name == agent_name,
                )
            )
            if row is None:
                row = AgentRunRecord(job_id=job_id, agent_name=agent_name, status="queued")
                session.add(row)
                session.flush()
            row.status = str(payload.get("status") or row.status or "running")
            row.current_step = payload.get("current_step") or row.current_step
            row.tool_calls_count = int(payload.get("tool_calls_count") or row.tool_calls_count or 0)
            row.summary = payload.get("summary") or row.summary
            row.warning = payload.get("warning") or row.warning
            row.error = payload.get("error") or row.error
            row.started_at = _parse_dt(payload.get("started_at")) or row.started_at
            row.finished_at = _parse_dt(payload.get("finished_at")) or row.finished_at
            row.duration_ms = payload.get("duration_ms") or row.duration_ms
        if event_type == "critic_warning" and payload.get("warning"):
            job.warnings = [*(job.warnings or []), str(payload["warning"])]
        job.updated_at = datetime.now(timezone.utc)
    publish_job_event(job_id, payload)


def _persist_completed_job(job_id: str, result: dict[str, Any], memo: InvestmentMemo) -> None:
    finished_at = datetime.now(timezone.utc)
    agent_results = {
        name: item if isinstance(item, AgentResult) else AgentResult.model_validate(item)
        for name, item in (result.get("agent_results") or {}).items()
    }
    documents, chunks = build_documents_and_chunks(agent_results)
    critic_summary = memo.critic_summary
    event_items = result.get("event_items") or []

    with get_db_session() as session:
        job = session.get(InvestmentJobRecord, job_id)
        if not job:
            raise RuntimeError(f"Job {job_id} disappeared before completion persistence.")

        memo_record = InvestmentMemoRecord(
            job_id=job_id,
            company_name=job.company_name,
            market=memo.market,
            stance=memo.stance,
            payload=memo.model_dump(),
        )
        session.add(memo_record)
        session.flush()

        document_id_map: dict[str, str] = {}
        for document in documents:
            record = EvidenceDocumentRecord(
                job_id=job_id,
                agent_name=document.agent_name,
                source_type=document.source_type,
                category=document.category,
                title=document.title,
                url=document.url,
                published_at=document.date,
                content=document.content,
                metadata_json=document.metadata,
            )
            session.add(record)
            session.flush()
            document_id_map[document.id] = record.id

        chunk_id_map: dict[str, str] = {}
        for chunk in chunks:
            record = EvidenceChunkRecord(
                job_id=job_id,
                document_id=document_id_map[chunk.document_id],
                agent_name=chunk.agent_name,
                source_type=chunk.source_type,
                category=chunk.category,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=chunk.embedding,
                metadata_json=chunk.metadata,
            )
            session.add(record)
            session.flush()
            chunk_id_map[chunk.id] = record.id

        for citation in memo.citations:
            session.add(
                MemoCitationRecord(
                    job_id=job_id,
                    memo_id=memo_record.id,
                    chunk_id=chunk_id_map.get(citation.chunk_id or ""),
                    claim=citation.claim,
                    agent_name=citation.agent_name,
                    source_type=citation.source_type,
                    category=citation.category,
                    title=citation.title,
                    snippet=citation.snippet,
                    url=citation.url,
                    published_at=citation.date,
                    score=citation.score,
                )
            )

        if critic_summary:
            session.add(
                CriticRunRecord(
                    job_id=job_id,
                    memo_id=memo_record.id,
                    payload=critic_summary.model_dump(),
                    citation_coverage_score=critic_summary.citation_coverage_score,
                    freshness_score=critic_summary.freshness_score,
                    consistency_score=critic_summary.consistency_score,
                    duplicate_event_bias_score=critic_summary.duplicate_event_bias_score,
                    stance_supported=critic_summary.stance_supported,
                )
            )

        for event in event_items:
            session.add(
                EventRecord(
                    job_id=job_id,
                    agent_name="news_risk",
                    title=event.title,
                    category=event.category,
                    horizon=event.horizon,
                    sentiment=event.sentiment,
                    impact_score=event.impact_score,
                    confidence_score=event.confidence_score,
                    occurred_at=event.date,
                    summary=event.summary,
                    source_ids=event.source_ids,
                    metadata_json={},
                )
            )

        for agent_name, result_item in agent_results.items():
            row = session.scalar(
                select(AgentRunRecord).where(
                    AgentRunRecord.job_id == job_id,
                    AgentRunRecord.agent_name == agent_name,
                )
            )
            if row is None:
                row = AgentRunRecord(job_id=job_id, agent_name=agent_name)
                session.add(row)
                session.flush()
            row.status = result_item.status
            row.current_step = result_item.current_step
            row.tool_calls_count = result_item.tool_calls_count
            row.summary = result_item.summary
            row.warning = result_item.warning
            row.error = result_item.error
            row.metrics = result_item.metrics
            row.payload = result_item.payload
            row.started_at = _parse_dt(result_item.started_at) or row.started_at
            row.finished_at = _parse_dt(result_item.finished_at) or row.finished_at
            row.duration_ms = result_item.duration_ms

        final_status = _final_status(agent_results, memo)
        job.status = final_status
        job.memo_id = memo_record.id
        job.market = memo.market
        job.research_brief = result.get("research_brief").model_dump() if result.get("research_brief") else job.research_brief
        job.warnings = list(dict.fromkeys([*(job.warnings or []), *memo.limitations]))
        job.finished_at = finished_at
        job.updated_at = finished_at
        if job.started_at:
            job.duration_ms = int((finished_at - job.started_at).total_seconds() * 1000)

    publish_job_event(
        job_id,
        {
            "type": "job_status",
            "status": _final_status(agent_results, memo),
            "memo_id": memo_record.id,
            "timestamp": finished_at.isoformat(),
        },
    )


def _final_status(agent_results: dict[str, AgentResult], memo: InvestmentMemo) -> str:
    if not agent_results:
        return "failed"
    if any(item.status in {"failed", "partial", "skipped"} for item in agent_results.values()):
        return "partial"
    if memo.critic_summary and memo.critic_summary.warnings:
        return "partial"
    return "succeeded"


def _agent_run_status_from_record(row: AgentRunRecord) -> AgentRunStatus:
    return AgentRunStatus(
        agent_name=row.agent_name,
        status=row.status,
        current_step=row.current_step,
        tool_calls_count=row.tool_calls_count,
        summary=row.summary,
        warning=row.warning,
        error=row.error,
        started_at=_iso(row.started_at),
        finished_at=_iso(row.finished_at),
        duration_ms=row.duration_ms,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_legacy_report_response(memo_id: str) -> dict[str, Any] | None:
    memo = get_investment_memo_response(memo_id)
    if memo is None:
        return None
    return {
        "report_id": memo.memo_id,
        "job_id": memo.job_id,
        "report": memo.memo.model_dump(),
    }


# Compatibility wrappers for deprecated v1 service callers.
create_research_job = create_investment_job
process_research_job = process_investment_job
get_research_job_status = get_investment_job_status
list_research_jobs = list_investment_jobs
get_report_response = get_legacy_report_response
get_job_report = get_job_memo
