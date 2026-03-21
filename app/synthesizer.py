from __future__ import annotations

import json

from langchain_core.prompts import ChatPromptTemplate

from app.config import get_settings
from app.llm import get_chat_model, is_llm_available
from app.prompts import FINAL_SYNTHESIS_SYSTEM_PROMPT, FINAL_SYNTHESIS_USER_PROMPT
from app.schemas import CoverageCheck, EvidenceCard, FinalReport, ModuleResult, PlannerOutput
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _score_text(text: str) -> int:
    lowered = text.lower()
    positive_words = ["growth", "beat", "improve", "strong", "record", "up", "partnership", "positive", "launch"]
    negative_words = ["risk", "decline", "weak", "loss", "lawsuit", "probe", "down", "negative", "recall", "layoff"]
    score = sum(1 for word in positive_words if word in lowered)
    score -= sum(1 for word in negative_words if word in lowered)
    return score


def _filing_fact_key_points(module_result: ModuleResult) -> tuple[list[str], list[str]]:
    structured_facts = module_result.metrics.get("structured_facts", {}) if module_result.metrics else {}
    if not isinstance(structured_facts, dict):
        return [], []

    key_findings: list[str] = []
    risks: list[str] = []

    if structured_facts.get("revenue"):
        finding = f"Filing revenue: {structured_facts['revenue']}"
        if structured_facts.get("revenue_yoy"):
            finding += f" ({structured_facts['revenue_yoy']} YoY)"
        key_findings.append(finding)
    if structured_facts.get("gross_margin"):
        key_findings.append(f"Filing gross margin: {structured_facts['gross_margin']}")
    if structured_facts.get("operating_income"):
        key_findings.append(f"Filing operating income: {structured_facts['operating_income']}")
    if structured_facts.get("net_income"):
        key_findings.append(f"Filing net income: {structured_facts['net_income']}")
    if structured_facts.get("eps"):
        key_findings.append(f"Filing EPS: {structured_facts['eps']}")
    if structured_facts.get("operating_cash_flow"):
        key_findings.append(f"Operating cash flow: {structured_facts['operating_cash_flow']}")
    if structured_facts.get("free_cash_flow"):
        key_findings.append(f"Free cash flow: {structured_facts['free_cash_flow']}")
    if structured_facts.get("guidance"):
        key_findings.extend(structured_facts["guidance"][:1])
    if structured_facts.get("unusual_items"):
        key_findings.extend(structured_facts["unusual_items"][:1])
    if structured_facts.get("key_risks"):
        risks.extend(structured_facts["key_risks"][:3])

    return key_findings, risks


def heuristic_final_report(
    company_name: str,
    planner_output: PlannerOutput,
    module_results: dict[str, ModuleResult],
    evidence_cards: list[EvidenceCard],
    coverage_check: CoverageCheck,
) -> FinalReport:
    # 最终兜底报告，避免整个流程在综合阶段中断。
    summaries = [result.summary for result in module_results.values() if result.summary]
    text_for_scoring = " ".join(summaries)
    score = _score_text(text_for_scoring)

    sentiment = "neutral"
    if score > 1:
        sentiment = "positive"
    elif score < -1:
        sentiment = "negative"

    key_findings: list[str] = []
    risks: list[str] = []
    limitations = list(coverage_check.warnings)

    for module_name, result in module_results.items():
        if module_name == "filing":
            filing_findings, filing_risks = _filing_fact_key_points(result)
            key_findings.extend(filing_findings)
            risks.extend(filing_risks)

        if result.key_points:
            key_findings.extend(result.key_points[:2])
        if result.rag_answers.get("risk_factors"):
            risk_values = result.rag_answers["risk_factors"]
            if isinstance(risk_values, list):
                risks.extend(risk_values[:2])
        if result.status in {"failed", "partial"} and result.warning:
            limitations.append(f"{module_name}: {result.warning}")
        if result.status == "failed" and result.error:
            limitations.append(f"{module_name}: execution error.")
        if "risk" in result.summary.lower():
            risks.append(result.summary)

    summary = " ".join(summaries[:3]) or f"Recent research for {company_name} used heuristic synthesis."
    if coverage_check.valid_module_count < 2:
        limitations.append("Less than two modules produced meaningful output.")

    return FinalReport(
        company_name=company_name,
        overall_sentiment=sentiment,
        summary=summary,
        key_findings=key_findings[:8],
        risks=risks[:8],
        limitations=list(dict.fromkeys(limitations))[:8],
        module_results=module_results,
        evidence=evidence_cards[: get_settings().final_evidence_limit],
    )


def synthesize_final_report(
    company_name: str,
    planner_output: PlannerOutput,
    module_results: dict[str, ModuleResult],
    evidence_cards: list[EvidenceCard],
    coverage_check: CoverageCheck,
) -> FinalReport:
    if not is_llm_available():
        logger.warning("Final synthesizer fallback triggered because OPENAI_API_KEY is missing.")
        return heuristic_final_report(company_name, planner_output, module_results, evidence_cards, coverage_check)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", FINAL_SYNTHESIS_SYSTEM_PROMPT),
            ("human", FINAL_SYNTHESIS_USER_PROMPT),
        ]
    )

    try:
        llm = get_chat_model(temperature=0.0)
        structured_llm = llm.with_structured_output(FinalReport, method="function_calling")
        result = (prompt | structured_llm).invoke(
            {
                "company_name": company_name,
                "planner_payload": planner_output.model_dump_json(indent=2),
                "module_results_payload": json.dumps(
                    {name: result.model_dump() for name, result in module_results.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                "evidence_payload": json.dumps(
                    [card.model_dump() for card in evidence_cards[: get_settings().final_evidence_limit]],
                    ensure_ascii=False,
                    indent=2,
                ),
                "coverage_payload": coverage_check.model_dump_json(indent=2),
            }
        )
        validated = FinalReport.model_validate(result)
        return validated
    except Exception:
        logger.exception("Final synthesizer failed. Falling back to heuristic report.")
        return heuristic_final_report(company_name, planner_output, module_results, evidence_cards, coverage_check)
