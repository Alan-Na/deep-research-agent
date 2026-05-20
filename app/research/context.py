from __future__ import annotations

import json
import hashlib
from typing import Any

from app.schemas import (
    AgentResult,
    EventItem,
    ResearchBrief,
    SentimentName,
    UnifiedAgentResearch,
    UnifiedResearchContext,
    UnifiedResearchFinding,
)
from app.utils.text import truncate_text

RESEARCH_AGENT_ORDER = ["market", "filing", "message_intel"]


def build_unified_research_context(
    brief: ResearchBrief,
    agent_results: dict[str, AgentResult],
    events: list[EventItem],
    coverage: dict[str, Any],
) -> UnifiedResearchContext:
    agents: dict[str, UnifiedAgentResearch] = {}
    for agent_name in RESEARCH_AGENT_ORDER:
        result = agent_results.get(agent_name)
        if not result:
            continue
        agents[agent_name] = _adapt_agent_result(agent_name, result)

    context = UnifiedResearchContext(
        company_name=brief.company_name,
        market=brief.market,
        instrument=brief.instrument,
        research_brief_notes=list(brief.briefing_notes),
        agents=agents,
        cross_agent=_build_cross_agent_summary(agents, coverage),
        events=events[:12],
        coverage=coverage,
    )
    document = build_llm_research_document(context)
    return context.model_copy(update={"llm_context_document": document})


def build_llm_research_document(context: UnifiedResearchContext) -> str:
    lines = [
        "# Unified Company Research Context",
        "",
        "This document is the normalized research context for downstream LLM reasoning and dialogue.",
        "Use only the facts, evidence, warnings, and open questions in this document. Do not invent missing data.",
        "",
        "## Research Brief",
        f"- Company: {context.company_name}",
        f"- Market: {context.market}",
        f"- Instrument: {context.instrument.symbol or 'unknown'} / {context.instrument.display_name or context.company_name}",
    ]
    if context.research_brief_notes:
        lines.append(f"- Notes: {'; '.join(context.research_brief_notes)}")

    lines.extend(
        [
            "",
            "## Cross-Agent Snapshot",
            f"- Overall signal bias: {context.cross_agent.get('overall_signal_bias', 'neutral')}",
            f"- Valid agents: {context.coverage.get('valid_agent_count', 0)}",
            f"- Evidence count: {context.coverage.get('evidence_count', 0)}",
            f"- Event count: {context.coverage.get('event_count', 0)}",
        ]
    )
    warnings = context.cross_agent.get("warnings") or []
    if warnings:
        lines.append(f"- Warnings: {'; '.join(str(item) for item in warnings[:8])}")

    for agent_name in RESEARCH_AGENT_ORDER:
        agent = context.agents.get(agent_name)
        if not agent:
            continue
        lines.extend(_agent_section(agent))

    if context.events:
        lines.extend(["", "## Normalized Events"])
        for event in context.events[:10]:
            lines.append(
                f"- [{event.sentiment}] {event.title} | category={event.category} | "
                f"horizon={event.horizon} | impact={event.impact_score} | confidence={event.confidence_score}"
            )
            lines.append(f"  Evidence summary: {event.summary}")

    return "\n".join(lines).strip()


def _adapt_agent_result(agent_name: str, result: AgentResult) -> UnifiedAgentResearch:
    if agent_name == "market":
        return _adapt_market_result(result)
    if agent_name == "filing":
        return _adapt_filing_result(result)
    if agent_name == "message_intel":
        return _adapt_message_result(result)
    return _adapt_generic_result(agent_name, result)


def _adapt_market_result(result: AgentResult) -> UnifiedAgentResearch:
    payload = result.payload or {}
    snapshot = payload.get("market_snapshot") or {}
    valuation = snapshot.get("valuation") or {}
    returns = snapshot.get("returns") or {}
    volatility = snapshot.get("volatility") or {}
    metrics = {
        "last_price": snapshot.get("last_price"),
        "as_of": snapshot.get("as_of"),
        "one_day_pct": returns.get("one_day_pct"),
        "one_month_pct": returns.get("one_month_pct"),
        "three_month_pct": returns.get("three_month_pct"),
        "realized_20d_pct": volatility.get("realized_20d_pct"),
        "pe_ttm": valuation.get("pe_ttm"),
        "pb": valuation.get("pb"),
        "market_cap": valuation.get("market_cap"),
    }
    findings = [
        _finding(
            result,
            "market_snapshot",
            "Market snapshot and valuation metrics.",
            evidence={key: value for key, value in metrics.items() if value is not None},
        )
    ]
    return _agent_research(result, metrics=metrics, findings=findings)


