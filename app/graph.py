from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.planner import plan_company_research
from app.schemas import CompanyIdentifiers, CoverageCheck, EvidenceCard, ModuleResult, ResearchState
from app.synthesizer import synthesize_final_report
from app.tools.filing import run_filing_module
from app.tools.news import run_news_module
from app.tools.price import run_price_module
from app.tools.website import run_website_module
from app.utils.logging import get_logger
from app.utils.text import dedupe_items
from app.utils.time import is_recent
from app.config import get_settings

logger = get_logger(__name__)


def _initial_identifiers(state: ResearchState) -> CompanyIdentifiers:
    return state.get("identifiers") or CompanyIdentifiers()


def _initial_module_results(state: ResearchState) -> dict[str, ModuleResult]:
    return dict(state.get("module_results", {}))


def _initial_warnings(state: ResearchState) -> list[str]:
    return list(state.get("warnings", []))


def planner_node(state: ResearchState) -> dict:
    company_name = state["company_name"]
    logger.info("Planner node started for company=%s", company_name)
    planner_output = plan_company_research(company_name)
    logger.info("Planner node completed for company=%s modules=%s", company_name, planner_output.selected_modules)
    return {"planner_output": planner_output}


def price_node(state: ResearchState) -> dict:
    company_name = state["company_name"]
    planner_output = state["planner_output"]
    identifiers = _initial_identifiers(state)
    module_results = _initial_module_results(state)

    logger.info("Price node started for company=%s", company_name)
    result, updated_identifiers = run_price_module(company_name, planner_output, identifiers)
    module_results["price"] = result
    logger.info("Price node finished with status=%s", result.status)
    return {"module_results": module_results, "identifiers": updated_identifiers}


def filing_node(state: ResearchState) -> dict:
    company_name = state["company_name"]
    planner_output = state["planner_output"]
    identifiers = _initial_identifiers(state)
    module_results = _initial_module_results(state)

    logger.info("Filing node started for company=%s", company_name)
    result, updated_identifiers = run_filing_module(company_name, planner_output, identifiers)
    module_results["filing"] = result
    logger.info("Filing node finished with status=%s", result.status)
    return {"module_results": module_results, "identifiers": updated_identifiers}


def website_node(state: ResearchState) -> dict:
    company_name = state["company_name"]
    planner_output = state["planner_output"]
    identifiers = _initial_identifiers(state)
    module_results = _initial_module_results(state)

    logger.info("Website node started for company=%s", company_name)
    result, updated_identifiers = run_website_module(company_name, planner_output, identifiers)
    module_results["website"] = result
    logger.info("Website node finished with status=%s", result.status)
    return {"module_results": module_results, "identifiers": updated_identifiers}


def news_node(state: ResearchState) -> dict:
    company_name = state["company_name"]
    planner_output = state["planner_output"]
    identifiers = _initial_identifiers(state)
    module_results = _initial_module_results(state)

    logger.info("News node started for company=%s", company_name)
    result, updated_identifiers = run_news_module(company_name, planner_output, identifiers)
    module_results["news"] = result
    logger.info("News node finished with status=%s", result.status)
    return {"module_results": module_results, "identifiers": updated_identifiers}


def evidence_normalization_node(state: ResearchState) -> dict:
    logger.info("Evidence normalization node started.")
    module_results = state.get("module_results", {})
    warnings = _initial_warnings(state)

    evidence_cards: list[EvidenceCard] = []
    for result in module_results.values():
        evidence_cards.extend(result.evidence)
        if result.status in {"failed", "partial", "skipped"} and result.reason:
            warnings.append(f"{result.module}: {result.reason}")

    evidence_cards = dedupe_items(
        evidence_cards,
        lambda card: f"{card.module}|{card.title}|{card.url}|{card.date}|{card.snippet}",
    )

    logger.info("Evidence normalization node completed with count=%s", len(evidence_cards))
    return {
        "evidence_cards": evidence_cards,
        "warnings": list(dict.fromkeys(warnings)),
    }


def coverage_check_node(state: ResearchState) -> dict:
    logger.info("Coverage check node started.")
    settings = get_settings()
    module_results = state.get("module_results", {})
    evidence_cards = state.get("evidence_cards", [])
    warnings = _initial_warnings(state)

    valid_module_count = 0
    failed_or_skipped_modules: list[str] = []
    for module_name, result in module_results.items():
        if result.applicable and result.status in {"success", "partial"} and (result.summary or result.evidence):
            valid_module_count += 1
        if result.status in {"failed", "skipped"}:
            failed_or_skipped_modules.append(module_name)

    has_recent_evidence = any(is_recent(card.date, settings.recent_days_threshold) for card in evidence_cards)
    enough_evidence = len(evidence_cards) >= settings.minimum_evidence_cards

    if valid_module_count < 2:
        warnings.append("Coverage warning: fewer than two modules produced meaningful output.")
    if not has_recent_evidence:
        warnings.append("Coverage warning: no clearly recent evidence was detected.")
    if not enough_evidence:
        warnings.append("Coverage warning: evidence volume is thin for a confident conclusion.")

    coverage = CoverageCheck(
        valid_module_count=valid_module_count,
        evidence_count=len(evidence_cards),
        has_recent_evidence=has_recent_evidence,
        enough_evidence=enough_evidence,
        failed_or_skipped_modules=failed_or_skipped_modules,
        warnings=list(dict.fromkeys(warnings)),
    )
    logger.info("Coverage check node completed.")
    return {"coverage_check": coverage, "warnings": coverage.warnings}


def final_synthesizer_node(state: ResearchState) -> dict:
    logger.info("Final synthesizer node started.")
    final_report = synthesize_final_report(
        company_name=state["company_name"],
        planner_output=state["planner_output"],
        module_results=state.get("module_results", {}),
        evidence_cards=state.get("evidence_cards", []),
        coverage_check=state["coverage_check"],
    )
    logger.info("Final synthesizer node completed.")
    return {"final_report": final_report}


def create_research_graph():
    builder = StateGraph(ResearchState)

    builder.add_node("planner", planner_node)
    builder.add_node("price", price_node)
    builder.add_node("filing", filing_node)
    builder.add_node("website", website_node)
    builder.add_node("news", news_node)
    builder.add_node("normalize_evidence", evidence_normalization_node)
    builder.add_node("coverage_check", coverage_check_node)
    builder.add_node("final_synthesizer", final_synthesizer_node)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "price")
    builder.add_edge("price", "filing")
    builder.add_edge("filing", "website")
    builder.add_edge("website", "news")
    builder.add_edge("news", "normalize_evidence")
    builder.add_edge("normalize_evidence", "coverage_check")
    builder.add_edge("coverage_check", "final_synthesizer")
    builder.add_edge("final_synthesizer", END)

    return builder.compile()
