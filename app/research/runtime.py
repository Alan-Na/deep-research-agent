from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable

from app.schemas import CompanyIdentifiers, ModuleResult, ModuleName, PlannerOutput
from app.tools.filing import run_filing_module
from app.tools.news import run_news_module
from app.tools.price import run_price_module
from app.tools.website import run_website_module

ProgressCallback = Callable[[dict], None]


def run_modules_in_parallel(
    company_name: str,
    planner_output: PlannerOutput,
    identifiers: CompanyIdentifiers,
    progress_callback: ProgressCallback | None = None,
) -> tuple[dict[str, ModuleResult], CompanyIdentifiers]:
    module_functions: dict[ModuleName, Callable[[str, PlannerOutput, CompanyIdentifiers], tuple[ModuleResult, CompanyIdentifiers]]] = {
        "price": run_price_module,
        "filing": run_filing_module,
        "website": run_website_module,
        "news": run_news_module,
    }

    results: dict[str, ModuleResult] = {}
    merged_identifiers = identifiers

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_module = {}
        for module_name, runner in module_functions.items():
            progress_callback and progress_callback(
                {
                    "type": "module_started",
                    "module": module_name,
                    "status": "running",
                    "timestamp": now_iso(),
                }
            )
            future = executor.submit(_run_single_module, runner, module_name, company_name, planner_output, identifiers)
            future_to_module[future] = module_name

        for future in as_completed(future_to_module):
            module_name = future_to_module[future]
            result, module_identifiers = future.result()
            results[module_name] = result
            merged_identifiers = _merge_identifiers(merged_identifiers, module_identifiers)
            progress_callback and progress_callback(
                {
                    "type": "module_finished",
                    "module": module_name,
                    "status": result.status,
                    "summary": result.summary,
                    "warning": result.warning,
                    "error": result.error,
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                    "duration_ms": result.duration_ms,
                    "timestamp": now_iso(),
                }
            )

    return results, merged_identifiers


def _run_single_module(
    runner: Callable[[str, PlannerOutput, CompanyIdentifiers], tuple[ModuleResult, CompanyIdentifiers]],
    module_name: ModuleName,
    company_name: str,
    planner_output: PlannerOutput,
    identifiers: CompanyIdentifiers,
) -> tuple[ModuleResult, CompanyIdentifiers]:
    started_at = now_iso()
    start_time = datetime.now(timezone.utc)
    result, module_identifiers = runner(company_name, planner_output, identifiers)
    finished_at = now_iso()
    duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    result = result.model_copy(
        update={
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
        }
    )
    return result, module_identifiers


def _merge_identifiers(base: CompanyIdentifiers, incoming: CompanyIdentifiers) -> CompanyIdentifiers:
    return base.model_copy(
        update={
            "ticker": base.ticker or incoming.ticker,
            "cik": base.cik or incoming.cik,
            "website_url": base.website_url or incoming.website_url,
            "exchange": base.exchange or incoming.exchange,
            "notes": list(dict.fromkeys([*base.notes, *incoming.notes])),
        }
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
