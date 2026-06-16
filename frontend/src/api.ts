const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

export type Project = {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
};

export type ProjectDetail = Project & {
  totals: {
    money_in: string;
    money_out: string;
    net: string;
  };
};

export type RawEntry = {
  id: number;
  project_id: number;
  text: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ExtractedEvent = {
  id: number;
  project_id: number;
  raw_entry_id: number;
  type: EventType;
  counterparty_name: string | null;
  counterparty_type: CounterpartyType;
  amount: string | null;
  description: string | null;
  event_date: string | null;
  confidence: string | null;
  status: "PENDING" | "CONFIRMED" | "DISCARDED";
  created_at: string;
  updated_at: string;
};

export type EventType = "MONEY_IN" | "MONEY_OUT" | "PURCHASE" | "NOTE";
export type CounterpartyType = "CUSTOMER" | "VENDOR" | "WORKER" | "UNKNOWN";

export type EventUpdate = Pick<
  ExtractedEvent,
  "type" | "counterparty_name" | "counterparty_type" | "amount" | "description" | "event_date"
>;

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  getProject: (projectId: number) => request<ProjectDetail>(`/projects/${projectId}`),
  createRawEntry: (projectId: number, text: string) =>
    request<RawEntry>(`/projects/${projectId}/raw-entries`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  extractRawEntry: (projectId: number, rawEntryId: number) =>
    request<ExtractedEvent[]>(`/projects/${projectId}/raw-entries/${rawEntryId}/extract`, {
      method: "POST",
    }),
  listPendingEvents: (projectId: number) =>
    request<ExtractedEvent[]>(`/projects/${projectId}/extracted-events/pending`),
  listConfirmedEvents: (projectId: number) =>
    request<ExtractedEvent[]>(`/projects/${projectId}/extracted-events/confirmed`),
  updateEvent: (eventId: number, payload: EventUpdate) =>
    request<ExtractedEvent>(`/extracted-events/${eventId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  confirmEvent: (eventId: number) =>
    request<ExtractedEvent>(`/extracted-events/${eventId}/confirm`, { method: "POST" }),
  discardEvent: (eventId: number) =>
    request<ExtractedEvent>(`/extracted-events/${eventId}/discard`, { method: "POST" }),
};
