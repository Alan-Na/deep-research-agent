from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import timezone
from typing import Any, Callable

from app.agents.base import AgentDefinition
from app.config import get_settings
from app.schemas import AgentObservation, AgentResult, ResearchBrief
from app.utils.logging import get_logger
from app.utils.time import utc_now

logger = get_logger(__name__)


def execute_react_agent(
    definition: AgentDefinition,
    brief: ResearchBrief,
    shared_context: dict[str, Any],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> AgentResult:
    settings = get_settings()
    started_at = utc_now()
    observations: list[AgentObservation] = []
    scratchpad: dict[str, Any] = {
        "observations": [],
        "events": [],
        "evidence": [],
        "metrics": {},
        "payload": {},
        "errors": [],
    }
    max_steps = min(definition.max_steps, settings.agent_max_steps)
    planned = (
        definition.plan_handler(brief, shared_context)
        if definition.plan_handler
        else list(definition.enabled_capabilities)
    )
    capabilities = [name for name in planned if name in definition.tool_registry][:max_steps]
    if progress_callback:
        progress_callback(
            {
                "type": "agent_started",
                "agent_name": definition.agent_name,
                "status": "running",
                "timestamp": started_at.isoformat(),
            }
        )

    try:
        for step_index, capability_name in enumerate(capabilities, start=1):
            tool = definition.tool_registry[capability_name]
            step_label = f"step_{step_index}:{capability_name}"
            if progress_callback:
                progress_callback(
                    {
                        "type": "tool_called",
                        "agent_name": definition.agent_name,
                        "capability": capability_name,
                        "current_step": step_label,
                        "tool_calls_count": step_index,
                        "timestamp": utc_now().isoformat(),
                    }
                )

            try:
                observation_payload = _run_with_timeout(
                    tool.handler,
                    args=(brief, shared_context, scratchpad),
                    timeout_seconds=tool.timeout_seconds or definition.timeout_seconds or settings.agent_timeout_seconds,
                )
            except Exception as exc:
                observation_payload = {
                    "summary": f"{capability_name} failed: {exc}",
                    "error": str(exc),
                }
                scratchpad["errors"].append(f"{capability_name}: {exc}")
            observation = AgentObservation(
                capability=capability_name,
                summary=str(observation_payload.get("summary") or f"{capability_name} completed."),
                payload={key: value for key, value in observation_payload.items() if key != "summary"},
            )
            observations.append(observation)
            scratchpad["observations"].append(observation.model_dump())
            if isinstance(observation_payload.get("events"), list):
                scratchpad["events"].extend(observation_payload["events"])
            if isinstance(observation_payload.get("evidence"), list):
                scratchpad["evidence"].extend(observation_payload["evidence"])
            if isinstance(observation_payload.get("metrics"), dict):
                scratchpad["metrics"].update(observation_payload["metrics"])
            if isinstance(observation_payload.get("payload"), dict):
                scratchpad["payload"].update(observation_payload["payload"])

            if progress_callback:
                progress_callback(
                    {
                        "type": "observation_recorded",
                        "agent_name": definition.agent_name,
                        "capability": capability_name,
                        "current_step": step_label,
                        "tool_calls_count": step_index,
                        "summary": observation.summary,
                        "timestamp": utc_now().isoformat(),
                    }
                )

        result = definition.finalize_handler(brief, scratchpad, observations)
        finished_at = utc_now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        finalized = result.model_copy(
            update={
                "agent_name": definition.agent_name,
                "current_step": "finalized",
                "tool_calls_count": len(observations),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_ms": duration_ms,
                "capabilities_used": [item.capability for item in observations],
                "observations": observations,
            }
        )
        if progress_callback:
            progress_callback(
                {
                    "type": "agent_completed",
                    "agent_name": definition.agent_name,
                    "status": finalized.status,
                    "summary": finalized.summary,
                    "warning": finalized.warning,
                    "current_step": finalized.current_step,
                    "tool_calls_count": finalized.tool_calls_count,
                    "started_at": finalized.started_at,
                    "finished_at": finalized.finished_at,
                    "duration_ms": finalized.duration_ms,
                    "timestamp": finished_at.isoformat(),
                }
            )
        return finalized
    except Exception as exc:
        logger.exception("Agent %s failed.", definition.agent_name)
        finished_at = utc_now()
        failed = AgentResult(
            agent_name=definition.agent_name,
            applicable=True,
            status="failed",
            summary=f"{definition.agent_name} failed during execution.",
            error=str(exc),
            reason="Unexpected agent exception.",
            tool_calls_count=len(observations),
            current_step="failed",
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
            observations=observations,
            capabilities_used=[item.capability for item in observations],
        )
        if progress_callback:
            progress_callback(
                {
                    "type": "agent_completed",
                    "agent_name": definition.agent_name,
                    "status": "failed",
                    "error": str(exc),
                    "current_step": "failed",
                    "tool_calls_count": len(observations),
                    "started_at": failed.started_at,
                    "finished_at": failed.finished_at,
                    "duration_ms": failed.duration_ms,
                    "timestamp": finished_at.isoformat(),
                }
            )
        return failed


def _run_with_timeout(
    handler: Callable[..., dict[str, Any]],
    *,
    args: tuple[Any, ...],
    timeout_seconds: int,
) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(handler, *args)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeout as exc:
            raise TimeoutError(f"Capability timed out after {timeout_seconds}s") from exc
