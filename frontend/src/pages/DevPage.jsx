import { useState, useEffect, useRef } from 'react'
import { listJobs, getJob, getReport, openEventStream } from '../api'

const COPY = {
  en: {
    topTitle: 'Dev Console',
    jobs: 'jobs',
    toUser: '← User View',
    languageToggle: '中文',
    filters: { all: 'all', running: 'running', completed: 'completed', failed: 'failed' },
    loading: 'Loading…',
    noJobs: 'No jobs found.',
    selectJob: 'Select a job to inspect.',
    jobNotFound: 'Job not found.',
    tabs: { overview: 'Overview', modules: 'Modules', events: 'Events', raw: 'Raw JSON' },
    listening: 'Listening for events…',
    noEvents: 'No live events captured. Job is not running.',
    noModuleData: 'No module data yet.',
    notApplicable: 'not applicable',
    summary: 'SUMMARY',
    fields: {
      jobId: 'Job ID',
      company: 'Company',
      status: 'Status',
      created: 'Created',
      updated: 'Updated',
      reportId: 'Report ID',
      market: 'Market',
      isPublic: 'Is Public',
      sentiment: 'Sentiment',
      modulesRun: 'Modules run',
    },
  },
  zh: {
    topTitle: '开发者控制台',
    jobs: '个任务',
    toUser: '← 用户视图',
    languageToggle: 'EN',
    filters: { all: '全部', running: '运行中', completed: '已完成', failed: '失败' },
    loading: '加载中…',
    noJobs: '暂无任务。',
    selectJob: '请选择一个任务查看详情。',
    jobNotFound: '未找到该任务。',
    tabs: { overview: '概览', modules: '模块', events: '事件流', raw: '原始 JSON' },
    listening: '正在监听事件流…',
    noEvents: '当前没有实时事件，任务未在运行。',
    noModuleData: '暂无模块数据。',
    notApplicable: '不适用',
    summary: '摘要',
    fields: {
      jobId: '任务 ID',
      company: '公司',
      status: '状态',
      created: '创建时间',
      updated: '更新时间',
      reportId: '报告 ID',
      market: '市场',
      isPublic: '是否上市',
      sentiment: '情绪',
      modulesRun: '已运行模块',
    },
  },
}

function fmtTime(iso, lang) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(lang === 'zh' ? 'zh-CN' : 'en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function statusColor(s) {
  const m = {
    completed: '#3fb950',
    success: '#3fb950',
    succeeded: '#3fb950',
    running: '#58a6ff',
    pending: '#d29922',
    queued: '#d29922',
    partial: '#d29922',
    failed: '#f85149',
    error: '#f85149',
  }
  return m[(s || '').toLowerCase()] || '#8b949e'
}

function Badge({ status }) {
  const col = statusColor(status)
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      fontSize: 11, fontWeight: 600, fontFamily: 'var(--mono)',
      color: col, letterSpacing: '.04em',
      background: col + '1a',
      padding: '2px 8px', borderRadius: 4,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: col }} />
      {(status || '').toUpperCase()}
    </span>
  )
}

