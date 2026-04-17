from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from app.schemas import AgentObservation, AgentResult, ResearchBrief

ToolHandler = Callable[[ResearchBrief, dict[str, Any], dict[str, Any]], dict[str, Any]]
PlanHandler = Callable[[ResearchBrief, dict[str, Any]], list[str]]
FinalizeHandler = Callable[[ResearchBrief, dict[str, Any], list[AgentObservation]], AgentResult]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    handler: ToolHandler
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class AgentDefinition:
    agent_name: str
    description: str
    enabled_capabilities: list[str]
    tool_registry: dict[str, ToolDefinition]
    output_model: type[BaseModel]
    finalize_handler: FinalizeHandler
    max_steps: int = 4
    timeout_seconds: int = 45
    plan_handler: PlanHandler | None = None
    tags: list[str] = field(default_factory=list)
