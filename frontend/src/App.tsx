import { useEffect, useMemo, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createJob, fetchEvidence, fetchHealth, fetchJobs, fetchJobStatus, fetchMemo } from "./lib/api";
import { openInvestmentJobEvents } from "./lib/events";
import type {
  AgentRun,
  EvidenceItem,
  InvestmentJobCreateResponse,
  InvestmentJobEvent,
  InvestmentJobStatusResponse,
  InvestmentMemoResponse,
} from "./lib/contracts";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard developerMode={false} />} />
      <Route path="/developer" element={<Dashboard developerMode={true} />} />
    </Routes>
  );
}

function Dashboard({ developerMode }: { developerMode: boolean }) {
  const queryClient = useQueryClient();
  const [companyName, setCompanyName] = useState("");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [events, setEvents] = useState<InvestmentJobEvent[]>([]);

  const jobsQuery = useQuery({
    queryKey: ["investment-jobs"],
    queryFn: () => fetchJobs(12),
    refetchInterval: 8000,
  });

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 10000,
  });

  const activeJobQuery = useQuery({
    queryKey: ["investment-job", activeJobId],
    queryFn: () => fetchJobStatus(activeJobId!),
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => {
      const current = query.state.data as InvestmentJobStatusResponse | undefined;
      return current && ["partial", "succeeded", "failed"].includes(current.status) ? false : 4000;
    },
  });

  const memoQuery = useQuery({
    queryKey: ["investment-memo", activeJobQuery.data?.memo_id],
    queryFn: () => fetchMemo(activeJobQuery.data!.memo_id!),
    enabled: Boolean(activeJobQuery.data?.memo_id),
  });

  const evidenceQuery = useQuery({
    queryKey: ["evidence", activeJobId],
    queryFn: () => fetchEvidence(activeJobId!),
    enabled: Boolean(activeJobId),
  });

  const createJobMutation = useMutation({
    mutationFn: createJob,
    onSuccess: (job: InvestmentJobCreateResponse) => {
      setActiveJobId(job.job_id);
      setEvents([]);
      queryClient.invalidateQueries({ queryKey: ["investment-jobs"] });
    },
  });

  useEffect(() => {
    if (!jobsQuery.data?.length || activeJobId) {
      return;
    }
    setActiveJobId(jobsQuery.data[0].job_id);
  }, [jobsQuery.data, activeJobId]);

  useEffect(() => {
    if (!activeJobId) {
      return;
    }
    const eventSource = openInvestmentJobEvents(activeJobId, {
      onEvent: (payload) => {
      setEvents((current) => [payload, ...current].slice(0, 40));
      queryClient.invalidateQueries({ queryKey: ["investment-job", activeJobId] });
      queryClient.invalidateQueries({ queryKey: ["evidence", activeJobId] });
      if ("memo_id" in payload && payload.memo_id) {
        queryClient.invalidateQueries({ queryKey: ["investment-memo", payload.memo_id] });
      }
      },
    });
    return () => eventSource.close();
  }, [activeJobId, queryClient]);

  const status = activeJobQuery.data;
  const memo = memoQuery.data?.memo;

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 px-4 py-6 lg:px-8">
      <header className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-panel backdrop-blur">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate">Investment Research V2</p>
            <h1 className="mt-2 text-3xl font-semibold text-ink lg:text-5xl">ReAct 多 Agent 投资研究平台</h1>
            <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
              以 A 股为主，四个研究 agent 并行采集市场、披露、官网与新闻风险，再由 Critic &
              Output Agent 生成带引用的投资 Memo。
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to={developerMode ? "/" : "/developer"}
              className="rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-ink transition hover:border-accent hover:text-accent"
            >
              {developerMode ? "用户视图" : "开发者视图"}
            </Link>
            <div className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-white">
              {healthQuery.data?.status === "ok" ? "系统健康" : "系统降级"}
            </div>
          </div>
        </div>
      </header>

      <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-panel">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate">新建任务</p>
          <div className="mt-4 flex flex-col gap-3 lg:flex-row">
            <input
              value={companyName}
              onChange={(event) => setCompanyName(event.target.value)}
              placeholder="输入公司名或证券代码，例如 贵州茅台 / 600519"
              className="min-h-14 flex-1 rounded-2xl border border-slate-200 px-4 text-lg outline-none transition focus:border-accent"
            />
            <button
              disabled={!companyName.trim() || createJobMutation.isPending}
              onClick={() => createJobMutation.mutate({ company_name: companyName.trim() })}
              className="min-h-14 rounded-2xl bg-ink px-6 text-white disabled:opacity-50"
            >
              {createJobMutation.isPending ? "提交中..." : "创建研究任务"}
            </button>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            <StatCard label="Database" value={healthQuery.data?.database || "checking"} />
            <StatCard label="Redis" value={healthQuery.data?.redis || "checking"} />
            <StatCard label="最近任务数" value={String(jobsQuery.data?.length || 0)} />
          </div>
        </div>

        <aside className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-panel">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate">Watchlist / Recent Jobs</p>
          <ul className="mt-4 grid gap-3">
            {jobsQuery.data?.map((job) => (
              <li key={job.job_id}>
                <button
                  onClick={() => setActiveJobId(job.job_id)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                    activeJobId === job.job_id ? "border-accent bg-teal-50" : "border-slate-200 bg-white hover:border-accent/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-ink">{job.company_name}</span>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium uppercase text-slate-600">{job.status}</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    {job.market} · {job.created_at}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      </section>

      <section className="grid gap-6 lg:grid-cols-[0.92fr_1.08fr]">
        <div className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-panel">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate">执行状态</p>
          {status ? (
            <div className="mt-4 grid gap-4">
              <JobHero status={status} />
              <div className="grid gap-3">
                {status.agent_runs.map((agentRun) => (
                  <AgentCard key={agentRun.agent_name} agentRun={agentRun} />
                ))}
              </div>
              <div>
                <h3 className="text-lg font-medium text-ink">实时 Trace</h3>
                <ul className="mt-3 grid max-h-[26rem] gap-3 overflow-auto">
                  {events.map((event, index) => (
                    <li key={index} className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-sm text-slate-600">
                      <pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify(event, null, 2)}</pre>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <EmptyState text="创建任务或从最近任务中选择一个，即可查看四个 agent 的并行执行状态。" />
          )}
        </div>

        <div className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-panel">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate">
            {developerMode ? "Developer JSON" : "Investment Memo"}
          </p>
          {memo ? (
            developerMode ? (
              <pre className="mt-4 overflow-auto rounded-3xl bg-slate-950 p-5 text-sm text-slate-100">
                {JSON.stringify({ status, memo: memoQuery.data, evidence: evidenceQuery.data }, null, 2)}
              </pre>
            ) : (
              <MemoPanel memo={memoQuery.data!} evidenceItems={evidenceQuery.data?.items || []} />
            )
          ) : (
            <EmptyState text="当前任务还没有生成最终 Memo。" />
          )}
        </div>
      </section>
    </div>
  );
}

function JobHero({ status }: { status: InvestmentJobStatusResponse }) {
  return (
    <div className="rounded-3xl bg-ink p-5 text-white">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm text-white/70">{status.company_name}</p>
          <h2 className="text-2xl font-semibold">
            {status.status} · {status.market}
          </h2>
          <p className="mt-2 text-sm text-white/70">
            {status.research_brief?.instrument
              ? `${String((status.research_brief.instrument as Record<string, unknown>).symbol || "未解析代码")}`
              : "等待 brief"}
          </p>
        </div>
        <div className="text-right text-sm text-white/70">
          <p>Created</p>
          <p>{status.created_at}</p>
        </div>
      </div>
      {status.warnings.length ? (
        <ul className="mt-4 grid gap-2 text-sm text-amber-100">
          {status.warnings.slice(0, 3).map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function AgentCard({ agentRun }: { agentRun: AgentRun }) {
  return (
    <div className="rounded-2xl border border-slate-200 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium capitalize">{agentRun.agent_name}</h3>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs uppercase text-slate-600">{agentRun.status}</span>
      </div>
      <p className="mt-2 text-sm text-slate-600">{agentRun.summary || agentRun.warning || "等待 agent 输出。"}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
        <span>step: {agentRun.current_step || "n/a"}</span>
        <span>tools: {agentRun.tool_calls_count}</span>
        {agentRun.duration_ms ? <span>{agentRun.duration_ms} ms</span> : null}
      </div>
    </div>
  );
}

function MemoPanel({ memo, evidenceItems }: { memo: InvestmentMemoResponse; evidenceItems: EvidenceItem[] }) {
  const investmentMemo = memo.memo;
  const topEvidence = useMemo(() => evidenceItems.slice(0, 8), [evidenceItems]);

  return (
    <div className="mt-4 grid gap-5">
      <div className="rounded-3xl bg-gradient-to-br from-ink to-accent p-6 text-white">
        <p className="text-sm uppercase tracking-[0.24em] text-white/70">
          {investmentMemo.company_name} · {investmentMemo.market}
        </p>
        <h2 className="mt-2 text-3xl font-semibold">
          {investmentMemo.stance} · confidence {investmentMemo.stance_confidence.toFixed(2)}
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-white/85">{investmentMemo.thesis}</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <ListCard title="Bull Case" items={investmentMemo.bull_case} />
        <ListCard title="Bear Case" items={investmentMemo.bear_case} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <ListCard title="Catalysts" items={investmentMemo.key_catalysts} />
        <ListCard title="Risks" items={investmentMemo.key_risks} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <SingleTextCard title="Valuation View" text={investmentMemo.valuation_view} />
        <ListCard title="Watch Items" items={investmentMemo.watch_items} />
      </div>

      {investmentMemo.market_snapshot ? (
        <div className="rounded-3xl border border-slate-200 p-5">
          <h3 className="text-xl font-semibold text-ink">Market Snapshot</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <StatCard label="Last Price" value={String(investmentMemo.market_snapshot.last_price ?? "n/a")} />
            <StatCard label="1M Return" value={String(investmentMemo.market_snapshot.returns?.one_month_pct ?? "n/a")} />
            <StatCard label="20D Vol" value={String(investmentMemo.market_snapshot.volatility?.realized_20d_pct ?? "n/a")} />
            <StatCard label="PE / PB" value={`${investmentMemo.market_snapshot.valuation?.pe_ttm ?? "n/a"} / ${investmentMemo.market_snapshot.valuation?.pb ?? "n/a"}`} />
          </div>
        </div>
      ) : null}

      <div className="rounded-3xl border border-slate-200 p-5">
        <h3 className="text-xl font-semibold text-ink">事件时间线</h3>
        <ul className="mt-4 grid gap-3">
          {investmentMemo.events.length ? (
            investmentMemo.events.map((event, index) => (
              <li key={`${event.title}-${index}`} className="rounded-2xl bg-slate-50 p-4">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>{event.date || "undated"}</span>
                  <span>{event.category}</span>
                  <span>{event.horizon}</span>
                  <span>impact {event.impact_score.toFixed(2)}</span>
                  <span>confidence {event.confidence_score.toFixed(2)}</span>
                </div>
                <p className="mt-2 font-medium text-ink">{event.title}</p>
                <p className="mt-1 text-sm text-slate-600">{event.summary}</p>
              </li>
            ))
          ) : (
            <li className="text-sm text-slate-400">No event timeline.</li>
          )}
        </ul>
      </div>

      <div className="rounded-3xl border border-slate-200 p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-xl font-semibold text-ink">Citation Explorer</h3>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium uppercase text-slate-600">
            {investmentMemo.citations.length} linked sources
          </span>
        </div>
        <ul className="mt-4 grid gap-3">
          {investmentMemo.citations.map((citation, index) => (
            <li key={`${citation.claim}-${index}`} className="rounded-2xl bg-slate-50 p-4">
              <p className="text-sm font-medium text-ink">{citation.claim}</p>
              <p className="mt-2 text-sm text-slate-600">{citation.snippet}</p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                <span>{citation.agent_name}</span>
                <span>{citation.source_type}</span>
                <span>{citation.category}</span>
                <span>{citation.date || "undated"}</span>
                <span>score {citation.score.toFixed(2)}</span>
                {citation.url ? (
                  <a href={citation.url} target="_blank" rel="noreferrer" className="text-accent underline">
                    source
                  </a>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <ListCard title="Limitations" items={investmentMemo.limitations} />
        <ListCard title="Evidence Explorer" items={topEvidence.map((item) => `${String(item.agent_name)} | ${String(item.title)} | ${String(item.category)}`)} />
      </div>

      {investmentMemo.critic_summary ? (
        <div className="rounded-3xl border border-slate-200 p-5">
          <h3 className="text-xl font-semibold text-ink">Critic Summary</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <StatCard label="Citation" value={investmentMemo.critic_summary.citation_coverage_score.toFixed(2)} />
            <StatCard label="Freshness" value={investmentMemo.critic_summary.freshness_score.toFixed(2)} />
            <StatCard label="Consistency" value={investmentMemo.critic_summary.consistency_score.toFixed(2)} />
            <StatCard label="Dup Bias" value={investmentMemo.critic_summary.duplicate_event_bias_score.toFixed(2)} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ListCard({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-3xl border border-slate-200 p-5">
      <h3 className="text-xl font-semibold text-ink">{title}</h3>
      <ul className="mt-3 grid gap-3">
        {items.length ? (
          items.map((item, index) => (
            <li key={index} className="text-sm leading-7 text-slate-600">
              {item}
            </li>
          ))
        ) : (
          <li className="text-sm text-slate-400">No data.</li>
        )}
      </ul>
    </div>
  );
}

function SingleTextCard({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-3xl border border-slate-200 p-5">
      <h3 className="text-xl font-semibold text-ink">{title}</h3>
      <p className="mt-3 text-sm leading-7 text-slate-600">{text}</p>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{label}</p>
      <p className="mt-2 text-lg font-semibold text-ink">{value}</p>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="mt-4 rounded-3xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500">{text}</div>;
}

export default App;
