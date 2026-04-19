import { useState, useEffect, useRef, useCallback } from 'react'
import { createJob, getJob, getOhlcv, getReport, openEventStream } from '../api'

const COPY = {
  en: {
    steps: [
      { key: 'intake_brief', label: 'Building research brief' },
      { key: 'market', label: 'Analyzing market & valuation data' },
      { key: 'filing', label: 'Reading regulatory filings' },
      { key: 'web_intel', label: 'Scanning official website and IR pages' },
      { key: 'news_risk', label: 'Clustering news and risk events' },
      { key: 'critic_output', label: 'Writing the investment memo' },
    ],
    sentiments: {
      positive: 'Positive Outlook',
      negative: 'Negative Outlook',
      neutral: 'Neutral Outlook',
      mixed: 'Mixed Signals',
    },
    researching: 'Researching…',
    keyFindings: 'Key Findings',
    riskFactors: 'Risk Factors',
    sources: 'Sources',
    sourcesDesc: 'Data compiled from news, regulatory filings, company website, and market feeds.',
    showFewer: '▲ Show fewer',
    showAll: (count) => `▼ Show all ${count} sources`,
    researchNotes: 'Research notes',
    marketChart: 'Daily K-Line',
    marketChartDesc: 'Server-side normalized and cached OHLCV bars with volume overlay.',
    cacheHit: 'Cache hit',
    cacheRefresh: 'Incremental refresh',
    cacheMiss: 'Cold fetch',
    latestBar: 'Latest bar',
    analysisFailed: 'Analysis failed — please try again.',
    startFailed: 'Failed to start analysis.',
    navTitle: 'Research Intelligence',
    newSearch: 'New Search',
    devConsole: 'Dev Console',
    languageToggle: '中文',
    heroEyebrow: 'AI-powered company research',
    heroTitle: ['Research any company,', 'instantly.'],
    heroSubtitle: 'Get a comprehensive research brief — market data, filings, news, and analysis — in under a minute.',
    searchPlaceholder: 'Enter company name — NVIDIA, Apple, Tesla…',
    analyzing: 'Analyzing',
    analyzeButton: 'Analyze →',
    recentSearches: 'Recent searches',
  },
  zh: {
    steps: [
      { key: 'intake_brief', label: '构建研究任务与公司画像' },
      { key: 'market', label: '分析市场与估值数据' },
      { key: 'filing', label: '读取公告与财务披露' },
      { key: 'web_intel', label: '扫描官网与投资者关系页面' },
      { key: 'news_risk', label: '聚类新闻与风险事件' },
      { key: 'critic_output', label: '撰写投资研究备忘录' },
    ],
    sentiments: {
      positive: '偏积极',
      negative: '偏消极',
      neutral: '中性判断',
      mixed: '多空交织',
    },
    researching: '正在研究中…',
    keyFindings: '关键结论',
    riskFactors: '风险因素',
    sources: '证据来源',
    sourcesDesc: '数据来自新闻、监管披露、公司官网与市场行情快照。',
    showFewer: '▲ 收起部分来源',
    showAll: (count) => `▼ 查看全部 ${count} 条来源`,
    researchNotes: '研究说明',
    marketChart: '日 K 线',
    marketChartDesc: '服务端统一清洗、缓存并增量更新的 OHLCV 与成交量数据。',
    cacheHit: '命中缓存',
    cacheRefresh: '增量刷新',
    cacheMiss: '首次拉取',
    latestBar: '最新交易日',
    analysisFailed: '分析失败，请稍后重试。',
    startFailed: '创建研究任务失败。',
    navTitle: '投资研究台',
    newSearch: '重新检索',
    devConsole: '开发者视图',
    languageToggle: 'EN',
    heroEyebrow: 'AI 驱动的投资研究',
    heroTitle: ['输入公司名称，', '快速生成研究结果。'],
    heroSubtitle: '聚合市场、披露、新闻与官网信息，生成可追溯的投资研究摘要。',
    searchPlaceholder: '输入公司名称，例如：贵州茅台、宁德时代、腾讯控股…',
    analyzing: '分析中',
    analyzeButton: '开始分析 →',
    recentSearches: '最近检索',
  },
}