def _adapt_filing_result(result: AgentResult) -> UnifiedAgentResearch:
    payload = result.payload or {}
    analysis = payload.get("financial_statement_analysis") or {}
    assessment = analysis.get("overall_financial_assessment") or {}
    snapshot = analysis.get("financial_snapshot") or {}
    key_metrics = analysis.get("key_metrics") or {}
    trend_analysis = analysis.get("trend_analysis") or {}
    findings: list[UnifiedResearchFinding] = []
    summary = assessment.get("summary")
    if summary:
        findings.append(_finding(result, "financial_assessment", str(summary), evidence=assessment))
    for item in analysis.get("strengths") or []:
        findings.append(
            _finding(
                result,
                f"financial_strength:{item.get('type', 'unknown')}",
                str(item.get("summary") or ""),
                sentiment="positive",
                confidence=item.get("confidence"),
                evidence=item.get("evidence") or {},
            )
        )
    for item in analysis.get("risks") or []:
        findings.append(
            _finding(
                result,
                f"financial_risk:{item.get('type', 'unknown')}",
                str(item.get("summary") or ""),
                sentiment="negative",
                confidence=item.get("confidence"),
                evidence=item.get("evidence") or {},
            )
        )
    metrics = {
        "period": analysis.get("period"),
        "currency": analysis.get("currency"),
        "unit": analysis.get("unit"),
        "filing_coverage": analysis.get("filing_coverage"),
        "period_analyses": analysis.get("period_analyses") or [],
        "trend_analysis": trend_analysis,
        "financial_score": analysis.get("financial_score"),
        "snapshot": _compact_dict(snapshot),
        "key_metrics": _compact_dict(key_metrics),
        "data_quality": analysis.get("data_quality"),
    }
    warnings = [*(result.warning.split(" | ") if result.warning else [])]
    warnings.extend(str(item.get("warning")) for item in analysis.get("metric_warnings") or [] if item.get("warning"))
    return _agent_research(result, metrics=metrics, findings=findings, warnings=warnings)


def _adapt_message_result(result: AgentResult) -> UnifiedAgentResearch:
    payload = result.payload or {}
    analysis = payload.get("news_signal_analysis") or {}
    findings: list[UnifiedResearchFinding] = []
    for event in analysis.get("events") or []:
        findings.append(
            _finding(
                result,
                f"news_event:{event.get('category', 'other')}",
                str(event.get("one_line_summary") or event.get("summary") or event.get("title") or ""),
                sentiment=event.get("sentiment"),
                confidence=event.get("sentiment_score"),
                impact=min(1.0, 0.35 + min(int(event.get("duplicate_count") or 1), 5) * 0.05),
                evidence={
                    "title": event.get("title"),
                    "time": event.get("time"),
                    "keywords": event.get("keywords") or [],
                    "metrics": event.get("extracted_metrics") or [],
                    "sentiment_method": event.get("sentiment_method"),
                    "duplicate_count": event.get("duplicate_count"),
                },
                source_refs=[url for url in [event.get("source_url"), *(event.get("source_urls") or [])] if url],
            )
        )
    metrics = {
        "dominant_narrative": analysis.get("dominant_narrative") or payload.get("dominant_narrative"),
        "raw_article_count": analysis.get("raw_article_count"),
        "deduped_event_count": analysis.get("deduped_event_count"),
        "data_quality": analysis.get("data_quality"),
        "official_website": payload.get("official_website"),
        "product_points": payload.get("product_points") or [],
        "ir_highlights": payload.get("ir_highlights") or [],
        "positioning": payload.get("positioning") or [],
    }
    warnings = [*(result.warning.split(" | ") if result.warning else []), *(analysis.get("warnings") or [])]
    return _agent_research(result, metrics=metrics, findings=findings, warnings=warnings)


def _adapt_generic_result(agent_name: str, result: AgentResult) -> UnifiedAgentResearch:
    return _agent_research(
        result,
        metrics=dict(result.metrics or {}),
        findings=[_finding(result, "agent_summary", result.summary)],
    )


