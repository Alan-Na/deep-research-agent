import {
  API_BASE_URL,
  type EvidenceResponse,
  type HealthResponse,
  type InvestmentJobCreateResponse,
  type InvestmentJobListItem,
  type InvestmentJobStatusResponse,
  type InvestmentMemoResponse,
} from "./contracts";

type RequestErrorPayload = {
  detail?: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as RequestErrorPayload;
    throw new Error(payload.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function createJob(payload: { company_name: string }) {
  return request<InvestmentJobCreateResponse>("/investment-jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchJobs(limit: number) {
  return request<InvestmentJobListItem[]>(`/investment-jobs?limit=${limit}`);
}

export function fetchJobStatus(jobId: string) {
  return request<InvestmentJobStatusResponse>(`/investment-jobs/${jobId}`);
}

export function fetchMemo(memoId: string) {
  return request<InvestmentMemoResponse>(`/investment-memos/${memoId}`);
}

export function fetchEvidence(jobId: string, agent?: string, category?: string) {
  const params = new URLSearchParams();
  if (agent) params.set("agent", agent);
  if (category) params.set("category", category);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<EvidenceResponse>(`/investment-jobs/${jobId}/evidence${suffix}`);
}

export function fetchHealth() {
  return request<HealthResponse>("/health");
}
