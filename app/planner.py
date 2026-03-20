from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from app.llm import get_chat_model, is_llm_available
from app.prompts import PLANNER_SYSTEM_PROMPT, PLANNER_USER_PROMPT
from app.schemas import PlannerOutput
from app.utils.logging import get_logger

logger = get_logger(__name__)
MODULE_PRIORITY = ["price", "filing", "website", "news"]


def _normalize_planner_output(planner_output: PlannerOutput) -> PlannerOutput:
    # 中文注释：统一模块顺序，去重，并应用最基础的业务约束。
    selected = []
    for module_name in MODULE_PRIORITY:
        if module_name in planner_output.selected_modules and module_name not in selected:
            selected.append(module_name)

    if "website" not in selected:
        selected.append("website")
    if "news" not in selected:
        selected.append("news")

    if planner_output.is_public is False:
        selected = [item for item in selected if item not in {"price", "filing"}]

    if planner_output.market != "US":
        selected = [item for item in selected if item != "filing"]

    return planner_output.model_copy(update={"selected_modules": selected})


def heuristic_plan(company_name: str, reason: str | None = None) -> PlannerOutput:
    # 中文注释：当模型不可用或结构化输出失败时，退化到最保守的方案。
    rationale = "Fallback planner used; listing status and market could not be confirmed."
    if reason:
        rationale = f"{rationale} {reason}"

    return PlannerOutput(
        company_name=company_name,
        is_public="unknown",
        market="UNKNOWN",
        selected_modules=["website", "news"],
        rationale=rationale,
        confidence=0.25,
    )


def plan_company_research(company_name: str) -> PlannerOutput:
    if not is_llm_available():
        logger.warning("Planner fallback triggered because OPENAI_API_KEY is missing.")
        return heuristic_plan(company_name, "OPENAI_API_KEY is missing.")

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", PLANNER_SYSTEM_PROMPT),
            ("human", PLANNER_USER_PROMPT),
        ]
    )

    try:
        llm = get_chat_model(temperature=0.0)
        structured_llm = llm.with_structured_output(PlannerOutput, method="json_schema")
        result = (prompt | structured_llm).invoke({"company_name": company_name})
        validated = PlannerOutput.model_validate(result)
        return _normalize_planner_output(validated)
    except Exception as exc:
        logger.exception("Planner failed. Falling back to heuristic planner.")
        return heuristic_plan(company_name, str(exc))
