const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

/* =========================================================
   TRACE SYSTEM (FIXED - MINIMAL SAFE VERSION)
========================================================= */

const traceListeners = new Set<(traceId: string) => void>();

// prevent infinite duplicate calls
const seenTraceIds = new Set<string>();

export function subscribeToTraceIds(
  listener: (traceId: string) => void,
): () => void {
  traceListeners.add(listener);

  return () => {
    traceListeners.delete(listener);
  };
}

function emitTrace(traceId: string) {
  if (!traceId) return;

  // ✅ CRITICAL FIX: prevent infinite loops
  if (seenTraceIds.has(traceId)) return;
  seenTraceIds.add(traceId);

  traceListeners.forEach((listener) => {
    listener(traceId);
  });
}

/* =========================================================
   TYPES
========================================================= */

export type Project = {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
};

export type VendorDebt = {
  vendor_id: number;
  vendor_name: string;
  invoice_total: string;
  paid_total: string;
  debt: string;
};

export type WorkerPayable = {
  worker_id: number;
  worker_name: string;
  debt: string;
};

export type ProjectSummary = {
  total_received: string;
  total_paid_out: string;
  open_payables: string;
  deferred_amount: string;
  check_amount: string;
  project_balance: string;
  available_balance: string;
  total_work_amount: string;
  total_invoice_amount: string;
  client_receivable: string;
  vendor_debts: VendorDebt[];
  worker_payables: WorkerPayable[];
};

