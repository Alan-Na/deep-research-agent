from __future__ import annotations

from dataclasses import dataclass

from app.schemas import ModuleName, ModuleResult, PlannerOutput


@dataclass(frozen=True)
class RouteDecision:
    should_run: bool
    reason: str


def module_selected(planner_output: PlannerOutput, module_name: ModuleName) -> bool:
    return module_name in planner_output.selected_modules


def route_price(planner_output: PlannerOutput) -> RouteDecision:
    if not module_selected(planner_output, "price"):
        return RouteDecision(False, "Planner did not select the price module.")
    if planner_output.is_public is False:
        return RouteDecision(False, "Planner marked the company as non-public.")
    if planner_output.market in {"NONE", "UNKNOWN"}:
        return RouteDecision(False, f"Market is {planner_output.market}.")
    return RouteDecision(True, "Price module is allowed.")


def route_filing(planner_output: PlannerOutput) -> RouteDecision:
    if not module_selected(planner_output, "filing"):
        return RouteDecision(False, "Planner did not select the filing module.")
    if planner_output.market != "US":
        return RouteDecision(False, "SEC filing research is enabled only for US market entities.")
    return RouteDecision(True, "Filing module is allowed.")


def route_website(planner_output: PlannerOutput) -> RouteDecision:
    if not module_selected(planner_output, "website"):
        return RouteDecision(False, "Planner did not select the website module.")
    return RouteDecision(True, "Website module is allowed.")


def route_news(planner_output: PlannerOutput) -> RouteDecision:
    if not module_selected(planner_output, "news"):
        return RouteDecision(False, "Planner did not select the news module.")
    return RouteDecision(True, "News module is allowed.")


def build_skipped_result(module_name: ModuleName, reason: str) -> ModuleResult:
    return ModuleResult(
        module=module_name,
        applicable=False,
        status="skipped",
        summary=f"{module_name} module skipped: {reason}",
        reason=reason,
    )