function JsonViewer({ data, depth = 0 }) {
  const [collapsed, setCollapsed] = useState(depth >= 2)
  if (data === null) return <span style={{ color: '#8b949e' }}>null</span>
  if (typeof data === 'boolean') return <span style={{ color: '#bc8cff' }}>{String(data)}</span>
  if (typeof data === 'number') return <span style={{ color: '#58a6ff' }}>{data}</span>
  if (typeof data === 'string') return <span style={{ color: '#a5c261' }}>"{data.length > 200 ? data.slice(0, 200) + '…' : data}"</span>

  if (Array.isArray(data)) {
    if (data.length === 0) return <span style={{ color: 'var(--dev-muted)' }}>[]</span>
    return (
      <span>
        <button onClick={() => setCollapsed(v => !v)} style={{
          color: 'var(--dev-blue)', background: 'none', border: 'none',
          cursor: 'pointer', fontFamily: 'var(--mono)', fontSize: 13, padding: 0,
        }}>
          {collapsed ? `[… ${data.length} items]` : '['}
        </button>
        {!collapsed && (
          <>
            {data.map((v, i) => (
              <div key={i} style={{ paddingLeft: 18 }}>
                <JsonViewer data={v} depth={depth + 1} />
                {i < data.length - 1 && <span style={{ color: 'var(--dev-muted)' }}>,</span>}
              </div>
            ))}
            <span style={{ color: 'var(--dev-text)' }}>]</span>
          </>
        )}
      </span>
    )
  }

  const entries = Object.entries(data)
  if (entries.length === 0) return <span style={{ color: 'var(--dev-muted)' }}>{'{}'}</span>
  return (
    <span>
      <button onClick={() => setCollapsed(v => !v)} style={{
        color: 'var(--dev-blue)', background: 'none', border: 'none',
        cursor: 'pointer', fontFamily: 'var(--mono)', fontSize: 13, padding: 0,
      }}>
        {collapsed ? `{… ${entries.length} keys}` : '{'}
      </button>
      {!collapsed && (
        <>
          {entries.map(([k, v], i) => (
            <div key={k} style={{ paddingLeft: 18 }}>
              <span style={{ color: '#e3b341' }}>"{k}"</span>
              <span style={{ color: 'var(--dev-muted)' }}>: </span>
              <JsonViewer data={v} depth={depth + 1} />
              {i < entries.length - 1 && <span style={{ color: 'var(--dev-muted)' }}>,</span>}
            </div>
          ))}
          <span style={{ color: 'var(--dev-text)' }}>{'}'}</span>
        </>
      )}
    </span>
  )
}

