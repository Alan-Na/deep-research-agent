const BASE = ''

const JOB_STATUS_MAP = {
  queued: 'pending',
  running: 'running',
  partial: 'completed',
  succeeded: 'completed',
  failed: 'failed',
}

const RUN_STATUS_MAP = {
  queued: 'pending',
  running: 'running',
  success: 'completed',
  succeeded: 'completed',
  partial: 'partial',
  skipped: 'partial',
  failed: 'failed',
}

function normalizeJobStatus(status) {
  return JOB_STATUS_MAP[(status || '').toLowerCase()] || status || 'pending'
}

function normalizeRunStatus(status) {
  return RUN_STATUS_MAP[(status || '').toLowerCase()] || status || 'pending'
}

function stanceToSentiment(stance) {
  const value = (stance || '').toLowerCase()
  if (value === 'bullish') return 'positive'
  if (value === 'bearish') return 'negative'
  return 'neutral'
}

function buildModuleResults(moduleRuns = []) {
  return Object.fromEntries(
    moduleRuns.map((item) => [
      item.module,
      {
        status: normalizeRunStatus(item.status),
        applicable: item.status !== 'skipped',
        summary: item.summary || '',
        key_points: [],
        warning: item.warning || null,
        error: item.error || null,
      },
    ])
  )
}

function summarizeAgentPayload(agentName, payload) {
  if (!payload || typeof payload !== 'object') return ''
  if (typeof payload.summary === 'string' && payload.summary) return payload.summary
  if (agentName === 'market' && payload.market_snapshot) {
    const snapshot = payload.market_snapshot
    return `Price ${snapshot.last_price ?? 'n/a'} | PE ${snapshot.valuation?.pe_ttm ?? 'n/a'} | PB ${snapshot.valuation?.pb ?? 'n/a'}`
  }
  if (agentName === 'news_risk' && payload.dominant_narrative) return payload.dominant_narrative
  if (agentName === 'web_intel' && payload.official_website) return `Official website: ${payload.official_website}`
  if (agentName === 'filing' && payload.provider) return `Disclosure provider: ${payload.provider}`
  return Object.keys(payload).slice(0, 4).join(', ')
}

function extractKeyPoints(payload) {
  if (!payload || typeof payload !== 'object') return []
  const points = []
  const addMany = (items) => {
    if (Array.isArray(items)) {
      for (const item of items) {
        if (typeof item === 'string' && item.trim()) points.push(item.trim())
      }
    }
  }
  addMany(payload.product_points)
  addMany(payload.ir_highlights)
  addMany(payload.positioning)
  addMany(payload.bull_case)
  addMany(payload.bear_case)
  addMany(payload.key_risks)
  addMany(payload.key_catalysts)
  return [...new Set(points)].slice(0, 6)
}

function transformReportResponse(raw) {
  const memo = raw?.report || raw?.memo || raw || {}
  const keyFindings = [
    ...(memo.bull_case || []).slice(0, 3),
    ...(memo.bear_case || []).slice(0, 2),
    ...(memo.key_catalysts || []).slice(0, 2),
  ]
  const citations = Array.isArray(memo.citations) ? memo.citations : []
  const moduleResults = Object.fromEntries(
    Object.entries(memo.agent_outputs || {}).map(([agentName, payload]) => [
      agentName,
      {
        status: 'completed',
        applicable: true,
        summary: summarizeAgentPayload(agentName, payload),
        key_points: extractKeyPoints(payload),
        warning: null,
        error: null,
      },
    ])
  )

  return {
    report_id: raw?.report_id || raw?.memo_id || null,
    job_id: raw?.job_id || null,
    company_name: memo.company_name,
    market: memo.market,
    is_public: memo.market && memo.market !== 'UNKNOWN',
    overall_sentiment: stanceToSentiment(memo.stance),
    summary: memo.thesis || '',
    key_findings: [...new Set(keyFindings)].slice(0, 8),
    risks: memo.key_risks || [],
    evidence: citations.map((item) => ({
      source_type: item.source_type,
      module: item.agent_name,
      title: item.title,
      snippet: item.snippet,
      url: item.url,
      date: item.date,
    })),
    limitations: memo.limitations || [],
    module_results: moduleResults,
    raw,
  }
}

function transformJobResponse(raw) {
  const moduleRuns = Array.isArray(raw?.module_runs) ? raw.module_runs : []
  return {
    ...raw,
    id: raw?.job_id || raw?.id,
    status: normalizeJobStatus(raw?.status),
    raw_status: raw?.status,
    module_results: buildModuleResults(moduleRuns),
    error: raw?.error || (Array.isArray(raw?.warnings) ? raw.warnings[0] : null),
  }
}

