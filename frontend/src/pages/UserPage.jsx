import { useState, useEffect, useRef, useCallback } from 'react'
import { createJob, deleteJob, getJob, getOhlcv, getReport, listJobs, openEventStream, chatWithReport } from '../api'

const COPY = {
  en: {
    steps: [
      { key: 'intake_brief', label: 'Building research brief' },
      { key: 'market', label: 'Analyzing market & valuation data' },
      { key: 'filing', label: 'Reading regulatory filings' },
      { key: 'message_intel', label: 'Reading official messages and news events' },
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
    marketChartDesc: 'Recent 60 trading days of normalized OHLCV bars with MA5, MA10, MA20 and volume overlay. Scroll horizontally to inspect earlier bars.',
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
    openPrevious: 'Open',
    deleteSearch: 'Delete',
    loadingPrevious: 'Opening saved result…',
    chatOpen: 'Ask',
    chatClose: 'Exit Chat',
    chatTitle: 'Company Q&A',
    chatIntro: 'Ask follow-up questions about this company. Answers use only the completed research context.',
    chatPlaceholder: 'Ask about valuation, filings, news signals…',
    chatSend: 'Send',
    chatThinking: 'Reading context…',
    chatError: 'Failed to answer. Please try again.',
    chatSources: 'Sources',
  },
  zh: {
    steps: [
      { key: 'intake_brief', label: '构建研究任务与公司画像' },
      { key: 'market', label: '分析市场与估值数据' },
      { key: 'filing', label: '读取公告与财务披露' },
      { key: 'message_intel', label: '分析消息面：官网、IR 与新闻事件' },
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
    marketChartDesc: '近 60 个交易日的 OHLCV、MA5、MA10、MA20 与成交量。图表固定大小，可左右滑动查看早期 K 线。',
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
    openPrevious: '查看',
    deleteSearch: '删除',
    loadingPrevious: '正在打开历史结果…',
    chatOpen: '追问',
    chatClose: '退出对话',
    chatTitle: '公司研究问答',
    chatIntro: '可以围绕这家公司继续追问。回答只使用本次研究链路生成的上下文。',
    chatPlaceholder: '追问估值、财报、新闻信号…',
    chatSend: '发送',
    chatThinking: '正在读取上下文…',
    chatError: '回答失败，请稍后重试。',
    chatSources: '来源',
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
    let normalized = iso
    if (typeof iso === 'string' && /^\d{8}$/.test(iso)) {
      normalized = `${iso.slice(0, 4)}-${iso.slice(4, 6)}-${iso.slice(6, 8)}`
    }
    const value = new Date(normalized)
    if (Number.isNaN(value.getTime()) || value.getUTCFullYear() < 2000) {
      return ''
    }
    return value.toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return ''
  }
}

function loadHistory() {
  try {
    const items = JSON.parse(localStorage.getItem('rh') || '[]')
    return Array.isArray(items) ? items.filter(item => item?.company) : []
  }
  catch { return [] }
}

function saveHistory(items) {
  const compacted = []
  const seen = new Set()
  for (const item of items || []) {
    if (!item?.company) continue
    const key = item.jobId || item.job_id || item.company
    if (seen.has(key)) continue
    seen.add(key)
    compacted.push({
      company: item.company || item.company_name,
      jobId: item.jobId || item.job_id || item.id || null,
      reportId: item.reportId || item.report_id || item.memo_id || null,
      status: item.status || null,
      ts: item.ts || Date.now(),
    })
  }
  const next = compacted.slice(0, 10)
  localStorage.setItem('rh', JSON.stringify(next))
  return next
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

function movingAverage(values, windowSize) {
  return values.map((_, index) => {
    if (index < windowSize - 1) return null
    const window = values.slice(index - windowSize + 1, index + 1)
    if (window.some((value) => value == null || Number.isNaN(value))) return null
    const average = window.reduce((sum, value) => sum + value, 0) / windowSize
    return Number(average.toFixed(4))
  })
}

function MarketChartCard({ ohlcv, copy, lang }) {
  const chartRef = useRef(null)

  useEffect(() => {
    if (!chartRef.current || !ohlcv?.series?.bars?.length) return undefined

    const bars = ohlcv.series.bars.slice(-60)
    const dates = bars.map((item) => item.date)
    const candleData = bars.map((item) => [item.open, item.close, item.low, item.high])
    const closeValues = bars.map((item) => Number(item.close))
    const ma5 = movingAverage(closeValues, 5)
    const ma10 = movingAverage(closeValues, 10)
    const ma20 = movingAverage(closeValues, 20)
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
        color: ['#b42318', '#d97706', '#2563eb', '#7c3aed', '#8a7f6d'],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          borderColor: '#e8dfcf',
          backgroundColor: 'rgba(255, 255, 255, 0.96)',
          textStyle: { color: '#2f2a23' },
        },
        legend: {
          top: 16,
          right: 24,
          itemWidth: 18,
          itemHeight: 8,
          textStyle: { color: '#6f6a61', fontSize: 12 },
          data: [copy.marketChart, 'MA5', 'MA10', 'MA20'],
        },
        grid: [
          { left: 52, right: 24, top: 58, height: '54%' },
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
            barWidth: 8,
          },
          {
            type: 'line',
            name: 'MA5',
            data: ma5,
            smooth: true,
            showSymbol: false,
            lineStyle: { width: 1.6, color: '#d97706' },
            connectNulls: false,
          },
          {
            type: 'line',
            name: 'MA10',
            data: ma10,
            smooth: true,
            showSymbol: false,
            lineStyle: { width: 1.6, color: '#2563eb' },
            connectNulls: false,
          },
          {
            type: 'line',
            name: 'MA20',
            data: ma20,
            smooth: true,
            showSymbol: false,
            lineStyle: { width: 1.6, color: '#7c3aed' },
            connectNulls: false,
          },
          {
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: volumeData,
            barWidth: 8,
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
  const visibleBars = ohlcv.series.bars.slice(-60)
  const chartWidth = Math.max(900, visibleBars.length * 16 + 120)

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
        <div style={{
          overflowX: 'auto',
          overflowY: 'hidden',
          border: '1px solid var(--border)',
          borderRadius: 12,
          background: 'var(--white)',
        }}>
          <div ref={chartRef} style={{ width: chartWidth, height: 420 }} />
        </div>
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

function ChatPanel({ open, onClose, report, copy }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const bodyRef = useRef(null)

  useEffect(() => {
    setMessages([])
    setInput('')
    setError('')
  }, [report?.report_id])

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [messages, loading])

  if (!open || !report?.report_id) return null

  const send = async (e) => {
    e?.preventDefault()
    const question = input.trim()
    if (!question || loading) return
    const history = messages.map((item) => ({ role: item.role, content: item.content }))
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setInput('')
    setError('')
    setLoading(true)
    try {
      const response = await chatWithReport(report.report_id, question, history)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: response.answer || '',
          sources: response.sources || [],
          rejected: response.rejected,
        },
      ])
    } catch {
      setError(copy.chatError)
    } finally {
      setLoading(false)
    }
  }

  return (
    <aside style={{
      position: 'fixed', right: 24, top: 72, bottom: 24, width: 'min(420px, calc(100vw - 32px))',
      zIndex: 120, background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 14, boxShadow: 'var(--shadow-md)', display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '16px 18px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12,
      }}>
        <div>
          <h2 style={{ fontFamily: 'var(--serif)', fontSize: 19, color: 'var(--ink)', marginBottom: 4 }}>
            {copy.chatTitle}
          </h2>
          <p style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.45 }}>{copy.chatIntro}</p>
        </div>
        <button onClick={onClose} style={{
          border: '1px solid var(--border)', borderRadius: 8, padding: '5px 9px',
          color: 'var(--muted)', fontSize: 12, flexShrink: 0,
        }}>
          {copy.chatClose}
        </button>
      </div>

      <div ref={bodyRef} style={{ flex: 1, overflowY: 'auto', padding: 16, background: 'var(--cream)' }}>
        {messages.length === 0 && (
          <div style={{
            background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 12,
            padding: 14, color: 'var(--muted)', fontSize: 13.5, lineHeight: 1.55,
          }}>
            {copy.chatIntro}
          </div>
        )}
        {messages.map((message, index) => {
          const isUser = message.role === 'user'
          return (
            <div key={index} style={{
              display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start',
              marginBottom: 12,
            }}>
              <div style={{
                maxWidth: '88%',
                background: isUser ? 'var(--ink)' : 'var(--white)',
                color: isUser ? 'var(--white)' : 'var(--ink)',
                border: isUser ? 'none' : '1px solid var(--border)',
                borderRadius: 12,
                padding: '11px 13px',
                fontSize: 14,
                lineHeight: 1.55,
                whiteSpace: 'pre-wrap',
                boxShadow: isUser ? 'none' : 'var(--shadow-sm)',
              }}>
                {message.content}
                {!isUser && message.sources?.length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 9, borderTop: '1px solid var(--cream-dark)' }}>
                    <p style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 700, marginBottom: 5 }}>
                      {copy.chatSources}
                    </p>
                    {message.sources.slice(0, 3).map((source, i) => (
                      <div key={i} style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.4, marginTop: 4 }}>
                        {source.url ? (
                          <a href={source.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--gold)', fontWeight: 600 }}>
                            {source.title}
                          </a>
                        ) : (
                          <strong style={{ color: 'var(--muted)' }}>{source.title}</strong>
                        )}
                        {source.snippet && <span> · {source.snippet}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )
        })}
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--muted)', fontSize: 13 }}>
            <Spinner size={14} /> {copy.chatThinking}
          </div>
        )}
        {error && <p style={{ color: 'var(--negative)', fontSize: 13, marginTop: 8 }}>{error}</p>}
      </div>

      <form onSubmit={send} style={{
        padding: 12, borderTop: '1px solid var(--border)', display: 'flex', gap: 8,
        background: 'var(--white)',
      }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={copy.chatPlaceholder}
          disabled={loading}
          style={{
            flex: 1, minWidth: 0, border: '1px solid var(--border)', borderRadius: 10,
            padding: '10px 12px', fontSize: 14, color: 'var(--ink)', outline: 'none',
          }}
        />
        <button type="submit" disabled={loading || !input.trim()} style={{
          background: loading || !input.trim() ? 'var(--cream-dark)' : 'var(--ink)',
          color: loading || !input.trim() ? 'var(--muted)' : 'var(--white)',
          borderRadius: 10, padding: '9px 13px', fontSize: 13, fontWeight: 700,
          flexShrink: 0,
        }}>
          {copy.chatSend}
        </button>
      </form>
    </aside>
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
  const [chatOpen, setChatOpen] = useState(false)
  const [openingJobId, setOpeningJobId] = useState(null)

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

  useEffect(() => {
    let active = true
    listJobs(10)
      .then((items) => {
        if (!active || !Array.isArray(items)) return
        const serverHistory = items
          .filter((item) => item?.job_id && item?.company_name)
          .map((item) => ({
            company: item.company_name,
            jobId: item.job_id,
            reportId: item.report_id || item.memo_id || null,
            status: item.status,
            ts: item.created_at ? new Date(item.created_at).getTime() : Date.now(),
          }))
        setHistory(saveHistory([...serverHistory, ...loadHistory()]))
      })
      .catch(() => {})
    return () => { active = false }
  }, [])

  const pushHistory = (company, jobId) => {
    const next = saveHistory([
      { company, jobId, ts: Date.now(), status: 'running' },
      ...loadHistory().filter((item) => item.jobId !== jobId && item.company !== company),
    ])
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
    setChatOpen(false)
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

  const openHistoryItem = async (item) => {
    if (!item?.jobId) {
      if (item?.company) startJob(item.company)
      return
    }
    stopListeners()
    setOpeningJobId(item.jobId)
    setQuery(item.company || '')
    setPhase('analyzing')
    setModuleStatus({})
    setReport(null)
    setOhlcv(null)
    setChatOpen(false)
    setErrorMsg('')

    const done = await loadJobReport(item.jobId)
    if (done) {
      setOpeningJobId(null)
      return
    }

    esRef.current = openEventStream(item.jobId, (data) => {
      const type = data.type || data.event || ''
      const node = data.node || data.module || data.step || ''
      if (node) setModuleStatus(prev => ({ ...prev, [node]: type }))
      if (type === 'done' || type === 'job_completed' || data.status === 'completed' || data.report_id || data.memo_id) {
        loadJobReport(item.jobId).finally(() => setOpeningJobId(null))
      }
    })

    pollRef.current = setInterval(async () => {
      const completed = await loadJobReport(item.jobId)
      if (completed) {
        setOpeningJobId(null)
        stopListeners()
      }
    }, 4000)
  }

  const removeHistoryItem = async (item) => {
    const next = saveHistory(loadHistory().filter((entry) => {
      if (item.jobId) return entry.jobId !== item.jobId
      return entry.company !== item.company
    }))
    setHistory(next)
    if (item.jobId) {
      await deleteJob(item.jobId).catch(() => {})
      if (report?.job_id === item.jobId) reset()
    }
  }

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
    setChatOpen(false)
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
            <>
              <button onClick={() => setChatOpen((value) => !value)} style={{
                fontSize: 13, color: chatOpen ? 'var(--white)' : 'var(--gold)', fontWeight: 600,
                padding: '6px 14px', border: '1px solid var(--gold)',
                borderRadius: 8, background: chatOpen ? 'var(--gold)' : 'transparent',
              }}>
                {chatOpen ? copy.chatClose : copy.chatOpen}
              </button>
              <button onClick={reset} style={{
                fontSize: 13, color: 'var(--gold)', fontWeight: 600,
                padding: '6px 14px', border: '1px solid var(--gold)',
                borderRadius: 8, background: 'transparent',
              }}>
                {copy.newSearch}
              </button>
            </>
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
          <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} report={report} copy={copy} />
        </div>
      )}

      {isHome && history.length > 0 && (
        <div style={{ maxWidth: 560, margin: '0 auto', padding: '0 24px 80px' }}>
          <p style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 12 }}>
            {copy.recentSearches}
          </p>
          <div style={{ display: 'grid', gap: 8 }}>
            {history.map((h, i) => (
              <div key={h.jobId || `${h.company}-${i}`} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                background: 'var(--white)', border: '1px solid var(--border)',
                borderRadius: 12, padding: '8px 10px',
                boxShadow: 'var(--shadow-sm)',
              }}>
                <button
                  onClick={() => openHistoryItem(h)}
                  disabled={openingJobId === h.jobId}
                  style={{
                    flex: 1, minWidth: 0, textAlign: 'left',
                    color: 'var(--ink)', cursor: openingJobId === h.jobId ? 'default' : 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 14, fontWeight: 600 }}>
                    {h.company}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--gold)', flexShrink: 0 }}>
                    {openingJobId === h.jobId ? copy.loadingPrevious : copy.openPrevious}
                  </span>
                </button>
                <button
                  onClick={() => removeHistoryItem(h)}
                  title={copy.deleteSearch}
                  aria-label={copy.deleteSearch}
                  style={{
                    width: 28, height: 28, borderRadius: 8,
                    border: '1px solid var(--border)', color: 'var(--muted)',
                    fontSize: 16, lineHeight: 1, flexShrink: 0,
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
