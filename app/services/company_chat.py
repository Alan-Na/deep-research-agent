from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import get_chat_model, is_llm_available
from app.schemas import (
    ChatHistoryMessage,
    CompanyChatRequest,
    CompanyChatResponse,
    CompanyChatSource,
    CompanyChatToolCall,
    ResearchContextResponse,
    UnifiedAgentResearch,
    UnifiedResearchContext,
)
from app.services.job_service import get_research_context_response
from app.utils.text import truncate_text

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_market_data",
            "description": "Read market, price, returns, volatility, and valuation data for the current company only.",
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string", "description": "Optional market topic to focus on."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_statement_analysis",
            "description": "Read filing/financial-statement extraction, key metrics, quality flags, risks, and score for the current company only.",
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string", "description": "Optional financial topic to focus on."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_message_signals",
            "description": "Read official website, IR, news events, sentiment, extracted numbers, and message-side signals for the current company only.",
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string", "description": "Optional news/message-side topic to focus on."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_events",
            "description": "Read normalized catalyst/risk events already produced for the current company only.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 12}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_research_context",
            "description": "Read the full normalized research context document for the current company only.",
            "parameters": {
                "type": "object",
                "properties": {"focus": {"type": "string", "description": "Optional topic to focus on."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_question",
            "description": "Reject questions that are not about the current company, ask for a different company, or require information outside the research context.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string", "description": "Concise rejection reason."}},
                "required": ["reason"],
            },
        },
    },
]

ROUTER_SYSTEM_PROMPT = """
你是投资研究对话系统的接口选择器。你只能处理当前公司：{company_name}。

可用函数接口：
1. get_market_data: 当前公司的股价、收益率、成交量、波动率、估值。
2. get_financial_statement_analysis: 当前公司的财报抽取、核心财务指标、财务风险和财务健康评分。
3. get_message_signals: 当前公司的官网/IR、新闻事件、情绪、关键数字和消息面结论。
4. get_company_events: 当前公司的结构化事件列表。
5. get_research_context: 当前公司的完整统一研究上下文文档。
6. reject_question: 用户问题不是关于当前公司，或要求分析其他公司，或需要当前研究上下文之外的信息。

规则：
- 必须输出一个或多个 function call。
- 用户问多个维度时可以调用多个函数。
- 严格限定只能回答关于 {company_name} 的问题。
- 如果用户问其他公司、泛化宏观问题、投资建议之外的闲聊，调用 reject_question。
- 不要在接口选择阶段直接回答问题。
"""

ANSWER_SYSTEM_PROMPT = """
你是投资研究对话助手。你只能基于传入的函数结果回答当前公司问题。

要求：
- 只回答当前公司：{company_name}。
- 不使用外部知识，不补编缺失数据。
- 回答要简洁、可追溯，必要时指出数据缺口。
- 具体数字必须来自函数结果。
- 尽量标注来源，例如“根据 Market Agent”“根据财报 Agent”“根据消息面 Agent/新闻事件”。
- 这不是自动交易建议；不要给出绝对买卖指令。
- 使用纯文本回答，不要使用 Markdown 加粗、标题符号、项目符号中的星号或井号。
"""


def answer_memo_chat(memo_id: str, request: CompanyChatRequest) -> CompanyChatResponse | None:
    context_response = get_research_context_response(memo_id)
    if context_response is None:
        return None
    return answer_company_question(context_response, request)


def answer_company_question(
    context_response: ResearchContextResponse,
    request: CompanyChatRequest,
) -> CompanyChatResponse:
    context = context_response.research_context
    tool_calls = _select_chat_tools(context, request.question, request.history)
    if not tool_calls:
        tool_calls = _heuristic_tool_selection(request.question)

    if any(call.name == "reject_question" for call in tool_calls):
        reason = next((call.arguments.get("reason") for call in tool_calls if call.name == "reject_question"), None)
        answer = _clean_chat_answer(str(reason or f"这个对话只支持围绕 {context.company_name} 的研究结果追问。"))
        return CompanyChatResponse(
            memo_id=context_response.memo_id,
            job_id=context_response.job_id,
            company_name=context.company_name,
            answer=answer,
            rejected=True,
            tool_calls=tool_calls,
            sources=[],
        )

    tool_results = [_execute_chat_tool(context_response, call) for call in tool_calls]
    sources = _sources_from_tool_results(tool_results)
    answer = _clean_chat_answer(_generate_chat_answer(context, request.question, request.history, tool_results))
    return CompanyChatResponse(
        memo_id=context_response.memo_id,
        job_id=context_response.job_id,
        company_name=context.company_name,
        answer=answer,
        rejected=False,
        tool_calls=tool_calls,
        sources=sources,
    )


