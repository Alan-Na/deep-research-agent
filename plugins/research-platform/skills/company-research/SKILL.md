---
name: company-research
description: Grounded company recent-status analysis workflow for the local research platform. Use when analyzing a company, creating a research job, reviewing module coverage, checking risks and limitations, or extracting citation-backed findings from the report.
---

# Company Research

Use this skill when the task is to analyze a company with the local research platform or to reason over a report it produced.

## Workflow

1. Confirm the local platform is reachable.
   Prefer the `research-job-mcp` tools when available.
   If the MCP server is unavailable, fall back to the HTTP API on `http://localhost:8000`.
2. Create a research job for the target company.
3. Poll until the job is `succeeded`, `partial`, or `failed`.
4. Read the final report and inspect:
   - `overall_sentiment`
   - `key_findings`
   - `risks`
   - `limitations`
   - `module_results`
   - `citations`
   - `evaluation_summary`
5. Base your answer on citations and module coverage, not on unstated prior knowledge.

## Analysis Rules

- Treat `filing` evidence as the highest-signal structured source when present.
- Treat `website` as official positioning and product/strategy context, not as proof of financial performance.
- Treat `news` as recency and external narrative context; if the module failed, say so plainly.
- If a module failed or the report is `partial`, explicitly surface the gap in your answer.
- Prefer exact reported values, dates, and cited snippets over vague summaries.
- When evidence is weak or stale, downgrade confidence and say why.

## Reporting Standard

- Start with the current status in one sentence.
- Then give 3-5 evidence-backed findings.
- Then list material risks or limitations.
- Mention whether the report is `succeeded` or `partial`.
- Do not present unsupported conclusions that are not tied back to report citations or module output.

## References

- For the full operating workflow and output checklist, read [workflow.md](references/workflow.md).
- For how to use the MCP tools and fall back to raw HTTP, read [mcp-usage.md](references/mcp-usage.md).
