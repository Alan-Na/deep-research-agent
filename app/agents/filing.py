from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import requests

from app.agents.base import AgentDefinition, ToolDefinition
from app.config import get_settings
from app.schemas import (
    AgentResult,
    EvidenceItem,
    FinancialAssessment,
    FinancialDataQuality,
    FinancialKeyMetrics,
    FinancialMetricWarning,
    FinancialScore,
    FinancialSignal,
    FinancialSnapshot,
    FinancialStatementAnalysis,
    ResearchBrief,
)
from app.tools.filing import SecEdgarAdapter
from app.utils.http import build_headers
from app.utils.logging import get_logger
from app.utils.text import normalize_whitespace, truncate_text
from app.utils.time import utc_now

logger = get_logger(__name__)

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


INCOME_FIELDS = {"revenue", "gross_profit", "operating_income", "net_income", "eps"}
BALANCE_FIELDS = {
    "cash_and_equivalents",
    "accounts_receivable",
    "inventory",
    "total_assets",
    "total_debt",
    "total_liabilities",
    "shareholders_equity",
}
CASH_FLOW_FIELDS = {"operating_cash_flow", "capital_expenditure"}
FINANCIAL_SNAPSHOT_FIELDS = [
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps",
    "cash_and_equivalents",
    "accounts_receivable",
    "inventory",
    "total_assets",
    "total_debt",
    "total_liabilities",
    "shareholders_equity",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
]

FIELD_ALIASES = {
    "revenue": ["营业总收入", "营业收入", "主营业务收入", "revenue", "total revenue", "total revenues", "net sales", "sales", "net revenue", "operating revenue"],
    "gross_profit": ["毛利", "gross profit"],
    "operating_income": ["营业利润", "经营利润", "operating income", "income from operations", "operating profit", "profit from operations"],
    "net_income": ["归属于上市公司股东的净利润", "归母净利润", "净利润", "net income", "net earnings", "profit attributable to shareholders", "net profit"],
    "eps": ["基本每股收益", "稀释每股收益", "earnings per share", "diluted earnings per share", "basic earnings per share", "eps"],
    "cash_and_equivalents": ["货币资金", "现金及现金等价物", "cash and cash equivalents", "cash and equivalents", "cash equivalents"],
    "accounts_receivable": ["应收账款", "accounts receivable", "trade receivables"],
    "inventory": ["存货", "inventory", "inventories"],
    "total_assets": ["资产总计", "总资产", "total assets"],
    "total_debt": ["有息负债", "总债务", "短期借款", "长期借款", "total debt", "total borrowings", "interest-bearing debt", "short-term borrowings", "long-term borrowings"],
    "total_liabilities": ["负债合计", "总负债", "total liabilities"],
    "shareholders_equity": ["归属于母公司所有者权益合计", "所有者权益合计", "股东权益合计", "shareholders' equity", "shareholders equity", "stockholders' equity", "total equity"],
    "operating_cash_flow": ["经营活动产生的现金流量净额", "经营活动现金流量净额", "operating cash flow", "net cash provided by operating activities", "cash provided by operating activities"],
    "capital_expenditure": ["购建固定资产、无形资产和其他长期资产支付的现金", "购建固定资产", "资本开支", "资本性支出", "capital expenditure", "capital expenditures", "purchase of property and equipment", "purchases of property and equipment", "capex"],
}

NUMBER_PATTERN = re.compile(r"\(?-?(?:[$¥￥]|RMB|US\$|USD|CNY)?\s*\d[\d,]*(?:\.\d+)?\)?", re.IGNORECASE)


@dataclass
class FilingDocument:
    provider: str
    filing_type: str
    title: str
    filed_at: str
    url: str
    text: str