const SOURCE_BADGE = {
  news_article: 'NEWS',
  news: 'NEWS',
  disclosure_document: 'FILING',
  sec_filing: 'SEC',
  filing: 'SEC',
  financial_abstract: 'MARKET',
  website_page: 'WEB',
  website: 'WEB',
  price_data: 'MARKET',
  price: 'MARKET',
}

const SOURCE_COLOR = {
  news_article: '#1a6b45',
  news: '#1a6b45',
  disclosure_document: '#1a4d8a',
  sec_filing: '#1a4d8a',
  filing: '#1a4d8a',
  website_page: '#6a2d8a',
  website: '#6a2d8a',
  financial_abstract: '#8a5c1a',
  price_data: '#8a5c1a',
  price: '#8a5c1a',
}

function formatDate(iso, lang) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return ''
  }
}

function loadHistory() {
  try { return JSON.parse(localStorage.getItem('rh') || '[]') }
  catch { return [] }
}

function Spinner({ size = 16 }) {
  return (
    <span style={{
      display: 'inline-block',
      width: size, height: size,
      border: `2px solid var(--border)`,
      borderTopColor: 'var(--gold)',
      borderRadius: '50%',
      animation: 'spin .8s linear infinite',
      flexShrink: 0,
    }} />
  )
}

function SentimentBadge({ sentiment, copy }) {
  const labels = copy.sentiments
  const cfgMap = {
    positive: { label: labels.positive, bg: 'var(--positive-bg)', color: 'var(--positive)', dot: '#1a6b45' },
    negative: { label: labels.negative, bg: 'var(--negative-bg)', color: 'var(--negative)', dot: '#9b2335' },
    neutral: { label: labels.neutral, bg: 'var(--neutral-bg)', color: 'var(--neutral)', dot: '#4a4d62' },
    mixed: { label: labels.mixed, bg: 'var(--amber-bg)', color: 'var(--amber)', dot: '#8a5c1a' },
  }
  const cfg = cfgMap[sentiment] || cfgMap.neutral
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: cfg.bg, color: cfg.color,
      padding: '4px 12px', borderRadius: 999,
      fontSize: 13, fontWeight: 600, letterSpacing: '.03em',
    }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: cfg.dot, flexShrink: 0 }} />
      {cfg.label}
    </span>
  )
}

