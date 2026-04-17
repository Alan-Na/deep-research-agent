from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


API_BASE_URL = os.getenv("RESEARCH_PLATFORM_API_BASE_URL", "http://localhost:8000").rstrip("/")
mcp = FastMCP("Investment Job MCP", json_response=True)


def _client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE_URL, timeout=30.0)


def _request(method: str, path: str, **kwargs: Any) -> Any:
    with _client() as client:
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text


def _tokenize(text: str) -> set[str]:
    return {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if token}


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Check whether the local research platform and its dependencies are healthy."""
    return _request("GET", "/health")


@mcp.tool()
def create_investment_job(company_name: str) -> dict[str, Any]:
    """Create a new investment research job and return its job metadata."""
    return _request("POST", "/investment-jobs", json={"company_name": company_name})


@mcp.tool()
def get_investment_job_status(job_id: str) -> dict[str, Any]:
    """Fetch the current status payload for an investment research job."""
    return _request("GET", f"/investment-jobs/{job_id}")


@mcp.tool()
def wait_for_investment_job(job_id: str, timeout_seconds: int = 180, poll_interval_seconds: float = 2.0) -> dict[str, Any]:
    """Poll a job until it reaches succeeded, partial, or failed, or until timeout."""
    deadline = time.time() + max(timeout_seconds, 1)
    while time.time() < deadline:
        status = get_investment_job_status(job_id)
        if status.get("status") in {"succeeded", "partial", "failed"}:
            return status
        time.sleep(max(poll_interval_seconds, 0.2))
    return get_investment_job_status(job_id)


@mcp.tool()
def list_investment_jobs(limit: int = 10) -> list[dict[str, Any]]:
    """List recent investment jobs from the local platform."""
    return _request("GET", f"/investment-jobs?limit={max(limit, 1)}")


@mcp.tool()
def get_memo(memo_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    """Fetch an investment memo directly by memo_id or resolve it from a job_id."""
    if memo_id:
        return _request("GET", f"/investment-memos/{memo_id}")
    if not job_id:
        raise ValueError("Provide either memo_id or job_id.")
    status = get_investment_job_status(job_id)
    resolved_memo_id = status.get("memo_id")
    if not resolved_memo_id:
        raise ValueError(f"Job {job_id} does not have a memo yet.")
    return _request("GET", f"/investment-memos/{resolved_memo_id}")


@mcp.tool()
def search_memo_citations(job_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search a completed investment memo's citations with simple token overlap ranking."""
    memo_payload = get_memo(job_id=job_id)
    memo = memo_payload.get("memo", {})
    citations = memo.get("citations", [])
    query_tokens = _tokenize(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for citation in citations:
        haystack = " ".join(
            [
                str(citation.get("claim", "")),
                str(citation.get("title", "")),
                str(citation.get("snippet", "")),
                str(citation.get("agent_name", "")),
            ]
        )
        score = len(query_tokens & _tokenize(haystack))
        if score > 0:
            scored.append((score, citation))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [citation for _, citation in scored[: max(limit, 1)]]


# Deprecated v1 aliases.
@mcp.tool()
def create_research_job(company_name: str) -> dict[str, Any]:
    return create_investment_job(company_name)


@mcp.tool()
def get_research_job_status(job_id: str) -> dict[str, Any]:
    status = get_investment_job_status(job_id)
    status["planner_output"] = status.pop("research_brief", None)
    status["module_runs"] = status.pop("agent_runs", [])
    status["report_id"] = status.pop("memo_id", None)
    return status


@mcp.tool()
def wait_for_research_job(job_id: str, timeout_seconds: int = 180, poll_interval_seconds: float = 2.0) -> dict[str, Any]:
    return wait_for_investment_job(job_id, timeout_seconds=timeout_seconds, poll_interval_seconds=poll_interval_seconds)


@mcp.tool()
def list_research_jobs(limit: int = 10) -> list[dict[str, Any]]:
    jobs = list_investment_jobs(limit)
    for job in jobs:
        job["report_id"] = job.pop("memo_id", None)
    return jobs


@mcp.tool()
def get_report(report_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    memo = get_memo(memo_id=report_id, job_id=job_id)
    return {
        "report_id": memo.get("memo_id"),
        "job_id": memo.get("job_id"),
        "report": memo.get("memo"),
    }


@mcp.tool()
def search_report_citations(job_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    return search_memo_citations(job_id=job_id, query=query, limit=limit)


if __name__ == "__main__":
    mcp.run(transport=os.getenv("RESEARCH_JOB_MCP_TRANSPORT", "stdio"))
