from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class InvestmentJobRecord(Base):
    __tablename__ = "investment_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    market: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    research_brief: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    memo_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    agent_runs: Mapped[list["AgentRunRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    memos: Mapped[list["InvestmentMemoRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    evidence_documents: Mapped[list["EvidenceDocumentRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    critic_runs: Mapped[list["CriticRunRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    events: Mapped[list["EventRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("job_id", "agent_name", name="uq_agent_run_job_agent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("investment_jobs.id", ondelete="CASCADE"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    current_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    job: Mapped[InvestmentJobRecord] = relationship(back_populates="agent_runs")


class InvestmentMemoRecord(Base):
    __tablename__ = "investment_memos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("investment_jobs.id", ondelete="CASCADE"), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    market: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    stance: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[InvestmentJobRecord] = relationship(back_populates="memos")
    citations: Mapped[list["MemoCitationRecord"]] = relationship(back_populates="memo", cascade="all, delete-orphan")


class EvidenceDocumentRecord(Base):
    __tablename__ = "evidence_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("investment_jobs.id", ondelete="CASCADE"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[InvestmentJobRecord] = relationship(back_populates="evidence_documents")
    chunks: Mapped[list["EvidenceChunkRecord"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class EvidenceChunkRecord(Base):
    __tablename__ = "evidence_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("evidence_documents.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("investment_jobs.id", ondelete="CASCADE"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(64))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    document: Mapped[EvidenceDocumentRecord] = relationship(back_populates="chunks")


class MemoCitationRecord(Base):
    __tablename__ = "memo_citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("investment_jobs.id", ondelete="CASCADE"), index=True)
    memo_id: Mapped[str] = mapped_column(ForeignKey("investment_memos.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_chunks.id", ondelete="SET NULL"), nullable=True)
    claim: Mapped[str] = mapped_column(Text)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    memo: Mapped[InvestmentMemoRecord] = relationship(back_populates="citations")


class CriticRunRecord(Base):
    __tablename__ = "critic_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("investment_jobs.id", ondelete="CASCADE"), index=True)
    memo_id: Mapped[str | None] = mapped_column(ForeignKey("investment_memos.id", ondelete="CASCADE"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    citation_coverage_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    consistency_score: Mapped[float] = mapped_column(Float, default=0.0)
    duplicate_event_bias_score: Mapped[float] = mapped_column(Float, default=0.0)
    stance_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[InvestmentJobRecord] = relationship(back_populates="critic_runs")


class EventRecord(Base):
    __tablename__ = "event_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("investment_jobs.id", ondelete="CASCADE"), index=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), index=True)
    horizon: Mapped[str] = mapped_column(String(64))
    sentiment: Mapped[str] = mapped_column(String(32))
    impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    occurred_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[InvestmentJobRecord] = relationship(back_populates="events")


# Compatibility aliases for deprecated v1 names.
ResearchJobRecord = InvestmentJobRecord
ModuleRunRecord = AgentRunRecord
ReportRecord = InvestmentMemoRecord
DocumentRecord = EvidenceDocumentRecord
ChunkRecord = EvidenceChunkRecord
CitationRecord = MemoCitationRecord
EvaluationRunRecord = CriticRunRecord
