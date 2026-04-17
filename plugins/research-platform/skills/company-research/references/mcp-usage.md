# MCP Usage

## Tools

- `health_check()`
- `create_research_job(company_name)`
- `get_research_job_status(job_id)`
- `wait_for_research_job(job_id, timeout_seconds, poll_interval_seconds)`
- `list_research_jobs(limit)`
- `get_report(report_id=None, job_id=None)`
- `search_report_citations(job_id, query, limit)`

## Fallback HTTP mapping

- Health: `GET /health`
- Create job: `POST /research-jobs`
- Job status: `GET /research-jobs/{job_id}`
- Report: `GET /reports/{report_id}`

## Practical rules

- Prefer `wait_for_research_job` when you need a completed report before answering.
- Prefer `get_report(job_id=...)` over manually resolving `report_id`.
- Use `search_report_citations` when the user asks for proof, sources, or support for a specific claim.
- If the API is unavailable, say that the local platform is down rather than guessing.
