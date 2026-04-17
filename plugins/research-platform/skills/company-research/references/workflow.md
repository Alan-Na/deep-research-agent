# Workflow

## Use this workflow

Use this workflow when the user wants a current company-status readout, a report summary, a review of module results, or a grounded explanation of the platform output.

## Steps

1. Check platform health.
   - Prefer MCP `health_check`
   - Fallback: `GET /health`
2. Create a job.
   - Prefer MCP `create_research_job`
   - Fallback: `POST /research-jobs`
3. Wait for completion.
   - Prefer MCP `wait_for_research_job`
   - Fallback: poll `GET /research-jobs/{job_id}`
4. Read the report.
   - Prefer MCP `get_report`
   - Fallback: `GET /reports/{report_id}`
5. Extract only grounded conclusions.

## Output checklist

- Company name
- Job status
- Overall sentiment
- Top findings with dates or values where available
- Risks
- Limitations
- Whether failed modules materially weaken the conclusion
- At least one cited source per major conclusion when possible
