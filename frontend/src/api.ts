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

export type WorkerType = "DAILY_WORKER" | "SKILLED_WORKER" | "VENDOR" | "CLIENT" | "OTHER";
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

export type HistoryEntry = {
  id: number;
  project_id: number;
  worker_state_id: number | null;
  input_text: string;
  change_type: "WORK" | "PAYMENT" | "INVOICE" | "SETUP" | "ENTITY_UPDATE" | "NOTE";
  delta: Record<string, string | number | null> | string | number | null;
  created_at: string;
  updated_at: string;
};

export type NaturalInputResult = {
  raw_entry_id: number;
  intent: string;
  workers: Worker[];
  states: WorkerState[];
  history_entries: HistoryEntry[];
  work_logs: WorkLog[];
  invoices: Invoice[];
  payments: Payment[];
};

export type PendingInterpretationStatus = "PENDING" | "CONFIRMED" | "EDITED" | "DISCARDED";

export type PendingInterpretation = {
  id: number;
  project_id: number;
  raw_input_text: string;
  canonical_event_type: string;
  semantic_action: string;
  suggested_entity_id: number | null;
  matched_input_text: string | null;
  extracted_entities: Array<Record<string, string | number | boolean | null | Record<string, string | number | boolean | null>>> | null;
  extracted_amount: string | null;
  extracted_quantity: string | null;
  payment_method: PaymentType | null;
  financial_direction: FinancialDirection | null;
  due_date: string | null;
  description: string | null;
  semantic_explanation: Record<string, unknown> | null;
  confidence: number | null;
  structured_interpretation: Record<string, unknown> | null;
  status: PendingInterpretationStatus;
  created_at: string;
  updated_at: string;
};

export type PendingInterpretationUpdate = Partial<Pick<PendingInterpretation, "canonical_event_type" | "semantic_action" | "suggested_entity_id" | "matched_input_text" | "extracted_entities" | "extracted_amount" | "extracted_quantity" | "payment_method" | "financial_direction" | "due_date" | "description" | "structured_interpretation">>;

export type PendingInterpretationConfirm = {
  selected_person_id?: number | null;
  create_new?: boolean;
  name?: string | null;
  role?: string | null;
  role_detail?: string | null;
};

export type NaturalInputInterpretationResult = {
  interpretations: PendingInterpretation[];
};

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
  listRawEntries: (projectId: number) => request<RawEntry[]>(`/projects/${projectId}/raw-entries`),
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
  listWorkers: (projectId: number) => request<Worker[]>(`/projects/${projectId}/workers`),
  listWorkerStates: (projectId: number) => request<WorkerState[]>(`/projects/${projectId}/worker-states`),
  listHistory: (projectId: number) => request<HistoryEntry[]>(`/projects/${projectId}/history`),
  createWorker: (projectId: number, payload: Pick<Worker, "name" | "type"> & Partial<Pick<Worker, "role_detail" | "phone" | "account_number" | "daily_rate" | "notes">>) =>
    request<Worker>(`/projects/${projectId}/workers`, { method: "POST", body: JSON.stringify(payload) }),
  updateWorker: (workerId: number, payload: Partial<Pick<Worker, "name" | "type" | "role_detail" | "phone" | "account_number" | "daily_rate" | "notes">>) =>
    request<Worker>(`/workers/${workerId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  listWorkLogs: (projectId: number) => request<WorkLog[]>(`/projects/${projectId}/work-logs`),
  createWorkLog: (projectId: number, payload: { worker_id: number; task_name: string; unit: WorkUnit; quantity: string; rate_per_unit?: string | null; description?: string | null }) =>
    request<WorkLog>(`/projects/${projectId}/work-logs`, { method: "POST", body: JSON.stringify(payload) }),
  updateWorkLog: (workLogId: number, payload: Partial<{ task_name: string; unit: WorkUnit; quantity: string; rate_per_unit: string | null; description: string | null }>) =>
    request<WorkLog>(`/work-logs/${workLogId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  listInvoices: (projectId: number) => request<Invoice[]>(`/projects/${projectId}/invoices`),
  createInvoice: (projectId: number, payload: { vendor_id: number; total_amount: string; description?: string | null }) =>
    request<Invoice>(`/projects/${projectId}/invoices`, { method: "POST", body: JSON.stringify(payload) }),
  listPayments: (projectId: number) => request<Payment[]>(`/projects/${projectId}/payments`),
  createPayment: (projectId: number, payload: { entity_id: number; amount: string; related_invoice_id?: number | null; type: PaymentType }) =>
    request<Payment>(`/projects/${projectId}/payments`, { method: "POST", body: JSON.stringify(payload) }),
  getOperatingSummary: (projectId: number) => request<OperatingSummary>(`/projects/${projectId}/operating-summary`),
  processNaturalInput: (projectId: number, text: string) =>
    request<NaturalInputInterpretationResult>(`/projects/${projectId}/natural-input`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  updatePendingInterpretation: (interpretationId: number, payload: PendingInterpretationUpdate) =>
    request<PendingInterpretation>(`/pending-interpretations/${interpretationId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  confirmPendingInterpretation: (interpretationId: number, payload: PendingInterpretationConfirm = {}) =>
    request<NaturalInputResult>(`/pending-interpretations/${interpretationId}/confirm`, { method: "POST", body: JSON.stringify(payload) }),
  discardPendingInterpretation: (interpretationId: number) =>
    request<PendingInterpretation>(`/pending-interpretations/${interpretationId}/discard`, { method: "POST" }),
};
