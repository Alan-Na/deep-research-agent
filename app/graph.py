from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.critic_output import run_critic_output_agent
from app.agents.registry import get_research_agent_definitions
from app.agents.runtime import execute_react_agent
from app.investment.intake import build_research_brief
from app.research.retrieval import build_documents_and_chunks, build_evidence_index
from app.schemas import AgentResult, InvestmentState, ResearchBrief
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _emit_progress(state: InvestmentState, payload: dict[str, Any]) -> None:
    callback = state.get("progress_callback")
    if callback:
        callback(payload)


def intake_brief_node(state: InvestmentState) -> dict[str, Any]:
    brief = build_research_brief(state["company_name"])
    _emit_progress(
        state,
        {
            "type": "job_started",
            "company_name": state["company_name"],
            "market": brief.market,
            "research_brief": brief.model_dump(),
        },
    )
    return {"research_brief": brief, "warnings": list(brief.briefing_notes)}


def parallel_research_node(state: InvestmentState) -> dict[str, Any]:
    brief = state["research_brief"]
    results: dict[str, AgentResult] = {}
    shared_context = {"research_brief": brief.model_dump()}
    definitions = get_research_agent_definitions()
    with ThreadPoolExecutor(max_workers=len(definitions)) as executor:
        future_map = {
            executor.submit(
                execute_react_agent,
                definition,
                brief,
                dict(shared_context),
                progress_callback=state.get("progress_callback"),
            ): definition.agent_name
            for definition in definitions
        }
        for future in as_completed(future_map):
            agent_name = future_map[future]
            results[agent_name] = future.result()
    return {"agent_results": results}


def evidence_index_node(state: InvestmentState) -> dict[str, Any]:
    agent_results = state.get("agent_results", {})
    evidence_items, event_items, coverage = build_evidence_index(agent_results)
    _, chunks = build_documents_and_chunks(agent_results)
    return {
        "evidence_items": evidence_items,
        "event_items": event_items,
        "coverage": coverage,
        "retrieval_chunks": chunks,
    }


def critic_output_node(state: InvestmentState) -> dict[str, Any]:
    memo = run_critic_output_agent(
        brief=state["research_brief"],
        agent_results=state.get("agent_results", {}),
        events=state.get("event_items", []),
        coverage=state.get("coverage", {}),
        chunks=state.get("retrieval_chunks", []),
    )
    critic_summary = memo.critic_summary
    if critic_summary:
        for warning in critic_summary.warnings:
            _emit_progress(
                state,
                {
                    "type": "critic_warning",
                    "warning": warning,
                },
            )
    return {"memo": memo}


def finalize_node(state: InvestmentState) -> dict[str, Any]:
    memo = state["memo"]
    _emit_progress(
        state,
        {
            "type": "memo_ready",
            "stance": memo.stance,
            "stance_confidence": memo.stance_confidence,
            "citation_count": len(memo.citations),
        },
    )
    return {"memo": memo}


def create_investment_graph():
    builder = StateGraph(InvestmentState)
    builder.add_node("intake_brief", intake_brief_node)
    builder.add_node("parallel_research", parallel_research_node)
    builder.add_node("evidence_index", evidence_index_node)
    builder.add_node("critic_output", critic_output_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "intake_brief")
    builder.add_edge("intake_brief", "parallel_research")
    builder.add_edge("parallel_research", "evidence_index")
    builder.add_edge("evidence_index", "critic_output")
    builder.add_edge("critic_output", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()


# Compatibility alias for the deprecated v1 entrypoint.
create_research_graph = create_investment_graph
