export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export type HealthResponse = {
  status: string;
  database: string;
  redis: string;
};

export type InvestmentJobCreateResponse = {
  job_id: string;
  status: string;
  created_at: string;
};

export type InvestmentJobListItem = {
  job_id: string;
  company_name: string;
  market: string;
  status: string;
  created_at: string;
  memo_id?: string | null;
};

export type AgentRun = {
  agent_name: string;
  status: string;
  current_step?: string | null;
  tool_calls_count: number;
  summary?: string | null;
  warning?: string | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
};

export type InvestmentJobStatusResponse = {
  job_id: string;
  company_name: string;
  market: string;
  status: string;
  research_brief?: Record<string, unknown> | null;
  agent_runs: AgentRun[];
  warnings: string[];
  memo_id?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type EvidenceItem = {
  id: string;
  agent_name: string;
  source_type: string;
  category: string;
  title: string;
  url?: string | null;
  published_at?: string | null;
  content: string;
  metadata: Record<string, unknown>;
};

export type EvidenceResponse = {
  job_id: string;
  items: EvidenceItem[];
};

export type MemoEvent = {
  title: string;
  category: string;
  horizon: string;
  sentiment: string;
  impact_score: number;
  confidence_score: number;
  date?: string | null;
  summary: string;
  source_ids: string[];
};

export type MemoCitation = {
  claim: string;
  agent_name: string;
  source_type: string;
  category: string;
  title: string;
  snippet: string;
  url?: string | null;
  date?: string | null;
  score: number;
};

export type CriticSummary = {
  citation_coverage_score: number;
  freshness_score: number;
  consistency_score: number;
  duplicate_event_bias_score: number;
  stance_supported: boolean;
  warnings: string[];
};

export type MarketSnapshot = {
  last_price?: number | null;
  provider?: string | null;
  as_of?: string | null;
  returns?: Record<string, number | null>;
  volatility?: Record<string, number | null>;
  valuation?: Record<string, number | null>;
};

export type InvestmentMemo = {
  company_name: string;
  market: string;
  instrument: {
    symbol?: string | null;
    display_name?: string | null;
    exchange?: string | null;
    industry?: string | null;
    website_url?: string | null;
  };
  stance: string;
  stance_confidence: number;
  thesis: string;
  bull_case: string[];
  bear_case: string[];
  key_catalysts: string[];
  key_risks: string[];
  valuation_view: string;
  market_snapshot?: MarketSnapshot | null;
  watch_items: string[];
  limitations: string[];
  agent_outputs: Record<string, Record<string, unknown>>;
  events: MemoEvent[];
  citations: MemoCitation[];
  critic_summary?: CriticSummary | null;
};

export type InvestmentMemoResponse = {
  memo_id: string;
  job_id: string;
  memo: InvestmentMemo;
};

export type InvestmentJobEvent =
  | { type: "snapshot"; status: InvestmentJobStatusResponse }
  | { type: "job_created"; job_id: string; status: string; company_name: string; created_at: string }
  | { type: "job_started"; company_name: string; market: string; research_brief: Record<string, unknown> }
  | {
      type: "agent_started" | "tool_called" | "observation_recorded" | "agent_completed";
      agent_name: string;
      status?: string;
      current_step?: string;
      tool_calls_count?: number;
      summary?: string;
      warning?: string;
      error?: string;
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
    }
  | { type: "critic_warning"; warning: string }
  | { type: "memo_ready"; stance: string; stance_confidence: number; citation_count: number }
  | { type: "job_status"; status: string; memo_id?: string; timestamp: string }
  | { type: "job_failed"; status: string; error: string; timestamp: string }
  | Record<string, unknown>;