def _select_chat_tools(
    context: UnifiedResearchContext,
    question: str,
    history: list[ChatHistoryMessage],
) -> list[CompanyChatToolCall]:
    if not is_llm_available():
        return _heuristic_tool_selection(question)
    try:
        llm = get_chat_model(temperature=0.0).bind_tools(CHAT_TOOLS)
        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT.format(company_name=context.company_name)),
            HumanMessage(content=_router_user_payload(context, question, history)),
        ]
        result = llm.invoke(messages)
        return _extract_tool_calls(result)
    except Exception:
        return _heuristic_tool_selection(question)


def _router_user_payload(context: UnifiedResearchContext, question: str, history: list[ChatHistoryMessage]) -> str:
    short_history = [{"role": item.role, "content": item.content} for item in history[-6:]]
    return json.dumps(
        {
            "company_name": context.company_name,
            "instrument": context.instrument.model_dump(),
            "available_agents": list(context.agents.keys()),
            "recent_history": short_history,
            "user_question": question,
        },
        ensure_ascii=False,
    )


def _extract_tool_calls(message: Any) -> list[CompanyChatToolCall]:
    raw_calls = getattr(message, "tool_calls", None) or []
    calls: list[CompanyChatToolCall] = []
    for item in raw_calls:
        name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
        args = item.get("args") if isinstance(item, dict) else getattr(item, "args", None)
        if name:
            calls.append(CompanyChatToolCall(name=str(name), arguments=args if isinstance(args, dict) else {}))
    if calls:
        return calls

    for item in (getattr(message, "additional_kwargs", {}) or {}).get("tool_calls", []) or []:
        function = item.get("function") or {}
        name = function.get("name")
        try:
            args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        if name:
            calls.append(CompanyChatToolCall(name=str(name), arguments=args if isinstance(args, dict) else {}))
    return calls


def _heuristic_tool_selection(question: str) -> list[CompanyChatToolCall]:
    normalized = question.lower()
    calls: list[CompanyChatToolCall] = []
    if any(token in normalized for token in ["股价", "价格", "估值", "pe", "pb", "市值", "收益", "走势", "波动", "market", "price", "valuation"]):
        calls.append(CompanyChatToolCall(name="get_market_data", arguments={"focus": question}))
    if any(token in normalized for token in ["财报", "利润", "营收", "现金流", "负债", "毛利", "净利", "financial", "revenue", "cash flow"]):
        calls.append(CompanyChatToolCall(name="get_financial_statement_analysis", arguments={"focus": question}))
    if any(token in normalized for token in ["新闻", "消息", "官网", "ir", "事件", "舆情", "情绪", "催化", "风险", "news", "event"]):
        calls.append(CompanyChatToolCall(name="get_message_signals", arguments={"focus": question}))
        calls.append(CompanyChatToolCall(name="get_company_events", arguments={"limit": 8}))
    if not calls:
        calls.append(CompanyChatToolCall(name="get_research_context", arguments={"focus": question}))
    return _dedupe_tool_calls(calls)


def _execute_chat_tool(context_response: ResearchContextResponse, call: CompanyChatToolCall) -> dict[str, Any]:
    context = context_response.research_context
    if call.name == "get_market_data":
        return _agent_tool_result(context, "market")
    if call.name == "get_financial_statement_analysis":
        return _agent_tool_result(context, "filing")
    if call.name == "get_message_signals":
        return _agent_tool_result(context, "message_intel")
    if call.name == "get_company_events":
        limit = int(call.arguments.get("limit") or 8)
        return {
            "tool": call.name,
            "events": [item.model_dump() for item in context.events[: max(1, min(limit, 12))]],
        }
    if call.name == "get_research_context":
        return {
            "tool": call.name,
            "research_context_document": context_response.llm_context_document,
            "cross_agent": context.cross_agent,
        }
    return {"tool": call.name, "error": "unknown_tool"}


