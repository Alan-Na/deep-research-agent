from __future__ import annotations

from app.agents.base import AgentDefinition
from app.agents.filing import filing_agent_definition
from app.agents.market import market_agent_definition
from app.agents.news_risk import news_risk_agent_definition
from app.agents.web_intel import web_intel_agent_definition


def get_research_agent_definitions() -> list[AgentDefinition]:
    return [
        market_agent_definition(),
        filing_agent_definition(),
        web_intel_agent_definition(),
        news_risk_agent_definition(),
    ]