export async function createJob(companyName) {
  const res = await fetch(`${BASE}/research-jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ company_name: companyName }),
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => 'Request failed')
    throw new Error(msg)
  }
  return res.json()
}

export async function getJob(jobId) {
  const res = await fetch(`${BASE}/research-jobs/${jobId}`)
  if (!res.ok) throw new Error('Failed to fetch job')
  const raw = await res.json()
  return transformJobResponse(raw)
}

export async function listJobs(limit = 40) {
  const res = await fetch(`${BASE}/research-jobs?limit=${limit}`)
  if (!res.ok) throw new Error('Failed to list jobs')
  const raw = await res.json()
  return Array.isArray(raw) ? raw.map(transformJobResponse) : raw
}

export async function getReport(reportId) {
  const res = await fetch(`${BASE}/reports/${reportId}`)
  if (!res.ok) throw new Error('Failed to fetch report')
  const raw = await res.json()
  return transformReportResponse(raw)
}

export async function getOhlcv(jobId) {
  const res = await fetch(`${BASE}/research-jobs/${jobId}/ohlcv`)
  if (!res.ok) throw new Error('Failed to fetch OHLCV data')
  const raw = await res.json()
  const series = raw?.series || {}
  return {
    job_id: raw?.job_id || jobId,
    company_name: raw?.company_name || '',
    market: raw?.market || 'UNKNOWN',
    instrument: raw?.instrument || {},
    series: {
      symbol: series.symbol || '',
      market: series.market || raw?.market || 'UNKNOWN',
      display_name: series.display_name || raw?.instrument?.display_name || raw?.company_name || '',
      adjustment: series.adjustment || 'raw',
      provider: series.provider || 'market-data-mcp',
      cache_status: series.cache_status || 'miss',
      cached_until: series.cached_until || null,
      bars: Array.isArray(series.bars) ? series.bars : [],
    },
  }
}

function emitSnapshotEvents(status, onEvent) {
  if (!status) return
  onEvent({ type: 'started', node: 'intake_brief', status: 'running' })
  const runs = Array.isArray(status.module_runs) ? status.module_runs : Array.isArray(status.agent_runs) ? status.agent_runs : []
  for (const item of runs) {
    const node = item.module || item.agent_name
    if (!node) continue
    onEvent({
      type: normalizeRunStatus(item.status),
      node,
      status: normalizeRunStatus(item.status),
    })
  }
  const terminal = ['partial', 'succeeded', 'failed', 'completed'].includes((status.status || '').toLowerCase())
  if (terminal && (status.report_id || status.memo_id)) {
    onEvent({
      type: 'job_completed',
      status: 'completed',
      report_id: status.report_id || status.memo_id,
    })
  }
}

export function openEventStream(jobId, onEvent, onError) {
  const url = `${BASE}/research-jobs/${jobId}/events`
  const es = new EventSource(url)

  es.onmessage = (e) => {
    try {
      const payload = JSON.parse(e.data)
      if (payload?.type === 'snapshot') {
        emitSnapshotEvents(payload.status, onEvent)
        return
      }

      if (payload?.type === 'job_started') {
        onEvent({ type: 'started', node: 'intake_brief', status: 'running' })
        return
      }

      if (payload?.type === 'agent_started' || payload?.type === 'tool_called' || payload?.type === 'observation_recorded') {
        onEvent({
          type: 'running',
          node: payload.agent_name,
          status: 'running',
        })
        return
      }

      if (payload?.type === 'agent_completed') {
        onEvent({
          type: normalizeRunStatus(payload.status),
          node: payload.agent_name,
          status: normalizeRunStatus(payload.status),
          warning: payload.warning,
          error: payload.error,
        })
        return
      }

      if (payload?.type === 'critic_warning') {
        onEvent({
          type: 'running',
          node: 'critic_output',
          status: 'running',
          warning: payload.warning,
        })
        return
      }

      if (payload?.type === 'memo_ready' || payload?.type === 'job_status') {
        onEvent({
          type: 'job_completed',
          status: 'completed',
          report_id: payload.report_id || payload.memo_id || null,
        })
        return
      }

      if (payload?.type === 'job_failed') {
        onEvent({
          type: 'failed',
          status: 'failed',
          error: payload.error || 'Job failed',
        })
        return
      }

      onEvent(payload)
    } catch {
      // ignore malformed keep-alive payloads
    }
  }

  es.addEventListener('error', () => {
    if (onError) onError()
    es.close()
  })

  return es
}