function JobDetail({ jobId, copy, lang }) {
  const [tab, setTab] = useState('overview')
  const [job, setJob] = useState(null)
  const [report, setReport] = useState(null)
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const esRef = useRef(null)
  const logRef = useRef(null)

  useEffect(() => {
    if (!jobId) return
    let alive = true
    setJob(null)
    setReport(null)
    setEvents([])
    setLoading(true)

    async function load() {
      const j = await getJob(jobId).catch(() => null)
      if (!alive || !j) return
      setJob(j)
      setLoading(false)

      if (j.report_id) {
        const r = await getReport(j.report_id).catch(() => null)
        if (alive && r) setReport(r)
      } else if (j.report) {
        setReport(j.report)
      }

      if (j.status === 'running' || j.status === 'pending') {
        esRef.current = openEventStream(jobId, (e) => {
          if (!alive) return
          setEvents(prev => [...prev.slice(-199), { ts: Date.now(), data: e }])
          if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
        })
      }
    }

    load()
    return () => {
      alive = false
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
    }
  }, [jobId])

  if (loading) {
    return <div style={{ padding: 32, color: 'var(--dev-muted)', fontFamily: 'var(--mono)', fontSize: 13 }}>{copy.loading}</div>
  }
  if (!job) {
    return <div style={{ padding: 32, color: 'var(--dev-red)', fontFamily: 'var(--mono)', fontSize: 13 }}>{copy.jobNotFound}</div>
  }

  const tabs = [
    { id: 'overview', label: copy.tabs.overview },
    { id: 'modules', label: copy.tabs.modules },
    { id: 'events', label: `${copy.tabs.events}${events.length ? ` (${events.length})` : ''}` },
    { id: 'raw', label: copy.tabs.raw },
  ]

  const mr = job.module_results || report?.module_results || {}
  const overviewRows = [
    [copy.fields.jobId, job.job_id || job.id || '—'],
    [copy.fields.company, job.company_name || '—'],
    [copy.fields.status, null, <Badge status={job.status} />],
    [copy.fields.created, fmtTime(job.created_at, lang)],
    [copy.fields.updated, fmtTime(job.updated_at, lang)],
    [copy.fields.reportId, job.report_id || '—'],
    [copy.fields.market, job.market || report?.market || '—'],
    [copy.fields.isPublic, job.is_public != null ? String(job.is_public) : report?.is_public != null ? String(report.is_public) : '—'],
    [copy.fields.sentiment, report?.overall_sentiment || '—'],
    [copy.fields.modulesRun, Object.keys(mr).join(', ') || '—'],
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{
        display: 'flex', gap: 0,
        borderBottom: '1px solid var(--dev-border)',
        flexShrink: 0,
      }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '10px 18px',
            fontFamily: 'var(--mono)', fontSize: 12,
            color: tab === t.id ? 'var(--dev-blue)' : 'var(--dev-muted)',
            background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: tab === t.id ? '2px solid var(--dev-blue)' : '2px solid transparent',
            marginBottom: -1,
          }}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {tab === 'overview' && (
          <div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--mono)', fontSize: 13 }}>
              <tbody>
                {overviewRows.map(([k, v, node]) => (
                  <tr key={k} style={{ borderBottom: '1px solid var(--dev-border)' }}>
                    <td style={{ padding: '9px 12px 9px 0', color: 'var(--dev-muted)', width: 140 }}>{k}</td>
                    <td style={{ padding: '9px 0', color: 'var(--dev-text)' }}>{node ?? v}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {report?.summary && (
              <div style={{ marginTop: 24 }}>
                <p style={{ fontSize: 12, color: 'var(--dev-muted)', fontFamily: 'var(--mono)', marginBottom: 8 }}>{copy.summary}</p>
                <p style={{ fontSize: 14, color: 'var(--dev-text)', lineHeight: 1.6 }}>{report.summary}</p>
              </div>
            )}
          </div>
        )}

        {tab === 'modules' && (
          <div>
            {Object.keys(mr).length === 0 && (
              <p style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--dev-muted)' }}>{copy.noModuleData}</p>
            )}
            {Object.entries(mr).map(([mod, res]) => (
              <div key={mod} style={{
                background: 'var(--dev-card)', border: '1px solid var(--dev-border)',
                borderRadius: 8, padding: '16px 20px', marginBottom: 12,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                  <span style={{ fontFamily: 'var(--mono)', fontWeight: 500, color: 'var(--dev-blue)', fontSize: 13 }}>{mod}</span>
                  <Badge status={res.status} />
                  {!res.applicable && (
                    <span style={{ fontSize: 11, color: 'var(--dev-muted)', fontFamily: 'var(--mono)' }}>{copy.notApplicable}</span>
                  )}
                </div>

                {res.summary && (
                  <p style={{ fontSize: 13, color: 'var(--dev-text)', marginBottom: 8, lineHeight: 1.55 }}>{res.summary}</p>
                )}

                {res.key_points?.length > 0 && (
                  <ul style={{ paddingLeft: 16, margin: 0 }}>
                    {res.key_points.map((p, i) => (
                      <li key={i} style={{ fontSize: 12, color: 'var(--dev-muted)', marginBottom: 3 }}>{p}</li>
                    ))}
                  </ul>
                )}

                {res.warning && (
                  <p style={{ fontSize: 12, color: 'var(--dev-amber)', marginTop: 6, fontFamily: 'var(--mono)' }}>⚠ {res.warning}</p>
                )}
                {res.error && (
                  <p style={{ fontSize: 12, color: 'var(--dev-red)', marginTop: 6, fontFamily: 'var(--mono)' }}>✗ {res.error}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === 'events' && (
          <div>
            <div ref={logRef} style={{
              fontFamily: 'var(--mono)', fontSize: 12,
              background: 'var(--dev-bg)', border: '1px solid var(--dev-border)',
              borderRadius: 8, padding: 16,
              maxHeight: '65vh', overflow: 'auto',
            }}>
              {events.length === 0 && (
                <span style={{ color: 'var(--dev-muted)' }}>
                  {job.status === 'running' || job.status === 'pending' ? copy.listening : copy.noEvents}
                </span>
              )}
              {events.map((e, i) => {
                const ts = new Date(e.ts).toISOString().slice(11, 23)
                const type = e.data?.type || e.data?.event || '—'
                const node = e.data?.node || e.data?.module || ''
                const col  = statusColor(type)
                return (
                  <div key={i} style={{ marginBottom: 4, lineHeight: 1.5 }}>
                    <span style={{ color: 'var(--dev-muted)' }}>{ts}</span>{' '}
                    <span style={{ color: col }}>{type}</span>
                    {node && <span style={{ color: 'var(--dev-blue)' }}> [{node}]</span>}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {tab === 'raw' && (
          <pre style={{
            fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.6,
            color: 'var(--dev-text)', background: 'var(--dev-bg)',
            border: '1px solid var(--dev-border)', borderRadius: 8,
            padding: 16, overflow: 'auto', maxHeight: '70vh',
          }}>
            <JsonViewer data={report || job} />
          </pre>
        )}
      </div>
    </div>
  )
}

export default function DevPage({ lang = 'en', onToggleLang, onSwitchToUser }) {
  const copy = COPY[lang] || COPY.en
  const [jobs, setJobs] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    let alive = true
    const load = async () => {
      const data = await listJobs(40).catch(() => [])
      if (alive) {
        const list = Array.isArray(data) ? data : data.jobs || data.items || []
        setJobs(list)
        setLoading(false)
        if (list.length > 0 && !selected) setSelected(list[0].job_id || list[0].id)
      }
    }
    load()
    const t = setInterval(load, 8000)
    return () => { alive = false; clearInterval(t) }
  }, [selected])

  const filtered = jobs.filter(j => {
    if (filter === 'all') return true
    return (j.status || '').toLowerCase() === filter
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--dev-bg)', color: 'var(--dev-text)' }}>
      <div style={{
        height: 48, background: 'var(--dev-panel)',
        borderBottom: '1px solid var(--dev-border)',
        display: 'flex', alignItems: 'center',
        padding: '0 20px', gap: 20, flexShrink: 0,
      }}>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 500, color: 'var(--dev-blue)' }}>
          {copy.topTitle}
        </span>
        <span style={{ color: 'var(--dev-border)' }}>|</span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--dev-muted)' }}>
          {jobs.length} {copy.jobs}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={onToggleLang} style={{
            fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--dev-muted)',
            padding: '4px 12px', border: '1px solid var(--dev-border)',
            borderRadius: 4, background: 'none', cursor: 'pointer',
          }}>
            {copy.languageToggle}
          </button>
          <button onClick={onSwitchToUser} style={{
            fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--dev-muted)',
            padding: '4px 12px', border: '1px solid var(--dev-border)',
            borderRadius: 4, background: 'none', cursor: 'pointer',
          }}>
            {copy.toUser}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{
          width: 290, flexShrink: 0,
          background: 'var(--dev-panel)',
          borderRight: '1px solid var(--dev-border)',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <div style={{
            display: 'flex', gap: 0, padding: '8px 12px',
            borderBottom: '1px solid var(--dev-border)',
          }}>
            {['all', 'running', 'completed', 'failed'].map(f => (
              <button key={f} onClick={() => setFilter(f)} style={{
                flex: 1, padding: '5px 0',
                fontFamily: 'var(--mono)', fontSize: 11,
                color: filter === f ? 'var(--dev-text)' : 'var(--dev-muted)',
                background: filter === f ? 'var(--dev-card)' : 'none',
                border: 'none', cursor: 'pointer', borderRadius: 4,
              }}>
                {copy.filters[f]}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, overflow: 'auto' }}>
            {loading && (
              <div style={{ padding: 16, fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--dev-muted)' }}>
                {copy.loading}
              </div>
            )}
            {!loading && filtered.length === 0 && (
              <div style={{ padding: 16, fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--dev-muted)' }}>
                {copy.noJobs}
              </div>
            )}
            {filtered.map(j => {
              const id = j.job_id || j.id
              const sel = id === selected
              return (
                <button key={id} onClick={() => setSelected(id)} style={{
                  width: '100%', textAlign: 'left',
                  padding: '10px 14px',
                  background: sel ? 'var(--dev-card)' : 'none',
                  border: 'none',
                  borderLeft: sel ? '2px solid var(--dev-blue)' : '2px solid transparent',
                  cursor: 'pointer',
                  borderBottom: '1px solid var(--dev-border)',
                  display: 'block',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
                    <span style={{
                      fontFamily: 'var(--mono)', fontSize: 13,
                      color: sel ? 'var(--dev-text)' : 'var(--dev-muted)',
                      fontWeight: sel ? 500 : 400,
                      flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {j.company_name || '—'}
                    </span>
                    <Badge status={j.status} />
                  </div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--dev-muted)', marginTop: 3 }}>
                    {fmtTime(j.created_at, lang)}
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'hidden' }}>
          {selected
            ? <JobDetail key={selected} jobId={selected} copy={copy} lang={lang} />
            : (
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                height: '100%', fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--dev-muted)',
              }}>
                {copy.selectJob}
              </div>
            )
          }
        </div>
      </div>
    </div>
  )
}