export type ProjectDetail = Project & {
  totals: {
    money_in: string;
    money_out: string;
    net: string;
  };
  summary: ProjectSummary | null;
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

export type WorkerType =
  | "DAILY_WORKER"
  | "SKILLED_WORKER"
  | "VENDOR"
  | "CLIENT"
  | "OTHER";

export type WorkUnit = "meter" | "day" | "item" | "project" | "custom";
export type PaymentType = "CASH" | "BANK_TRANSFER" | "CHECK" | "OTHER";
export type FinancialDirection = "INCOMING" | "OUTGOING" | "DEBT" | "DEFERRED";

export type Worker = {
  id: number;
  project_id: number;
  name: string;
  type: WorkerType;
  role_detail: string | null;
  phone: string | null;
  account_number: string | null;
  daily_rate: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkerState = {
  id: number;
  project_id: number;
  worker_id: number;
  name: string;
  role: "DAILY" | "SKILLED" | "VENDOR" | "CLIENT";
  total_days_worked: string;
  total_quantity: string;
  unit: string | null;
  financial_balance: string;
  created_at: string;
  updated_at: string;
};

export type WorkLog = {
  id: number;
  project_id: number;
  worker_id: number;
  task_name: string;
  unit: WorkUnit;
  quantity: string;
  rate_per_unit: string | null;
  total_amount: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
};

export type Invoice = {
  id: number;
  project_id: number;
  vendor_id: number;
  total_amount: string;
  description: string | null;
  status: "OPEN" | "PARTIAL" | "PAID";
  created_at: string;
  updated_at: string;
};

export type Payment = {
  id: number;
  project_id: number;
  entity_id: number;
  amount: string;
  related_invoice_id: number | null;
  type: PaymentType;
  due_date: string | null;
  direction: FinancialDirection;
  created_at: string;
  updated_at: string;
};

export type OperatingSummary = {
  total_work_amount: string;
  total_invoice_amount: string;
  total_payments: string;
  total_paid_out: string;
  total_received: string;
  total_received_from_client: string;
  open_payables: string;
  project_balance: string;
  client_receivable: string;
  available_balance: string;
  deferred_amount: string;
  check_amount: string;
  vendor_debts: Array<{
    vendor_id: number;
    vendor_name: string;
    invoice_total: string;
    paid_total: string;
    debt: string;
  }>;
  worker_payables?: Array<{
    worker_id: number;
    worker_name: string;
    debt: string;
  }>;
};

export type HistoryEntry = {
  id: number;
  project_id: number;
  worker_state_id: number | null;
  input_text: string;
  change_type: string;
  delta: Record<string, string | number | null> | string | number | null;
  rule_id: string | null;
  explanation: Record<string, unknown> | null;
  conflict_warnings: Array<Record<string, unknown>> | null;
  created_at: string;
  updated_at: string;
};

export type PendingInterpretationStatus = "PENDING" | "EDITED" | "CONFIRMED" | "DISCARDED";

export type PendingInterpretation = {
  id: number;
  project_id: number;
  raw_input_text: string;
  canonical_event_type: string;
  semantic_action: string;
  suggested_entity_id: number | null;
  matched_input_text: string | null;
  extracted_entities: Array<Record<string, unknown>> | null;
  extracted_amount: string | null;
  extracted_quantity: string | null;
  payment_method: PaymentType | null;
  financial_direction: FinancialDirection | null;
  due_date: string | null;
  description: string | null;
  semantic_explanation: Record<string, unknown> | null;
  confidence: number | null;
  structured_interpretation: Record<string, unknown> | null;
  domain_route: {
    domain: "SETUP" | "FINANCIAL" | "ENTITY_UPDATE" | "MIXED";
    confidence: number;
    required_schema: "setup_confirmation" | "entity_update_confirmation" | "financial_confirmation" | "split_confirmation";
    ui_mode: "SetupModal" | "EntityUpdateModal" | "FinancialModal" | "SplitFlow";
  } | null;
  status: PendingInterpretationStatus;
  created_at: string;
  updated_at: string;
};

export type PendingInterpretationUpdate = Partial<Pick<PendingInterpretation, "canonical_event_type" | "semantic_action" | "suggested_entity_id" | "matched_input_text" | "extracted_entities" | "extracted_amount" | "extracted_quantity" | "payment_method" | "financial_direction" | "due_date" | "description" | "structured_interpretation">>;

export type PendingInterpretationConfirm = {
  entity_id?: number | null;
  selected_person_id?: number | null;
  confirmed?: boolean;
  create_new?: boolean;
  name?: string | null;
  role?: string | null;
  role_detail?: string | null;
  field_updates?: Record<string, unknown> | null;
  amount?: string | null;
  direction?: FinancialDirection | null;
  payment_method?: PaymentType | null;
  description?: string | null;
  due_date?: string | null;
};

export type EntityResolutionResult = {
  status: "ENTITY_RESOLVED";
  entity_id: number;
  is_new: boolean;
  name: string;
  role: string;
  requires_confirmation: boolean;
};

export type PendingInterpretationConfirmResult = NaturalInputResult | EntityResolutionResult;

export type NaturalInputResult = {
  raw_entry_id: number | null;
  intent: string;
  workers: Worker[];
  states: WorkerState[];
  history_entries: HistoryEntry[];
  work_logs: WorkLog[];
  invoices: Invoice[];
  payments: Payment[];
};

export type NaturalInputInterpretationResult = {
  interpretations: PendingInterpretation[];
};

/* =========================================================
   TRACE EVENT TYPES
========================================================= */

export type TraceEvent = {
  trace_id: string;
  event: string;
  event_group?: string;
  payload: Record<string, unknown>;
  start_time: number | null;
  end_time: number | null;
  duration_ms: number | null;
  created_at: number;
};

export type MetricTraceEvent = {
  trace_id: string;
  event_name: string;
  event_group: string;
  event_index: number;
  timestamp: string;
  duration_ms: number | null;
  payload: Record<string, unknown>;
};

export type TraceMetricsResponse = {
  trace_id: string;
  total_duration_ms: number;
  events: MetricTraceEvent[];
};

export type TraceDetail = {
  trace_id: string;
  events: TraceEvent[];
};

export type JobStatus = "PENDING" | "RUNNING" | "DONE" | "FAILED";

export type JobState = "IDLE" | "SUBMITTED" | "PROCESSING" | "DONE" | "FAILED";

export type NaturalInputJobRecord = {
  job_id: string;
  status: JobStatus;
  project_id?: number | null;
  trace_id?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
  duration_ms?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  events_summary?: Array<{
    event: string;
    duration_ms: number | null;
  }>;
};

export type JobEvent = TraceEvent & {
  job_id?: string;
  sequence_number?: number;
  timestamp?: string | number | null;
};

type RawTraceEvent = Partial<TraceEvent> & {
  traceId?: string;
  trace_id?: string;
  job_id?: string;
  event?: string;
  eventName?: string;
  event_name?: string;
  eventGroup?: string;
  event_group?: string;
  eventIndex?: number;
  event_index?: number;
  sequence_number?: number;
  durationMs?: number | null;
  duration_ms?: number | null;
  createdAt?: number;
  created_at?: number;
  timestamp?: string | number | null;
  name?: string;
  type?: string;
  data?: Record<string, unknown>;
};

export function normalizeTraceEvent(raw: unknown, index = 0): JobEvent {
  const record = raw && typeof raw === "object" ? raw as RawTraceEvent : {};
  const eventName = record.event ?? record.eventName ?? record.event_name ?? record.name ?? record.type ?? "UNKNOWN_EVENT";
  const eventGroup = record.event_group ?? record.eventGroup ?? "OTHER";
  const eventIndex = record.sequence_number ?? record.eventIndex ?? record.event_index ?? index + 1;

  return {
    trace_id: record.trace_id ?? record.traceId ?? "",
    event: eventName,
    event_group: eventGroup,
    payload: record.payload ?? record.data ?? {},
    start_time: record.start_time ?? null,
    end_time: record.end_time ?? null,
    duration_ms: record.duration_ms ?? record.durationMs ?? null,
    created_at: record.created_at ?? record.createdAt ?? Date.now() / 1000,
    job_id: record.job_id,
    sequence_number: eventIndex,
    timestamp: record.timestamp ?? null,
  };
}

export function normalizeMetricTraceEvent(raw: unknown, index = 0): MetricTraceEvent {
  const record = raw && typeof raw === "object" ? raw as RawTraceEvent : {};

  return {
    trace_id: record.trace_id ?? record.traceId ?? "",
    event_name: record.eventName ?? record.event_name ?? record.event ?? record.name ?? record.type ?? "UNKNOWN_EVENT",
    event_group: record.eventGroup ?? record.event_group ?? "OTHER",
    event_index: record.eventIndex ?? record.event_index ?? record.sequence_number ?? index + 1,
    timestamp: String(record.timestamp ?? record.created_at ?? record.createdAt ?? new Date().toISOString()),
    duration_ms: record.durationMs ?? record.duration_ms ?? null,
    payload: record.payload ?? record.data ?? {},
  };
}

/* =========================================================
   REQUEST WRAPPER
========================================================= */

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  // ✅ TRACE HOOK (FIXED)
  const traceId = response.headers.get("X-Trace-Id");

  // Only emit for NON-read-only debug endpoints
  const isTraceRead =
    path.startsWith("/traces/") ||
    path === "/jobs" ||
    path.startsWith("/jobs/") ||
    path.startsWith("/natural-input-jobs/");

  if (traceId && !isTraceRead) {
    emitTrace(traceId);
  }

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

/* =========================================================
   API
========================================================= */

export const api = {
  listProjects: () => request<Project[]>("/projects"),

  createProject: (name: string) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  getProject: (projectId: number) =>
    request<ProjectDetail>(`/projects/${projectId}`),

  listRawEntries: (projectId: number) =>
    request<RawEntry[]>(`/projects/${projectId}/raw-entries`),

  createRawEntry: (projectId: number, text: string) =>
    request<RawEntry>(`/projects/${projectId}/raw-entries`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  extractRawEntry: (projectId: number, rawEntryId: number) =>
    request<ExtractedEvent[]>(
      `/projects/${projectId}/raw-entries/${rawEntryId}/extract`,
      { method: "POST" },
    ),

  listPendingEvents: (projectId: number) =>
    request<ExtractedEvent[]>(
      `/projects/${projectId}/extracted-events/pending`,
    ),

  listConfirmedEvents: (projectId: number) =>
    request<ExtractedEvent[]>(
      `/projects/${projectId}/extracted-events/confirmed`,
    ),

  updateEvent: (eventId: number, payload: Partial<ExtractedEvent>) =>
    request<ExtractedEvent>(`/extracted-events/${eventId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  confirmEvent: (eventId: number) =>
    request<ExtractedEvent>(`/extracted-events/${eventId}/confirm`, {
      method: "POST",
    }),

  discardEvent: (eventId: number) =>
    request<ExtractedEvent>(`/extracted-events/${eventId}/discard`, {
      method: "POST",
    }),

  listWorkers: (projectId: number) =>
    request<Worker[]>(`/projects/${projectId}/workers`),

  createWorker: (projectId: number, payload: Pick<Worker, "name" | "type"> & Partial<Pick<Worker, "role_detail" | "phone" | "account_number" | "daily_rate" | "notes">>) =>
    request<Worker>(`/projects/${projectId}/workers`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateWorker: (workerId: number, payload: Partial<Pick<Worker, "name" | "type" | "role_detail" | "phone" | "account_number" | "daily_rate" | "notes">>) =>
    request<Worker>(`/workers/${workerId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  listWorkerStates: (projectId: number) =>
    request<WorkerState[]>(`/projects/${projectId}/worker-states`),

  listHistory: (projectId: number) =>
    request<HistoryEntry[]>(`/projects/${projectId}/history`),

  listWorkLogs: (projectId: number) =>
    request<WorkLog[]>(`/projects/${projectId}/work-logs`),

  createWorkLog: (projectId: number, payload: { worker_id: number; task_name: string; unit: WorkUnit; quantity: string; rate_per_unit?: string | null; description?: string | null }) =>
    request<WorkLog>(`/projects/${projectId}/work-logs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateWorkLog: (workLogId: number, payload: Partial<{ task_name: string; unit: WorkUnit; quantity: string; rate_per_unit: string | null; description: string | null }>) =>
    request<WorkLog>(`/work-logs/${workLogId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  listPayments: (projectId: number) =>
    request<Payment[]>(`/projects/${projectId}/payments`),

  createPayment: (projectId: number, payload: { entity_id: number; amount: string; related_invoice_id?: number | null; type: PaymentType; direction?: FinancialDirection; due_date?: string | null }) =>
    request<Payment>(`/projects/${projectId}/payments`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listInvoices: (projectId: number) =>
    request<Invoice[]>(`/projects/${projectId}/invoices`),

  createInvoice: (projectId: number, payload: { vendor_id: number; total_amount: string; description?: string | null }) =>
    request<Invoice>(`/projects/${projectId}/invoices`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getOperatingSummary: (projectId: number) =>
    request<OperatingSummary>(`/projects/${projectId}/operating-summary`),

  getTrace: (traceId: string) => request<TraceDetail>(`/traces/${traceId}`),

  getTraceMetrics: async (traceId: string) => {
    const result = await request<TraceMetricsResponse>(`/metrics/trace/${encodeURIComponent(traceId)}`);
    return {
      ...result,
      events: result.events.map((event, index) => normalizeMetricTraceEvent(event, index)),
    };
  },

  listJobs: () => request<NaturalInputJobRecord[]>("/jobs"),

  getNaturalInputJob: (jobId: string) =>
    request<NaturalInputJobRecord>(`/natural-input-jobs/${encodeURIComponent(jobId)}`),

  listJobEvents: async (jobId: string) => {
    const result = await request<JobEvent[] | { events: JobEvent[] }>(
      `/jobs/${encodeURIComponent(jobId)}/events`,
    );
    const events = Array.isArray(result) ? result : result.events;
    return events.map((event, index) => normalizeTraceEvent(event, index));
  },

  processNaturalInput: (projectId: number, text: string) =>
    request<NaturalInputJobRecord>(`/projects/${projectId}/natural-input`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  updatePendingInterpretation: (id: number, payload: PendingInterpretationUpdate) =>
    request<PendingInterpretation>(`/pending-interpretations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  confirmPendingInterpretation: (id: number, payload: PendingInterpretationConfirm = {}) =>
    request<PendingInterpretationConfirmResult>(`/pending-interpretations/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  discardPendingInterpretation: (id: number) =>
    request<PendingInterpretation>(`/pending-interpretations/${id}/discard`, {
      method: "POST",
    }),
};
