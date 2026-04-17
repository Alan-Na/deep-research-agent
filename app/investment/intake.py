from __future__ import annotations

import re

from app.agents.market import LocalMarketDataMcpTransport
from app.schemas import InstrumentInfo, ResearchBrief
from app.utils.text import normalize_name


def build_research_brief(company_name: str) -> ResearchBrief:
    transport = LocalMarketDataMcpTransport()
    normalized = normalize_name(company_name)
    looks_like_a_share = bool(re.search(r"\b\d{6}\b", company_name)) or any("\u4e00" <= char <= "\u9fff" for char in company_name)

    instrument = InstrumentInfo(display_name=company_name)
    market = "UNKNOWN"
    notes: list[str] = []

    if looks_like_a_share:
        try:
            instrument = transport.resolve_instrument(company_name, "A_SHARE")
        except Exception:
            instrument = InstrumentInfo(display_name=company_name, market="A_SHARE", notes=["A-share resolution failed."])
        market = instrument.market if instrument.symbol else "A_SHARE"
        if not instrument.symbol:
            notes.append("A-share resolution was weak; downstream agents may run partially.")
    else:
        try:
            a_share_candidate = transport.resolve_instrument(company_name, "A_SHARE")
        except Exception:
            a_share_candidate = InstrumentInfo(display_name=company_name, market="A_SHARE", notes=["A-share resolution failed."])
        if a_share_candidate.symbol:
            instrument = a_share_candidate
            market = "A_SHARE"
        else:
            try:
                us_candidate = transport.resolve_instrument(company_name, "US")
            except Exception:
                us_candidate = InstrumentInfo(display_name=company_name, market="US", notes=["US resolution failed."])
            instrument = us_candidate if us_candidate.symbol else InstrumentInfo(display_name=company_name)
            market = "US" if us_candidate.symbol else "UNKNOWN"
            if not instrument.symbol:
                notes.append("Primary listing could not be resolved from the input.")

    if normalized and normalized == normalize_name(instrument.display_name or ""):
        notes.append("Instrument identity aligned with the input query.")

    return ResearchBrief(
        company_name=company_name,
        market=market,  # type: ignore[arg-type]
        query=company_name,
        instrument=instrument,
        priority_agents=["market", "filing", "web_intel", "news_risk", "critic_output"],
        briefing_notes=notes,
    )