function ProgressPanel({ steps, moduleStatus, copy }) {
  const done = steps.filter((s) => ['completed', 'success', 'partial'].includes(moduleStatus[s.key])).length
  const pct  = Math.round((done / steps.length) * 100)

  return (
    <div style={{
      background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 16, padding: '28px 32px',
      boxShadow: 'var(--shadow-md)', maxWidth: 540, margin: '0 auto',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <span style={{ fontFamily: 'var(--serif)', fontSize: 18, color: 'var(--ink)' }}>{copy.researching}</span>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--gold)', fontWeight: 500 }}>{pct}%</span>
      </div>

      <div style={{ height: 3, background: 'var(--border)', borderRadius: 999, marginBottom: 24 }}>
        <div style={{
          height: '100%', background: 'var(--gold)', borderRadius: 999,
          width: `${pct}%`, transition: 'width .5s ease',
        }} />
      </div>

      {steps.map((step, i) => {
        const st = moduleStatus[step.key]
        const isDone = ['completed', 'success', 'partial'].includes(st)
        const isRunning = ['running', 'started', 'start'].includes(st)
        const isFailed = st === 'failed' || st === 'error'
        const isIdle = !st

        return (
          <div key={step.key} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '8px 0',
            borderBottom: i < steps.length - 1 ? '1px solid var(--cream-dark)' : 'none',
            opacity: isIdle ? .4 : 1,
            transition: 'opacity .3s',
          }}>
            <div style={{ width: 22, display: 'flex', justifyContent: 'center', flexShrink: 0 }}>
              {isDone && <span style={{ color: 'var(--positive)', fontSize: 16, fontWeight: 700 }}>✓</span>}
              {isRunning && <Spinner size={15} />}
              {isFailed && <span style={{ color: 'var(--negative)', fontSize: 16 }}>✗</span>}
              {isIdle && <span style={{ color: 'var(--border)', fontSize: 12 }}>○</span>}
            </div>
            <span style={{
              fontSize: 14,
              color: isDone ? 'var(--muted)' : isRunning ? 'var(--ink)' : isFailed ? 'var(--negative)' : 'var(--muted)',
              fontWeight: isRunning ? 600 : 400,
              textDecoration: isDone ? 'line-through' : 'none',
              textDecorationColor: 'var(--border)',
            }}>
              {step.label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function KeyFindingCard({ text }) {
  return (
    <div style={{
      background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 12, padding: '18px 20px',
      borderLeft: '3px solid var(--gold)',
      boxShadow: 'var(--shadow-sm)',
    }}>
      <p style={{ fontSize: 14.5, lineHeight: 1.55, color: 'var(--ink)' }}>{text}</p>
    </div>
  )
}

function RiskItem({ text }) {
  return (
    <li style={{
      display: 'flex', gap: 10, alignItems: 'flex-start',
      padding: '10px 0',
      borderBottom: '1px solid var(--cream-dark)',
      listStyle: 'none',
    }}>
      <span style={{ color: 'var(--negative)', fontSize: 13, marginTop: 2, flexShrink: 0 }}>▲</span>
      <span style={{ fontSize: 14.5, color: 'var(--ink)', lineHeight: 1.5 }}>{text}</span>
    </li>
  )
}

function SourceRow({ item, lang }) {
  const type  = item.source_type || item.module || ''
  const badge = SOURCE_BADGE[type] || type.toUpperCase().slice(0, 6)
  const color = SOURCE_COLOR[type] || 'var(--muted)'
  const date  = formatDate(item.date, lang)

  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', gap: 12,
      padding: '11px 0',
      borderBottom: '1px solid var(--cream-dark)',
    }}>
      <span style={{
        flexShrink: 0,
        background: color + '1a', color,
        fontSize: 10, fontWeight: 700, letterSpacing: '.07em',
        padding: '2px 7px', borderRadius: 4,
        fontFamily: 'var(--mono)',
      }}>
        {badge}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        {item.url ? (
          <a href={item.url} target="_blank" rel="noopener noreferrer"
            style={{ fontSize: 14, color: 'var(--ink)', fontWeight: 500 }}
            onMouseEnter={e => e.target.style.color = 'var(--gold)'}
            onMouseLeave={e => e.target.style.color = 'var(--ink)'}
          >
            {item.title}
          </a>
        ) : (
          <span style={{ fontSize: 14, color: 'var(--ink)', fontWeight: 500 }}>{item.title}</span>
        )}
        {item.snippet && (
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2, lineHeight: 1.4, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
            {item.snippet}
          </p>
        )}
      </span>
      {date && <span style={{ flexShrink: 0, fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>{date}</span>}
    </div>
  )
}

function MarketChartCard({ ohlcv, copy, lang }) {
  const chartRef = useRef(null)

  useEffect(() => {
    if (!chartRef.current || !ohlcv?.series?.bars?.length) return undefined

    const bars = ohlcv.series.bars
    const dates = bars.map((item) => item.date)
    const candleData = bars.map((item) => [item.open, item.close, item.low, item.high])
    const volumeData = bars.map((item) => ({
      value: item.volume ?? 0,
      itemStyle: {
        color: item.close >= item.open ? '#b42318' : '#12715b',
      },
    }))

    let chart
    let disposed = false
    let resize = null

    import('echarts').then((echarts) => {
      if (disposed || !chartRef.current) return
      chart = echarts.init(chartRef.current)
      chart.setOption({
        animation: false,
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        grid: [
          { left: 52, right: 24, top: 50, height: '56%' },
          { left: 52, right: 24, top: '74%', height: '16%' },
        ],
        xAxis: [
          {
            type: 'category',
            data: dates,
            boundaryGap: true,
            axisLine: { lineStyle: { color: '#d7d1c4' } },
            axisLabel: { color: '#6f6a61', hideOverlap: true },
            min: 'dataMin',
            max: 'dataMax',
          },
          {
            type: 'category',
            gridIndex: 1,
            data: dates,
            boundaryGap: true,
            axisLine: { lineStyle: { color: '#d7d1c4' } },
            axisLabel: { show: false },
            min: 'dataMin',
            max: 'dataMax',
          },
        ],
        yAxis: [
          {
            scale: true,
            axisLine: { show: false },
            splitLine: { lineStyle: { color: '#f0ebe2' } },
            axisLabel: { color: '#6f6a61' },
          },
          {
            gridIndex: 1,
            scale: true,
            axisLine: { show: false },
            splitLine: { show: false },
            axisLabel: {
              color: '#6f6a61',
              formatter: (value) => {
                if (value >= 100000000) return `${(value / 100000000).toFixed(1)}e8`
                if (value >= 10000) return `${(value / 10000).toFixed(0)}w`
                return `${Math.round(value)}`
              },
            },
          },
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1], start: 45, end: 100 },
          { type: 'slider', xAxisIndex: [0, 1], bottom: 10, height: 18, borderColor: '#e8dfcf' },
        ],
        series: [
          {
            type: 'candlestick',
            name: copy.marketChart,
            data: candleData,
            itemStyle: {
              color: '#b42318',
              color0: '#12715b',
              borderColor: '#b42318',
              borderColor0: '#12715b',
            },
          },
          {
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: volumeData,
            barMaxWidth: 10,
          },
        ],
      })

      resize = () => chart.resize()
      window.addEventListener('resize', resize)
    })

    return () => {
      disposed = true
      if (resize) window.removeEventListener('resize', resize)
      if (chart) chart.dispose()
    }
  }, [ohlcv, copy])

  if (!ohlcv?.series?.bars?.length) return null

  const cacheLabel = {
    hit: copy.cacheHit,
    refresh: copy.cacheRefresh,
    miss: copy.cacheMiss,
  }[ohlcv.series.cache_status] || ohlcv.series.cache_status

  return (
    <section className="fade-up-1" style={{ marginBottom: 20 }}>
      <div style={{
        background: 'var(--white)', border: '1px solid var(--border)',
        borderRadius: 16, padding: '24px 28px', boxShadow: 'var(--shadow-sm)',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
          <div>
            <h2 style={{
              fontFamily: 'var(--serif)', fontSize: 20, fontWeight: 600, color: 'var(--ink)',
              marginBottom: 4, display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ color: 'var(--gold)', fontSize: 14 }}>◫</span> {copy.marketChart}
            </h2>
            <p style={{ fontSize: 13, color: 'var(--muted)' }}>{copy.marketChartDesc}</p>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <span style={{
              fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--gold)',
              background: 'rgba(177, 137, 61, 0.10)', border: '1px solid rgba(177, 137, 61, 0.22)',
              borderRadius: 999, padding: '6px 10px',
            }}>
              {cacheLabel}
            </span>
            {ohlcv.series.cached_until && (
              <span style={{
                fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)',
                background: 'var(--cream-dark)', borderRadius: 999, padding: '6px 10px',
              }}>
                {copy.latestBar}: {formatDate(ohlcv.series.cached_until, lang)}
              </span>
            )}
          </div>
        </div>
        <div ref={chartRef} style={{ width: '100%', height: 420 }} />
      </div>
    </section>
  )
}

function Report({ data, copy, lang }) {
  const [showAll, setShowAll] = useState(false)
  if (!data) return null

  const sentiment = (data.overall_sentiment || 'neutral').toLowerCase()
  const evidence  = data.evidence || []
  const visEvidence = showAll ? evidence : evidence.slice(0, 8)

  return (
    <div className="fade-up" style={{ maxWidth: 760, margin: '0 auto', paddingBottom: 80 }}>
      <div style={{
        background: 'var(--white)', border: '1px solid var(--border)',
        borderRadius: 16, padding: '32px 36px', marginBottom: 20,
        boxShadow: 'var(--shadow-md)',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <h1 style={{ fontFamily: 'var(--serif)', fontSize: 32, fontWeight: 700, color: 'var(--ink)', lineHeight: 1.2 }}>
            {data.company_name}
          </h1>
          <SentimentBadge sentiment={sentiment} copy={copy} />
        </div>
        {data.summary && (
          <p style={{
            fontSize: 16, lineHeight: 1.7, color: 'var(--ink-light)',
            borderLeft: '3px solid var(--gold)', paddingLeft: 18,
            marginTop: 4,
          }}>
            {data.summary}
          </p>
        )}
      </div>

      {data.key_findings?.length > 0 && (
        <section className="fade-up-1" style={{ marginBottom: 20 }}>
          <h2 style={{
            fontFamily: 'var(--serif)', fontSize: 20, fontWeight: 600, color: 'var(--ink)',
            marginBottom: 14, paddingBottom: 10, borderBottom: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span style={{ color: 'var(--gold)', fontSize: 14 }}>◆</span> {copy.keyFindings}
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(310px, 1fr))', gap: 12 }}>
            {data.key_findings.map((f, i) => <KeyFindingCard key={i} text={f} />)}
          </div>
        </section>
      )}

      {data.risks?.length > 0 && (
        <section className="fade-up-2" style={{ marginBottom: 20 }}>
          <div style={{
            background: 'var(--white)', border: '1px solid var(--border)',
            borderRadius: 16, padding: '24px 28px', boxShadow: 'var(--shadow-sm)',
          }}>
            <h2 style={{
              fontFamily: 'var(--serif)', fontSize: 20, fontWeight: 600, color: 'var(--ink)',
              marginBottom: 12,
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ color: 'var(--negative)', fontSize: 14 }}>▲</span> {copy.riskFactors}
            </h2>
            <ul style={{ paddingLeft: 0 }}>
              {data.risks.map((r, i) => <RiskItem key={i} text={r} />)}
            </ul>
          </div>
        </section>
      )}

      {evidence.length > 0 && (
        <section className="fade-up-3" style={{ marginBottom: 20 }}>
          <div style={{
            background: 'var(--white)', border: '1px solid var(--border)',
            borderRadius: 16, padding: '24px 28px', boxShadow: 'var(--shadow-sm)',
          }}>
            <h2 style={{
              fontFamily: 'var(--serif)', fontSize: 20, fontWeight: 600, color: 'var(--ink)',
              marginBottom: 4,
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ color: 'var(--muted)', fontSize: 14 }}>≡</span> {copy.sources}
              <span style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 400, color: 'var(--muted)' }}>
                ({evidence.length})
              </span>
            </h2>
            <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>{copy.sourcesDesc}</p>
            {visEvidence.map((item, i) => <SourceRow key={i} item={item} lang={lang} />)}
            {evidence.length > 8 && (
              <button onClick={() => setShowAll(v => !v)} style={{
                marginTop: 14, fontSize: 13, color: 'var(--gold)', fontWeight: 600,
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '6px 0',
              }}>
                {showAll ? copy.showFewer : copy.showAll(evidence.length)}
              </button>
            )}
          </div>
        </section>
      )}

      {data.limitations?.length > 0 && (
        <section className="fade-up-4">
          <div style={{
            background: 'var(--cream-dark)', border: '1px solid var(--border)',
            borderRadius: 12, padding: '16px 20px',
          }}>
            <p style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>
              <strong style={{ color: 'var(--ink)' }}>{copy.researchNotes}: </strong>
              {data.limitations.join('  ·  ')}
            </p>
          </div>
        </section>
      )}
    </div>
  )
}

export default function UserPage({ lang = 'en', onToggleLang, onSwitchToDev }) {
  const copy = COPY[lang] || COPY.en
  const [query, setQuery] = useState('')
  const [phase, setPhase] = useState('home')
  const [moduleStatus, setModuleStatus] = useState({})
  const [report, setReport] = useState(null)
  const [ohlcv, setOhlcv] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [history, setHistory] = useState(loadHistory)

  const esRef = useRef(null)
  const pollRef = useRef(null)

  const stopListeners = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => () => stopListeners(), [stopListeners])

  const pushHistory = (company, jobId) => {
    const next = [{ company, jobId, ts: Date.now() }, ...loadHistory()].slice(0, 10)
    localStorage.setItem('rh', JSON.stringify(next))
    setHistory(next)
  }

  const loadJobReport = async (jobId) => {
    try {
      const job = await getJob(jobId)
      if (job.status === 'completed') {
        const reportData = job.report || (job.report_id ? await getReport(job.report_id) : null)
        if (reportData) {
          getOhlcv(jobId).then(setOhlcv).catch(() => setOhlcv(null))
          stopListeners()
          setReport(reportData)
          setPhase('result')
          return true
        }
      }
      if (job.status === 'failed') {
        stopListeners()
        setErrorMsg(job.error || copy.analysisFailed)
        setPhase('error')
        return true
      }
      return false
    } catch {
      return false
    }
  }

  const startJob = useCallback(async (companyName) => {
    setPhase('analyzing')
    setModuleStatus({})
    setReport(null)
    setOhlcv(null)
    setErrorMsg('')

    let job
    try {
      job = await createJob(companyName)
    } catch (e) {
      setErrorMsg(e.message || copy.startFailed)
      setPhase('error')
      return
    }

    const id = job.job_id || job.id
    pushHistory(companyName, id)

    esRef.current = openEventStream(id, (data) => {
      const type = data.type || data.event || ''
      const node = data.node || data.module || data.step || ''
      if (node) setModuleStatus(prev => ({ ...prev, [node]: type }))
      if (type === 'done' || type === 'job_completed' || data.status === 'completed' || data.report_id) {
        loadJobReport(id)
      }
    })

    pollRef.current = setInterval(async () => {
      const done = await loadJobReport(id)
      if (done) stopListeners()
    }, 4000)
  }, [copy.startFailed, stopListeners])

  const handleSubmit = (e) => {
    e?.preventDefault()
    if (query.trim()) startJob(query.trim())
  }

  const reset = () => {
    stopListeners()
    setPhase('home')
    setQuery('')
    setReport(null)
    setOhlcv(null)
    setModuleStatus({})
    setErrorMsg('')
  }

  const isHome = phase === 'home'
  const isAnalyz = phase === 'analyzing'
  const isResult = phase === 'result'
  const isError = phase === 'error'

  return (
    <div style={{ minHeight: '100vh', background: 'var(--cream)' }}>
      <nav style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: 'var(--white)', borderBottom: '1px solid var(--border)',
        padding: '0 32px', height: 56,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        boxShadow: 'var(--shadow-sm)',
      }}>
        <button onClick={reset} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
          <span style={{
            width: 28, height: 28, background: 'var(--ink)', borderRadius: 6,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--gold)', fontSize: 14, fontWeight: 700, flexShrink: 0,
          }}>R</span>
          <span style={{ fontFamily: 'var(--serif)', fontSize: 17, fontWeight: 600, color: 'var(--ink)' }}>
            {copy.navTitle}
          </span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={onToggleLang} style={{
            fontSize: 13, color: 'var(--muted)', fontWeight: 500,
            padding: '4px 10px', borderRadius: 6,
            border: '1px solid var(--border)',
          }}>
            {copy.languageToggle}
          </button>
          {isResult && (
            <button onClick={reset} style={{
              fontSize: 13, color: 'var(--gold)', fontWeight: 600,
              padding: '6px 14px', border: '1px solid var(--gold)',
              borderRadius: 8, background: 'transparent',
            }}>
              {copy.newSearch}
            </button>
          )}
          <button onClick={onSwitchToDev} style={{
            fontSize: 13, color: 'var(--muted)', fontWeight: 500,
            padding: '4px 10px', borderRadius: 6,
            border: '1px solid var(--border)',
          }}>
            {copy.devConsole}
          </button>
        </div>
      </nav>

      {!isResult && (
        <div style={{
          padding: isHome ? '80px 24px 40px' : '28px 24px',
          textAlign: 'center',
          transition: 'padding .3s ease',
        }}>
          {isHome && (
            <>
              <p className="fade-up" style={{
                fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 500,
                color: 'var(--gold)', letterSpacing: '.12em', textTransform: 'uppercase',
                marginBottom: 14,
              }}>
                {copy.heroEyebrow}
              </p>
              <h1 className="fade-up-1" style={{
                fontFamily: 'var(--serif)', fontSize: 'clamp(32px, 5vw, 52px)',
                fontWeight: 700, color: 'var(--ink)', lineHeight: 1.15,
                marginBottom: 10,
              }}>
                {copy.heroTitle[0]}<br />{copy.heroTitle[1]}
              </h1>
              <p className="fade-up-2" style={{
                fontSize: 17, color: 'var(--muted)', marginBottom: 36, maxWidth: 480, margin: '0 auto 36px',
              }}>
                {copy.heroSubtitle}
              </p>
            </>
          )}

          <form onSubmit={handleSubmit} className="fade-up-3" style={{
            display: 'flex', maxWidth: 560, margin: '0 auto',
            background: 'var(--white)', border: '1.5px solid var(--border)',
            borderRadius: 14, overflow: 'hidden',
            boxShadow: 'var(--shadow-md)',
            transition: 'border-color .2s',
          }}
            onFocus={e => e.currentTarget.style.borderColor = 'var(--gold)'}
            onBlur={e => e.currentTarget.style.borderColor = 'var(--border)'}
          >
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={copy.searchPlaceholder}
              disabled={isAnalyz}
              style={{
                flex: 1, padding: '16px 20px',
                border: 'none', outline: 'none',
                fontSize: 16, color: 'var(--ink)',
                background: 'transparent',
              }}
            />
            <button type="submit" disabled={isAnalyz || !query.trim()} style={{
              padding: '14px 26px',
              background: isAnalyz ? 'var(--cream-dark)' : 'var(--ink)',
              color: isAnalyz ? 'var(--muted)' : 'var(--white)',
              fontSize: 15, fontWeight: 600,
              border: 'none', cursor: isAnalyz ? 'default' : 'pointer',
              transition: 'background .2s',
              display: 'flex', alignItems: 'center', gap: 8,
              flexShrink: 0,
            }}>
              {isAnalyz ? <><Spinner size={14} /> {copy.analyzing}</> : copy.analyzeButton}
            </button>
          </form>

          {isError && (
            <div style={{
              marginTop: 20, padding: '14px 20px', maxWidth: 560, margin: '20px auto 0',
              background: 'var(--negative-bg)', border: '1px solid #e8c0c5',
              borderRadius: 10, color: 'var(--negative)', fontSize: 14,
            }}>
              {errorMsg}
            </div>
          )}
        </div>
      )}

      {isAnalyz && (
        <div style={{ padding: '8px 24px 60px' }}>
          <ProgressPanel steps={copy.steps} moduleStatus={moduleStatus} copy={copy} />
        </div>
      )}

      {isResult && report && (
        <div style={{ padding: '32px 24px' }}>
          <MarketChartCard ohlcv={ohlcv} copy={copy} lang={lang} />
          <Report data={report} copy={copy} lang={lang} />
        </div>
      )}

      {isHome && history.length > 0 && (
        <div style={{ maxWidth: 560, margin: '0 auto', padding: '0 24px 80px' }}>
          <p style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 12 }}>
            {copy.recentSearches}
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {history.map((h, i) => (
              <button key={i} onClick={() => { setQuery(h.company); startJob(h.company) }}
                style={{
                  padding: '7px 16px',
                  background: 'var(--white)', border: '1px solid var(--border)',
                  borderRadius: 999, fontSize: 13, color: 'var(--ink)',
                  cursor: 'pointer', transition: 'border-color .2s, color .2s',
                }}
                onMouseEnter={e => { e.target.style.borderColor = 'var(--gold)'; e.target.style.color = 'var(--gold)' }}
                onMouseLeave={e => { e.target.style.borderColor = 'var(--border)'; e.target.style.color = 'var(--ink)' }}
              >
                {h.company}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