def _agent_tool_result(context: UnifiedResearchContext, agent_name: str) -> dict[str, Any]:
    agent = context.agents.get(agent_name)
    if not agent:
        return {"tool": agent_name, "error": f"{agent_name} data is unavailable."}
    return {
        "tool": agent_name,
        "agent": agent.model_dump(),
    }


def _generate_chat_answer(
    context: UnifiedResearchContext,
    question: str,
    history: list[ChatHistoryMessage],
    tool_results: list[dict[str, Any]],
) -> str:
    if not is_llm_available():
        return _heuristic_answer(context, question, tool_results)
    try:
        llm = get_chat_model(temperature=0.1)
        messages = [
            SystemMessage(content=ANSWER_SYSTEM_PROMPT.format(company_name=context.company_name)),
            HumanMessage(content=_answer_user_payload(question, history, tool_results)),
        ]
        result = llm.invoke(messages)
        content = result.content
        if isinstance(content, list):
            return _clean_chat_answer("\n".join(str(item) for item in content))
        return _clean_chat_answer(str(content))
    except Exception:
        return _clean_chat_answer(_heuristic_answer(context, question, tool_results))


def _answer_user_payload(question: str, history: list[ChatHistoryMessage], tool_results: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "user_question": question,
            "recent_history": [{"role": item.role, "content": item.content} for item in history[-6:]],
            "function_results": tool_results,
        },
        ensure_ascii=False,
        default=str,
    )


def _heuristic_answer(context: UnifiedResearchContext, question: str, tool_results: list[dict[str, Any]]) -> str:
    lines = [f"基于当前已完成的 {context.company_name} 研究结果："]
    for result in tool_results:
        agent_payload = result.get("agent")
        if isinstance(agent_payload, dict):
            agent_name = agent_payload.get("agent_name") or result.get("tool")
            summary = agent_payload.get("summary")
            if summary:
                lines.append(f"- 根据 {agent_name}：{summary}")
            metrics = agent_payload.get("metrics") or {}
            if metrics:
                lines.append(f"  关键数据：{truncate_text(json.dumps(metrics, ensure_ascii=False, default=str), 360)}")
            findings = agent_payload.get("findings") or []
            for finding in findings[:3]:
                lines.append(f"  证据：{finding.get('summary')}")
        elif result.get("events"):
            lines.append("- 根据事件列表：")
            for event in result["events"][:5]:
                lines.append(f"  - {event.get('title')}：{event.get('summary')}")
        elif result.get("research_context_document"):
            lines.append(truncate_text(result["research_context_document"], 900))
    lines.append("以上只基于当前研究上下文，不构成买卖建议。")
    return "\n".join(lines)


def _clean_chat_answer(answer: str) -> str:
    cleaned = str(answer or "")
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"__(.*?)__", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*]\s+", "", cleaned)
    return cleaned.strip()


def _sources_from_tool_results(tool_results: list[dict[str, Any]]) -> list[CompanyChatSource]:
    sources: list[CompanyChatSource] = []
    for result in tool_results:
        agent_payload = result.get("agent")
        if isinstance(agent_payload, dict):
            agent_name = str(agent_payload.get("agent_name") or result.get("tool") or "")
            for finding in agent_payload.get("findings") or []:
                refs = finding.get("source_refs") or []
                sources.append(
                    CompanyChatSource(
                        agent_name=agent_name,
                        title=str(finding.get("category") or agent_name),
                        snippet=truncate_text(str(finding.get("summary") or ""), 280),
                        url=refs[0] if refs else None,
                    )
                )
        for event in result.get("events") or []:
            source_ids = event.get("source_ids") or []
            sources.append(
                CompanyChatSource(
                    agent_name="message_intel",
                    title=str(event.get("title") or "event"),
                    snippet=truncate_text(str(event.get("summary") or ""), 280),
                    url=source_ids[0] if source_ids else None,
                    date=event.get("date"),
                )
            )
    deduped: list[CompanyChatSource] = []
    seen: set[tuple[str, str, str | None]] = set()
    for source in sources:
        key = (source.agent_name, source.title, source.url)
        if key in seen or not source.snippet:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped[:8]


def _dedupe_tool_calls(calls: list[CompanyChatToolCall]) -> list[CompanyChatToolCall]:
    deduped: list[CompanyChatToolCall] = []
    seen: set[str] = set()
    for call in calls:
        if call.name in seen:
            continue
        seen.add(call.name)
        deduped.append(call)
    return deduped
