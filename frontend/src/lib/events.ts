import { API_BASE_URL, type InvestmentJobEvent } from "./contracts";

export function openInvestmentJobEvents(
  jobId: string,
  handlers: {
    onEvent: (payload: InvestmentJobEvent) => void;
    onError?: () => void;
  },
): EventSource {
  const source = new EventSource(`${API_BASE_URL}/investment-jobs/${jobId}/events`);
  source.onmessage = (event) => {
    const payload = JSON.parse(event.data) as InvestmentJobEvent;
    handlers.onEvent(payload);
  };
  source.onerror = () => {
    handlers.onError?.();
    source.close();
  };
  return source;
}