class AShareDisclosureProvider:
    base_url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    static_prefix = "http://static.cninfo.com.cn/"

    def fetch_recent_documents(self, brief: ResearchBrief, limit: int = 3) -> list[FilingDocument]:
        query = brief.instrument.symbol or brief.company_name
        categories = ["年报", "半年报", "一季报", "三季报"]
        announcements: list[dict[str, Any]] = []
        for category in categories:
            payload = {
                "pageNum": 1,
                "pageSize": 15,
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": "",
                "searchkey": query,
                "secid": "",
                "category": _cninfo_category(category),
                "trade": "",
                "seDate": f"{utc_now().year - 3}-01-01~{utc_now().date().isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            response = requests.post(self.base_url, data=payload, headers=build_headers(), timeout=get_settings().request_timeout)
            response.raise_for_status()
            data = response.json()
            announcements.extend(data.get("announcements", []))

        documents: list[FilingDocument] = []
        seen_urls: set[str] = set()
        for announcement in sorted(announcements, key=lambda item: item.get("announcementTime", 0), reverse=True):
            symbol = str(announcement.get("secCode") or "")
            if brief.instrument.symbol and symbol and symbol != brief.instrument.symbol:
                continue
            title = normalize_whitespace(re.sub(r"<[^>]+>", "", str(announcement.get("announcementTitle") or "")))
            filed_at = _millis_to_iso(announcement.get("announcementTime"))
            adjunct = str(announcement.get("adjunctUrl") or "").strip("/")
            if not adjunct:
                continue
            url = f"{self.static_prefix}{adjunct}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            text = _extract_document_text(url)
            if not text:
                text = title
            filing_type = _infer_filing_type(title)
            documents.append(
                FilingDocument(
                    provider="cninfo",
                    filing_type=filing_type,
                    title=title,
                    filed_at=filed_at,
                    url=url,
                    text=text,
                )
            )
            if len(documents) >= limit:
                break
        return documents


class SecProviderRegistry:
    def __init__(self) -> None:
        self.sec = SecEdgarAdapter()

    def fetch_recent_documents(self, brief: ResearchBrief, limit: int = 3) -> list[FilingDocument]:
        filings = self.sec.fetch_recent_filings(brief.company_name, ticker=brief.instrument.symbol, limit=limit)
        return [
            FilingDocument(
                provider="sec",
                filing_type=item.form,
                title=item.title,
                filed_at=item.filed_at,
                url=item.url,
                text=item.text,
            )
            for item in filings
        ]


def filing_agent_definition() -> AgentDefinition:
    a_share_provider = AShareDisclosureProvider()
    sec_registry = SecProviderRegistry()
    return AgentDefinition(
        agent_name="filing",
        description="Extract financial statement data, calculate core metrics, detect financial risk flags, and return structured financial diagnosis.",
        enabled_capabilities=[
            "discover_documents",
            "parse_financial_statements",
            "calculate_key_metrics",
            "detect_financial_flags",
            "build_structured_output",
        ],
        tool_registry={
            "discover_documents": ToolDefinition(
                name="discover_documents",
                description="Discover latest annual/interim disclosure documents from the active market provider.",
                handler=lambda brief, shared, scratchpad: _discover_documents(a_share_provider, sec_registry, brief),
            ),
            "parse_financial_statements": ToolDefinition(
                name="parse_financial_statements",
                description="Parse core income statement, balance sheet, and cash flow statement fields from filings.",
                handler=_parse_financial_statements,
            ),
            "calculate_key_metrics": ToolDefinition(
                name="calculate_key_metrics",
                description="Calculate deterministic growth, margin, cash flow quality, and balance sheet metrics.",
                handler=_calculate_key_metrics,
            ),
            "detect_financial_flags": ToolDefinition(
                name="detect_financial_flags",
                description="Detect financial strengths and risk flags from calculated metrics.",
                handler=_detect_financial_flags,
            ),
            "build_structured_output": ToolDefinition(
                name="build_structured_output",
                description="Format the filing agent output for the main critic/output agent.",
                handler=_build_structured_output,
            ),
        },
        output_model=FinancialStatementAnalysis,
        finalize_handler=_finalize_filing_agent,
        timeout_seconds=get_settings().agent_timeout_seconds,
        max_steps=max(get_settings().agent_max_steps, 5),
    )


def _discover_documents(
    a_share_provider: AShareDisclosureProvider,
    sec_registry: SecProviderRegistry,
    brief: ResearchBrief,
) -> dict[str, Any]:
    if brief.market == "A_SHARE":
        documents = a_share_provider.fetch_recent_documents(brief, limit=get_settings().filing_max_documents)
    elif brief.market == "US":
        documents = sec_registry.fetch_recent_documents(brief, limit=get_settings().filing_max_documents)
    else:
        documents = []

    payload = [document.__dict__ for document in documents]
    return {
        "summary": f"Discovered {len(documents)} recent disclosure documents.",
        "payload": {"documents": payload},
    }


def _parse_financial_statements(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    raw_documents = scratchpad.get("payload", {}).get("documents") or []
    parsed_periods = [_parse_document_financials(brief, item) for item in raw_documents]
    parsed_periods = [item for item in parsed_periods if item]
    current_period = parsed_periods[0] if parsed_periods else _empty_period(brief.company_name)
    same_period_last_year = _select_same_period_last_year(current_period, parsed_periods[1:])
    previous_period = parsed_periods[1] if len(parsed_periods) > 1 else None
    evidence = _build_extraction_evidence(current_period)
    return {
        "summary": f"Parsed financial statement fields from {len(parsed_periods)} disclosure documents.",
        "payload": {
            "parsed_financial_periods": parsed_periods,
            "current_period": current_period,
            "same_period_last_year": same_period_last_year,
            "previous_period": previous_period,
        },
        "evidence": evidence,
    }


def _calculate_key_metrics(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    current = scratchpad.get("payload", {}).get("current_period") or _empty_period(brief.company_name)
    same_last_year = scratchpad.get("payload", {}).get("same_period_last_year")
    snapshot, current_values = _build_financial_snapshot(current)
    last_year_values = _flatten_period_values(same_last_year) if same_last_year else {}
    warnings: list[FinancialMetricWarning] = []

    metrics = FinancialKeyMetrics(
        revenue_yoy_growth=_growth_metric("revenue_yoy_growth", current_values.get("revenue"), last_year_values.get("revenue"), warnings),
        operating_income_yoy_growth=_growth_metric("operating_income_yoy_growth", current_values.get("operating_income"), last_year_values.get("operating_income"), warnings),
        net_income_yoy_growth=_growth_metric("net_income_yoy_growth", current_values.get("net_income"), last_year_values.get("net_income"), warnings),
        operating_cash_flow_yoy_growth=_growth_metric("operating_cash_flow_yoy_growth", current_values.get("operating_cash_flow"), last_year_values.get("operating_cash_flow"), warnings),
        accounts_receivable_yoy_growth=_growth_metric("accounts_receivable_yoy_growth", current_values.get("accounts_receivable"), last_year_values.get("accounts_receivable"), warnings),
        inventory_yoy_growth=_growth_metric("inventory_yoy_growth", current_values.get("inventory"), last_year_values.get("inventory"), warnings),
        gross_margin=_safe_divide_metric("gross_margin", current_values.get("gross_profit"), current_values.get("revenue"), warnings),
        operating_margin=_safe_divide_metric("operating_margin", current_values.get("operating_income"), current_values.get("revenue"), warnings),
        net_margin=_safe_divide_metric("net_margin", current_values.get("net_income"), current_values.get("revenue"), warnings),
        ocf_to_net_income=_safe_divide_metric("ocf_to_net_income", current_values.get("operating_cash_flow"), current_values.get("net_income"), warnings),
        fcf_margin=_safe_divide_metric("fcf_margin", snapshot.free_cash_flow, current_values.get("revenue"), warnings),
        debt_to_equity=_safe_divide_metric("debt_to_equity", current_values.get("total_debt"), current_values.get("shareholders_equity"), warnings),
        cash_to_debt=_safe_divide_metric("cash_to_debt", current_values.get("cash_and_equivalents"), current_values.get("total_debt"), warnings, zero_warning="no_reported_debt_or_debt_missing"),
    )
    previous_operating_margin = _safe_divide(last_year_values.get("operating_income"), last_year_values.get("revenue"))
    if metrics.operating_margin is not None and previous_operating_margin is not None:
        metrics = metrics.model_copy(update={"operating_margin_change": round(metrics.operating_margin - previous_operating_margin, 6)})

    return {
        "summary": "Calculated key financial metrics from extracted statement data.",
        "payload": {
            "financial_snapshot": snapshot.model_dump(),
            "key_metrics": metrics.model_dump(),
            "metric_warnings": [item.model_dump() for item in warnings],
        },
        "evidence": _build_metric_evidence(current, snapshot, metrics),
    }


def _detect_financial_flags(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    snapshot = FinancialSnapshot.model_validate(scratchpad.get("payload", {}).get("financial_snapshot") or {})
    metrics = FinancialKeyMetrics.model_validate(scratchpad.get("payload", {}).get("key_metrics") or {})
    risks = _detect_risks(snapshot, metrics)
    strengths = _detect_strengths(snapshot, metrics)
    return {
        "summary": f"Detected {len(strengths)} financial strengths and {len(risks)} financial risk flags.",
        "payload": {
            "financial_strengths": [item.model_dump() for item in strengths],
            "financial_risks": [item.model_dump() for item in risks],
        },
        "evidence": _build_risk_evidence(brief, risks),
    }


def _build_structured_output(
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    scratchpad: dict[str, Any],
) -> dict[str, Any]:
    payload = scratchpad.get("payload", {}) or {}
    current = payload.get("current_period") or _empty_period(brief.company_name)
    documents = payload.get("documents") or []
    snapshot = FinancialSnapshot.model_validate(payload.get("financial_snapshot") or {})
    metrics = FinancialKeyMetrics.model_validate(payload.get("key_metrics") or {})
    risks = [FinancialSignal.model_validate(item) for item in payload.get("financial_risks") or []]
    strengths = [FinancialSignal.model_validate(item) for item in payload.get("financial_strengths") or []]
    warnings = [FinancialMetricWarning.model_validate(item) for item in payload.get("metric_warnings") or []]
    data_quality = _build_data_quality(snapshot, warnings)
    score = _build_financial_score(metrics, risks)
    assessment = _build_financial_assessment(data_quality, score, strengths, risks)
    analysis = FinancialStatementAnalysis(
        company=brief.company_name,
        period=current.get("period"),
        currency=current.get("currency"),
        unit=current.get("unit"),
        data_quality=data_quality,
        financial_snapshot=snapshot,
        key_metrics=metrics,
        metric_warnings=warnings,
        strengths=strengths,
        risks=risks,
        overall_financial_assessment=assessment,
        questions_for_main_agent=_questions_for_main_agent(risks, metrics),
        financial_score=score,
    )
    signal_bias = _signal_bias_from_analysis(analysis)
    structured_facts = _compat_structured_facts(brief, current, snapshot, analysis, documents)
    return {
        "summary": "Built structured financial statement analysis for the main agent.",
        "payload": {
            "financial_statement_analysis": analysis.model_dump(),
            "structured_facts": structured_facts,
            "memo_insights": {
                "summary": assessment.summary,
                "takeaways": _key_points_from_analysis(analysis),
                "signal_bias": signal_bias,
            },
            "signal_bias": signal_bias,
        },
    }


def _finalize_filing_agent(
    brief: ResearchBrief,
    scratchpad: dict[str, Any],
    observations: list[Any],
) -> AgentResult:
    payload = dict(scratchpad.get("payload") or {})
    documents = payload.get("documents") or []
    analysis_payload = payload.get("financial_statement_analysis")
    analysis = FinancialStatementAnalysis.model_validate(analysis_payload) if analysis_payload else None
    status = "success" if analysis and analysis.data_quality.status == "success" else "partial"
    reason = None if documents else "No disclosure documents were found for the target."
    warning = None
    if analysis and analysis.data_quality.status == "partial":
        warning = "Financial statement extraction is partial; missing fields or unavailable comparisons limit confidence."
    if scratchpad.get("errors"):
        status = "partial"
        error_warning = " | ".join(str(item) for item in scratchpad["errors"][:2])
        warning = f"{warning + ' ' if warning else ''}Capability fallback triggered: {error_warning}"

    key_points = _key_points_from_analysis(analysis) if analysis else []
    if not key_points and documents:
        key_points = [f"已获取 {len(documents)} 份近期披露文件，但财务字段抽取较弱。"]

    provider = documents[0]["provider"] if documents else None
    output_payload = {
        "provider": provider,
        "documents": documents,
        "financial_statement_analysis": analysis.model_dump() if analysis else None,
        "structured_facts": payload.get("structured_facts") or {},
        "memo_insights": payload.get("memo_insights") or {},
        "signal_bias": payload.get("signal_bias", "neutral"),
    }
    return AgentResult(
        agent_name="filing",
        applicable=brief.market in {"A_SHARE", "US"},
        status=status,
        summary=(analysis.overall_financial_assessment.summary if analysis else "Filing Agent completed with limited financial statement signal."),
        key_points=key_points,
        metrics={
            "provider": provider,
            "financial_score": analysis.financial_score.model_dump() if analysis else None,
            "data_quality": analysis.data_quality.model_dump() if analysis else None,
        },
        payload=output_payload,
        evidence=[EvidenceItem.model_validate(item) for item in scratchpad.get("evidence", [])],
        warning=warning,
        reason=reason,
        observations=observations,
    )


def _empty_period(company_name: str) -> dict[str, Any]:
    return {
        "company": company_name,
        "period": None,
        "currency": None,
        "unit": None,
        "document": {},
        "income_statement": {},
        "balance_sheet": {},
        "cash_flow_statement": {},
        "field_sources": {},
    }


def _parse_document_financials(brief: ResearchBrief, document: dict[str, Any]) -> dict[str, Any]:
    text = normalize_whitespace(str(document.get("text") or ""))
    period = _infer_period(str(document.get("title") or ""), document.get("filed_at"), str(document.get("filing_type") or ""))
    parsed = _empty_period(brief.company_name)
    parsed.update(
        {
            "period": period,
            "currency": _detect_currency(text),
            "unit": _detect_unit(text),
            "document": {
                "title": document.get("title"),
                "filed_at": document.get("filed_at"),
                "url": document.get("url"),
                "provider": document.get("provider"),
                "filing_type": document.get("filing_type"),
            },
        }
    )
    field_sources: dict[str, dict[str, Any]] = {}
    for field in [*INCOME_FIELDS, *BALANCE_FIELDS, *CASH_FLOW_FIELDS]:
        value, snippet = _extract_field_value(text, field)
        if value is None:
            continue
        statement_key = _statement_key(field)
        parsed[statement_key][field] = value
        field_sources[field] = {
            "value": value,
            "snippet": snippet,
            "title": document.get("title"),
            "date": document.get("filed_at"),
            "url": document.get("url"),
            "provider": document.get("provider"),
            "filing_type": document.get("filing_type"),
        }
    parsed["field_sources"] = field_sources
    return parsed


def _extract_field_value(text: str, field: str) -> tuple[float | None, str | None]:
    aliases = FIELD_ALIASES[field]
    lowered = text.lower()
    for alias in aliases:
        lowered_alias = alias.lower()
        index = lowered.find(lowered_alias)
        if index < 0:
            continue
        window = text[index : index + 260]
        value = _first_number_after_alias(window, alias)
        if value is not None:
            return value, truncate_text(window, 240)
    return None, None


def _first_number_after_alias(window: str, alias: str) -> float | None:
    alias_index = window.lower().find(alias.lower())
    if alias_index >= 0:
        window = window[alias_index + len(alias) :]
    for match in NUMBER_PATTERN.finditer(window):
        raw = match.group(0)
        if _looks_like_year(raw):
            continue
        value = _parse_number(raw)
        if value is not None:
            return value
    return None


def _parse_number(raw: str) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"(US\$|USD|CNY|RMB|[$¥￥])", "", text, flags=re.IGNORECASE).strip()
    text = text.replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _looks_like_year(raw: str) -> bool:
    cleaned = re.sub(r"\D", "", raw)
    return len(cleaned) == 4 and cleaned.startswith(("19", "20"))


def _statement_key(field: str) -> str:
    if field in INCOME_FIELDS:
        return "income_statement"
    if field in BALANCE_FIELDS:
        return "balance_sheet"
    return "cash_flow_statement"


def _detect_currency(text: str) -> str | None:
    lowered = text.lower()
    if any(token in lowered for token in ["usd", "us$", "$"]):
        return "USD"
    if any(token in text for token in ["人民币", "元", "¥", "￥"]) or "rmb" in lowered or "cny" in lowered:
        return "CNY"
    return None


def _detect_unit(text: str) -> str | None:
    lowered = text.lower()
    if "单位：万元" in text or "单位:万元" in text:
        return "ten_thousand_cny"
    if "单位：亿元" in text or "单位:亿元" in text:
        return "hundred_million_cny"
    if "单位：百万元" in text or "单位:百万元" in text or "rmb million" in lowered or "人民币百万元" in text:
        return "million_cny"
    if "in millions" in lowered or "millions of" in lowered:
        return "millions"
    if "in thousands" in lowered or "thousands of" in lowered:
        return "thousands"
    return None


def _infer_period(title: str, filed_at: str | None, filing_type: str) -> str | None:
    year_match = re.search(r"(20\d{2}|19\d{2})", title)
    year = year_match.group(1) if year_match else None
    if not year and filed_at:
        try:
            filed_year = int(str(filed_at)[:4])
            year = str(filed_year - 1 if filing_type in {"年报", "10-K", "20-F", "40-F"} else filed_year)
        except Exception:
            year = None
    if not year:
        return filed_at
    if filing_type in {"年报", "10-K", "20-F", "40-F"} or "annual" in title.lower():
        return f"{year}FY"
    if filing_type == "一季报" or "q1" in title.lower():
        return f"{year}Q1"
    if filing_type in {"半年报", "10-Q"} and ("半年" in title or "quarter" not in title.lower()):
        return f"{year}H1"
    if filing_type == "三季报" or "q3" in title.lower():
        return f"{year}Q3"
    return year


def _select_same_period_last_year(current_period: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    current = str(current_period.get("period") or "")
    current_year_match = re.search(r"(20\d{2}|19\d{2})", current)
    suffix = re.sub(r"^(20\d{2}|19\d{2})", "", current)
    if current_year_match:
        target = f"{int(current_year_match.group(1)) - 1}{suffix}"
        for item in candidates:
            if item.get("period") == target:
                return item
    current_type = (current_period.get("document") or {}).get("filing_type")
    for item in candidates:
        if (item.get("document") or {}).get("filing_type") == current_type:
            return item
    return candidates[0] if candidates else None


def _flatten_period_values(period: dict[str, Any] | None) -> dict[str, float | None]:
    if not period:
        return {}
    values: dict[str, float | None] = {}
    for statement in ("income_statement", "balance_sheet", "cash_flow_statement"):
        values.update(period.get(statement) or {})
    return values


def _build_financial_snapshot(period: dict[str, Any]) -> tuple[FinancialSnapshot, dict[str, float | None]]:
    values = _flatten_period_values(period)
    capex_raw = values.get("capital_expenditure")
    capex_spend = abs(capex_raw) if capex_raw is not None else None
    free_cash_flow = None
    if values.get("operating_cash_flow") is not None and capex_spend is not None:
        free_cash_flow = values["operating_cash_flow"] - capex_spend
    snapshot = FinancialSnapshot(
        revenue=values.get("revenue"),
        gross_profit=values.get("gross_profit"),
        operating_income=values.get("operating_income"),
        net_income=values.get("net_income"),
        eps=values.get("eps"),
        cash_and_equivalents=values.get("cash_and_equivalents"),
        accounts_receivable=values.get("accounts_receivable"),
        inventory=values.get("inventory"),
        total_assets=values.get("total_assets"),
        total_debt=values.get("total_debt"),
        total_liabilities=values.get("total_liabilities"),
        shareholders_equity=values.get("shareholders_equity"),
        operating_cash_flow=values.get("operating_cash_flow"),
        capital_expenditure=capex_spend,
        free_cash_flow=free_cash_flow,
    )
    values["capital_expenditure"] = capex_spend
    values["free_cash_flow"] = free_cash_flow
    return snapshot, values


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def _safe_divide_metric(
    metric: str,
    numerator: float | None,
    denominator: float | None,
    warnings: list[FinancialMetricWarning],
    *,
    zero_warning: str = "denominator_is_zero_or_missing",
) -> float | None:
    if numerator is None:
        warnings.append(FinancialMetricWarning(metric=metric, warning="numerator_is_missing"))
        return None
    if denominator is None:
        warnings.append(FinancialMetricWarning(metric=metric, warning="denominator_is_missing"))
        return None
    if denominator == 0:
        warnings.append(FinancialMetricWarning(metric=metric, warning=zero_warning))
        return None
    return round(numerator / denominator, 6)


def _growth_metric(
    metric: str,
    current: float | None,
    previous: float | None,
    warnings: list[FinancialMetricWarning],
) -> float | None:
    if current is None:
        warnings.append(FinancialMetricWarning(metric=metric, warning="current_period_value_is_missing"))
        return None
    if previous is None:
        warnings.append(FinancialMetricWarning(metric=metric, warning="prior_period_value_is_missing"))
        return None
    if previous == 0:
        warnings.append(FinancialMetricWarning(metric=metric, warning="previous_period_value_is_zero"))
        return None
    if previous < 0:
        warnings.append(FinancialMetricWarning(metric=metric, warning="prior_period_value_is_negative_growth_rate_less_reliable"))
    return round((current - previous) / abs(previous), 6)


def _detect_risks(snapshot: FinancialSnapshot, metrics: FinancialKeyMetrics) -> list[FinancialSignal]:
    risks: list[FinancialSignal] = []
    if _gt(metrics.revenue_yoy_growth, 0) and _lt(metrics.operating_margin_change, -0.02):
        risks.append(
            FinancialSignal(
                type="revenue_growth_with_margin_pressure",
                summary="收入增长但经营利润率下降，增长质量可能受到成本压力、降价竞争或费用上升影响。",
                severity="medium",
                evidence={
                    "revenue_yoy_growth": metrics.revenue_yoy_growth,
                    "operating_margin_change": metrics.operating_margin_change,
                },
                confidence=0.85,
            )
        )
    if _gt(metrics.net_income_yoy_growth, 0) and _lt(metrics.operating_cash_flow_yoy_growth, 0):
        risks.append(
            FinancialSignal(
                type="profit_growth_not_supported_by_cash_flow",
                summary="净利润增长没有被经营现金流增长支持，盈利质量可能下降。",
                severity="high",
                evidence={
                    "net_income_yoy_growth": metrics.net_income_yoy_growth,
                    "operating_cash_flow_yoy_growth": metrics.operating_cash_flow_yoy_growth,
                },
                confidence=0.9,
            )
        )
    if _spread_gt(metrics.accounts_receivable_yoy_growth, metrics.revenue_yoy_growth, 0.10):
        risks.append(
            FinancialSignal(
                type="receivables_growing_faster_than_revenue",
                summary="应收账款增速明显高于收入增速，回款速度和收入质量需要进一步核验。",
                severity="medium",
                evidence={
                    "accounts_receivable_yoy_growth": metrics.accounts_receivable_yoy_growth,
                    "revenue_yoy_growth": metrics.revenue_yoy_growth,
                },
                confidence=0.82,
            )
        )
    if _spread_gt(metrics.inventory_yoy_growth, metrics.revenue_yoy_growth, 0.10):
        risks.append(
            FinancialSignal(
                type="inventory_growing_faster_than_revenue",
                summary="存货增速明显高于收入增速，可能存在库存积压、需求放缓或未来减值风险。",
                severity="medium",
                evidence={
                    "inventory_yoy_growth": metrics.inventory_yoy_growth,
                    "revenue_yoy_growth": metrics.revenue_yoy_growth,
                },
                confidence=0.82,
            )
        )
    if snapshot.free_cash_flow is not None and snapshot.free_cash_flow < 0:
        risks.append(
            FinancialSignal(
                type="negative_free_cash_flow",
                summary="自由现金流为负，经营现金流不足以覆盖资本开支。",
                severity="medium",
                evidence={
                    "operating_cash_flow": snapshot.operating_cash_flow,
                    "capital_expenditure": snapshot.capital_expenditure,
                    "free_cash_flow": snapshot.free_cash_flow,
                },
                confidence=0.86,
            )
        )
    if metrics.cash_to_debt is not None and metrics.cash_to_debt < 0.3:
        risks.append(
            FinancialSignal(
                type="weak_cash_debt_coverage",
                summary="现金对债务覆盖较弱，可能存在偿债压力。",
                severity="high",
                evidence={
                    "cash_to_debt": metrics.cash_to_debt,
                    "cash": snapshot.cash_and_equivalents,
                    "total_debt": snapshot.total_debt,
                },
                confidence=0.88,
            )
        )
    return risks


def _detect_strengths(snapshot: FinancialSnapshot, metrics: FinancialKeyMetrics) -> list[FinancialSignal]:
    strengths: list[FinancialSignal] = []
    if _gt(metrics.revenue_yoy_growth, 0.1) and (metrics.operating_margin_change is None or metrics.operating_margin_change >= 0):
        strengths.append(
            FinancialSignal(
                type="revenue_growth",
                summary="收入实现较好增长，且未观察到明显经营利润率压缩。",
                severity="low",
                evidence={"revenue_yoy_growth": metrics.revenue_yoy_growth, "operating_margin_change": metrics.operating_margin_change},
                confidence=0.78,
            )
        )
    if metrics.ocf_to_net_income is not None and metrics.ocf_to_net_income > 1:
        strengths.append(
            FinancialSignal(
                type="cash_flow_quality",
                summary="经营现金流超过净利润，盈利现金含量较好。",
                severity="low",
                evidence={
                    "operating_cash_flow": snapshot.operating_cash_flow,
                    "net_income": snapshot.net_income,
                    "ocf_to_net_income": metrics.ocf_to_net_income,
                },
                confidence=0.9,
            )
        )
    if metrics.cash_to_debt is not None and metrics.cash_to_debt >= 1:
        strengths.append(
            FinancialSignal(
                type="cash_debt_coverage",
                summary="现金能够较好覆盖有息债务，短期偿债弹性较强。",
                severity="low",
                evidence={"cash_to_debt": metrics.cash_to_debt},
                confidence=0.82,
            )
        )
    return strengths


def _build_data_quality(snapshot: FinancialSnapshot, warnings: list[FinancialMetricWarning]) -> FinancialDataQuality:
    payload = snapshot.model_dump()
    missing_fields = [field for field in FINANCIAL_SNAPSHOT_FIELDS if payload.get(field) is None]
    present_required = len(FINANCIAL_SNAPSHOT_FIELDS) - len(missing_fields)
    confidence = min(0.95, max(0.15, present_required / len(FINANCIAL_SNAPSHOT_FIELDS)))
    warning_penalty = min(0.25, len(warnings) * 0.015)
    confidence = round(max(0.0, confidence - warning_penalty), 2)
    status = "success" if confidence >= 0.6 and not {"revenue", "net_income", "operating_cash_flow"} & set(missing_fields) else "partial"
    return FinancialDataQuality(status=status, missing_fields=missing_fields, confidence=confidence)


def _build_financial_score(metrics: FinancialKeyMetrics, risks: list[FinancialSignal]) -> FinancialScore:
    growth = _score_growth(metrics)
    profitability = _score_profitability(metrics)
    cash_flow_quality = _score_cash_flow(metrics)
    balance_sheet = _score_balance_sheet(metrics, risks)
    overall = round((growth + profitability + cash_flow_quality + balance_sheet) / 4)
    return FinancialScore(
        growth=growth,
        profitability=profitability,
        cash_flow_quality=cash_flow_quality,
        balance_sheet=balance_sheet,
        overall=max(1, min(5, overall)),
    )


def _build_financial_assessment(
    data_quality: FinancialDataQuality,
    score: FinancialScore,
    strengths: list[FinancialSignal],
    risks: list[FinancialSignal],
) -> FinancialAssessment:
    high_risks = [item for item in risks if item.severity == "high"]
    main_positive = strengths[0].summary if strengths else "未提取到明确财务亮点。"
    main_negative = high_risks[0].summary if high_risks else (risks[0].summary if risks else "未识别到明确财务风险 flag。")
    if score.overall >= 4 and not high_risks:
        rating = "moderately_positive"
    elif score.overall <= 2 or high_risks:
        rating = "moderately_negative"
    else:
        rating = "neutral"
    summary = (
        f"财报子 Agent 对财务健康度的评分为 {score.overall}/5。"
        f"{main_positive} {main_negative}"
    )
    if data_quality.status == "partial":
        summary += " 由于部分核心字段或历史同期数据缺失，该判断应保守使用。"
    return FinancialAssessment(
        rating=rating,
        summary=truncate_text(summary, 520),
        main_positive=main_positive,
        main_negative=main_negative,
        confidence=data_quality.confidence,
    )


def _questions_for_main_agent(risks: list[FinancialSignal], metrics: FinancialKeyMetrics) -> list[str]:
    questions = []
    risk_types = {item.type for item in risks}
    if "revenue_growth_with_margin_pressure" in risk_types:
        questions.append("利润率下降是由产品结构、原材料成本、竞争降价，还是一次性费用导致？")
    if "profit_growth_not_supported_by_cash_flow" in risk_types:
        questions.append("净利润增长未被经营现金流支持，是否与回款周期、收入确认或营运资本变化有关？")
    if "receivables_growing_faster_than_revenue" in risk_types:
        questions.append("应收账款增速高于收入增速是否属于行业账期变化，还是客户回款质量下降？")
    if "inventory_growing_faster_than_revenue" in risk_types:
        questions.append("存货增长是否对应真实订单和扩产周期，还是需求放缓或减值压力？")
    if "negative_free_cash_flow" in risk_types:
        questions.append("负自由现金流是否来自成长性资本开支，还是经营现金创造能力不足？")
    if "weak_cash_debt_coverage" in risk_types:
        questions.append("现金债务覆盖较弱时，公司是否有稳定融资渠道或短债滚续压力？")
    if not questions and metrics.operating_margin_change is not None:
        questions.append("财务趋势是否与同行利润率、行业景气度和公司产品结构变化一致？")
    return questions[:6]


def _signal_bias_from_analysis(analysis: FinancialStatementAnalysis) -> str:
    high_risks = len([item for item in analysis.risks if item.severity == "high"])
    if high_risks or analysis.financial_score.overall <= 2:
        return "negative"
    if analysis.strengths and analysis.financial_score.overall >= 4:
        return "positive"
    return "neutral"


def _compat_structured_facts(
    brief: ResearchBrief,
    current: dict[str, Any],
    snapshot: FinancialSnapshot,
    analysis: FinancialStatementAnalysis,
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "company": brief.company_name,
        "ticker": brief.instrument.symbol,
        "filing_type": (current.get("document") or {}).get("filing_type") or "",
        "fiscal_period": current.get("period"),
        "filed_at": (current.get("document") or {}).get("filed_at") or "",
        "revenue": snapshot.revenue,
        "operating_income": snapshot.operating_income,
        "net_income": snapshot.net_income,
        "eps": snapshot.eps,
        "operating_cash_flow": snapshot.operating_cash_flow,
        "free_cash_flow": snapshot.free_cash_flow,
        "capex": snapshot.capital_expenditure,
        "key_risks": [item.summary for item in analysis.risks],
        "supporting_filings": [
            {
                "title": item.get("title"),
                "filed_at": item.get("filed_at"),
                "url": item.get("url"),
                "provider": item.get("provider"),
                "filing_type": item.get("filing_type"),
            }
            for item in documents
        ],
    }


def _key_points_from_analysis(analysis: FinancialStatementAnalysis | None) -> list[str]:
    if not analysis:
        return []
    points = []
    metrics = analysis.key_metrics
    snapshot = analysis.financial_snapshot
    if metrics.revenue_yoy_growth is not None:
        points.append(f"收入同比增速 {metrics.revenue_yoy_growth:.1%}")
    if metrics.net_income_yoy_growth is not None:
        points.append(f"净利润同比增速 {metrics.net_income_yoy_growth:.1%}")
    if metrics.ocf_to_net_income is not None:
        points.append(f"经营现金流/净利润 {metrics.ocf_to_net_income:.2f}")
    if snapshot.free_cash_flow is not None:
        points.append(f"自由现金流 {snapshot.free_cash_flow}")
    points.extend(item.summary for item in analysis.strengths[:2])
    points.extend(item.summary for item in analysis.risks[:3])
    return list(dict.fromkeys(points))[:6]


def _build_extraction_evidence(period: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = []
    for field, source in (period.get("field_sources") or {}).items():
        evidence.append(
            EvidenceItem(
                agent_name="filing",
                source_type="disclosure_document",
                category="financial_statement_extract",
                title=str(source.get("title") or f"Financial statement field: {field}"),
                date=source.get("date"),
                url=source.get("url"),
                snippet=truncate_text(f"{field}: {source.get('value')} | {source.get('snippet')}", 320),
                metadata={"field": field, "provider": source.get("provider"), "filing_type": source.get("filing_type")},
            ).model_dump()
        )
    return evidence[: get_settings().filing_evidence_limit]


def _build_metric_evidence(
    period: dict[str, Any],
    snapshot: FinancialSnapshot,
    metrics: FinancialKeyMetrics,
) -> list[dict[str, Any]]:
    document = period.get("document") or {}
    snippets = []
    if metrics.revenue_yoy_growth is not None:
        snippets.append(f"revenue_yoy_growth={metrics.revenue_yoy_growth:.4f}")
    if metrics.operating_margin is not None:
        snippets.append(f"operating_margin={metrics.operating_margin:.4f}")
    if metrics.ocf_to_net_income is not None:
        snippets.append(f"ocf_to_net_income={metrics.ocf_to_net_income:.4f}")
    if snapshot.free_cash_flow is not None:
        snippets.append(f"free_cash_flow={snapshot.free_cash_flow}")
    if not snippets:
        return []
    return [
        EvidenceItem(
            agent_name="filing",
            source_type="disclosure_document",
            category="financial_metric",
            title=str(document.get("title") or "Calculated financial metrics"),
            date=document.get("filed_at"),
            url=document.get("url"),
            snippet=truncate_text("; ".join(snippets), 320),
            metadata={"period": period.get("period"), "provider": document.get("provider")},
        ).model_dump()
    ]


def _build_risk_evidence(brief: ResearchBrief, risks: list[FinancialSignal]) -> list[dict[str, Any]]:
    return [
        EvidenceItem(
            agent_name="filing",
            source_type="disclosure_document",
            category="financial_risk_flag",
            title=f"{brief.company_name} financial risk: {risk.type}",
            date=None,
            url=None,
            snippet=truncate_text(f"{risk.summary} Evidence: {risk.evidence}", 320),
            metadata={"flag": risk.type, "severity": risk.severity},
        ).model_dump()
        for risk in risks[: get_settings().filing_evidence_limit]
    ]


def _score_growth(metrics: FinancialKeyMetrics) -> int:
    values = [metrics.revenue_yoy_growth, metrics.operating_income_yoy_growth, metrics.net_income_yoy_growth]
    present = [value for value in values if value is not None]
    if not present:
        return 3
    average = sum(present) / len(present)
    if average > 0.2:
        return 5
    if average > 0.05:
        return 4
    if average < -0.15:
        return 1
    if average < 0:
        return 2
    return 3


def _score_profitability(metrics: FinancialKeyMetrics) -> int:
    if metrics.net_margin is None and metrics.operating_margin is None:
        return 3
    margin = metrics.net_margin if metrics.net_margin is not None else metrics.operating_margin
    if margin is not None and margin > 0.2:
        return 5
    if margin is not None and margin > 0.08:
        return 4
    if margin is not None and margin < 0:
        return 1
    if margin is not None and margin < 0.03:
        return 2
    return 3


def _score_cash_flow(metrics: FinancialKeyMetrics) -> int:
    if metrics.ocf_to_net_income is None:
        return 3
    if metrics.ocf_to_net_income > 1.2:
        return 5
    if metrics.ocf_to_net_income > 1:
        return 4
    if metrics.ocf_to_net_income < 0:
        return 1
    if metrics.ocf_to_net_income < 0.5:
        return 2
    return 3


def _score_balance_sheet(metrics: FinancialKeyMetrics, risks: list[FinancialSignal]) -> int:
    if any(item.type == "weak_cash_debt_coverage" for item in risks):
        return 2
    if metrics.cash_to_debt is not None and metrics.cash_to_debt >= 1:
        return 5
    if metrics.debt_to_equity is not None and metrics.debt_to_equity < 0.8:
        return 4
    if metrics.debt_to_equity is not None and metrics.debt_to_equity > 2:
        return 2
    return 3


def _gt(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _lt(value: float | None, threshold: float) -> bool:
    return value is not None and value < threshold


def _spread_gt(left: float | None, right: float | None, threshold: float) -> bool:
    return left is not None and right is not None and left - right > threshold


def _extract_document_text(url: str) -> str:
    try:
        response = requests.get(url, headers=build_headers(), timeout=get_settings().request_timeout)
        response.raise_for_status()
    except Exception:
        logger.exception("Failed to download disclosure document: %s", url)
        return ""

    lower_url = url.lower()
    if lower_url.endswith(".pdf") and PdfReader is not None:
        try:
            reader = PdfReader(BytesIO(response.content))
            pages = []
            for page in reader.pages[:20]:
                pages.append(page.extract_text() or "")
            return normalize_whitespace("\n".join(pages))
        except Exception:
            logger.exception("Failed to parse PDF disclosure document: %s", url)
            return ""
    try:
        return normalize_whitespace(response.text)
    except Exception:
        return ""


def _infer_filing_type(title: str) -> str:
    for filing_type in ["年报", "半年报", "一季报", "三季报"]:
        if filing_type in title:
            return filing_type
    return "公告"


def _extract_interesting_sentences(text: str) -> str:
    if not text:
        return ""
    separators = re.split(r"[。；;\n]", text)
    picked = []
    for sentence in separators:
        candidate = normalize_whitespace(sentence)
        if not candidate:
            continue
        if any(keyword in candidate for keyword in ["营业收入", "归属于上市公司股东", "净利润", "现金流", "风险", "产能", "渠道", "需求"]):
            picked.append(candidate)
        if len(picked) >= 8:
            break
    if not picked:
        return truncate_text(text, 600)
    return "。".join(picked)


def _millis_to_iso(value: Any) -> str | None:
    try:
        millis = int(value)
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).date().isoformat()
    except Exception:
        return None


def _cninfo_category(category: str) -> str:
    mapping = {
        "年报": "category_ndbg_szsh;",
        "半年报": "category_bndbg_szsh;",
        "一季报": "category_yjdbg_szsh;",
        "三季报": "category_sjdbg_szsh;",
    }
    return mapping.get(category, "")