def _agent_research(
    result: AgentResult,
    *,
    metrics: dict[str, Any],
    findings: list[UnifiedResearchFinding],
    warnings: list[str] | None = None,
) -> UnifiedAgentResearch:
    return UnifiedAgentResearch(
        agent_name=result.agent_name,
        status=result.status,
        signal_bias=_normalize_signal_bias((result.payload or {}).get("signal_bias")),
        summary=result.summary,
        key_points=list(result.key_points[:8]),
        findings=findings[:12],
        metrics={key: value for key, value in metrics.items() if value not in (None, {}, [])},
        warnings=list(dict.fromkeys([item for item in (warnings or []) if item])),
        payload_keys=sorted((result.payload or {}).keys()),
    )


def _agent_section(agent: UnifiedAgentResearch) -> list[str]:
    lines = [
        "",
        f"## {agent.agent_name} Agent",
        f"- Status: {agent.status}",
        f"- Signal bias: {agent.signal_bias}",
        f"- Summary: {truncate_text(agent.summary, 500)}",
    ]
    if agent.key_points:
        lines.append("- Key points:")
        for point in agent.key_points[:6]:
            lines.append(f"  - {truncate_text(point, 260)}")
    if agent.metrics:
        lines.append("- Normalized metrics:")
        lines.append(f"  ```json\n  {_json_dumps(agent.metrics)}\n  ```")
    if agent.findings:
        lines.append("- Findings:")
        for finding in agent.findings[:8]:
            lines.append(
                f"  - [{finding.category}] {finding.summary} "
                f"(sentiment={finding.sentiment or 'n/a'}, confidence={finding.confidence_score if finding.confidence_score is not None else 'n/a'})"
            )
            if finding.evidence:
                lines.append(f"    Evidence: {_json_dumps(finding.evidence)}")
            if finding.source_refs:
                lines.append(f"    Sources: {', '.join(finding.source_refs[:3])}")
    if agent.warnings:
        lines.append(f"- Agent warnings: {'; '.join(agent.warnings[:6])}")
    return lines


def _finding(
    result: AgentResult,
    category: str,
    summary: str,
    *,
    sentiment: str | None = None,
    impact: float | None = None,
    confidence: float | None = None,
    evidence: dict[str, Any] | None = None,
    source_refs: list[str] | None = None,
) -> UnifiedResearchFinding:
    digest = hashlib.md5(f"{result.agent_name}|{category}|{summary}".encode("utf-8")).hexdigest()[:10]
    return UnifiedResearchFinding(
        id=f"{result.agent_name}:{category}:{digest}",
        agent_name=result.agent_name,
        category=category,
        summary=truncate_text(summary, 500),
        sentiment=_normalize_optional_sentiment(sentiment),
        impact_score=_safe_score(impact),
        confidence_score=_safe_score(confidence),
        evidence=evidence or {},
        source_refs=list(dict.fromkeys(source_refs or []))[:5],
    )


def _build_cross_agent_summary(agents: dict[str, UnifiedAgentResearch], coverage: dict[str, Any]) -> dict[str, Any]:
    biases = [agent.signal_bias for agent in agents.values()]
    positive = biases.count("positive")
    negative = biases.count("negative")
    overall = "positive" if positive > negative else "negative" if negative > positive else "neutral"
    return {
        "overall_signal_bias": overall,
        "agent_statuses": {name: agent.status for name, agent in agents.items()},
        "signal_biases": {name: agent.signal_bias for name, agent in agents.items()},
        "warnings": list(dict.fromkeys(coverage.get("warnings") or [])),
        "open_questions": _open_questions(agents),
    }


def _open_questions(agents: dict[str, UnifiedAgentResearch]) -> list[str]:
    questions: list[str] = []
    filing = agents.get("filing")
    if filing:
        score = (filing.metrics.get("financial_score") or {}) if isinstance(filing.metrics.get("financial_score"), dict) else {}
        if score.get("overall") in {None, 1, 2, 3}:
            questions.append("Financial statement extraction should be verified against original filings before strong conclusions.")
    message = agents.get("message_intel")
    if message and message.signal_bias != "neutral":
        questions.append("Check whether dominant news events are company-specific catalysts or broader sector/market noise.")
    market = agents.get("market")
    if market and market.metrics.get("pe_ttm"):
        questions.append("Compare valuation multiples with peers before treating price momentum as fundamental upside.")
    return questions[:6]


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _normalize_signal_bias(value: Any) -> SentimentName:
    return value if value in {"positive", "neutral", "negative"} else "neutral"


def _normalize_optional_sentiment(value: Any) -> SentimentName | None:
    return value if value in {"positive", "neutral", "negative"} else None


def _safe_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
