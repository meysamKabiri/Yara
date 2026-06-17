import { FormEvent, useEffect, useState } from "react";
import { api, HistoryEntry, Invoice, OperatingSummary, Payment, PaymentType, PendingInterpretation, Project, ProjectDetail, RawEntry, Worker, WorkerState } from "./api";

const exampleInputs = [
  "کارفرمای پروژه میثم کبیری است",
  "مش رحیم امروز کار کرد",
  "نادری جوشکار امروز جوشکاری کرد",
  "۱۰۰ میلیون دادم به جوشکار",
  "جوشکار فاکتور ۳۴۵ میلیونی داده",
];

function friendlyError(err: unknown): string {
  if (!(err instanceof Error)) return "Something went wrong. Please try again.";
  try {
    const parsed = JSON.parse(err.message) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    return err.message || "Something went wrong. Please try again.";
  }
  return err.message || "Something went wrong. Please try again.";
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

const debugSemantics = import.meta.env.YARA_DEBUG_SEMANTICS === "1" || import.meta.env.VITE_YARA_DEBUG_SEMANTICS === "1";

function formatConfidence(value: number | null): string {
  if (value === null) return "نامشخص";
  return `${Math.round(value * 100)}%`;
}

function formatMoney(value: string | null): string | null {
  if (!value) return null;
  return `${Number(value).toLocaleString("fa-IR")} تومان`;
}

function firstEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  return interpretation.extracted_entities?.[0] ?? {};
}

function entityLabel(interpretation: PendingInterpretation): string {
  const entity = firstEntity(interpretation);
  const name = typeof entity.name === "string" ? entity.name : "نامشخص";
  const type = typeof entity.type === "string" ? entity.type : typeof entity.role_guess === "string" ? entity.role_guess : "UNKNOWN";
  return `${name} (${type})`;
}

function entityName(interpretation: PendingInterpretation): string {
  const entity = firstEntity(interpretation);
  return typeof entity.name === "string" && entity.name.trim() ? entity.name.trim() : "نامشخص";
}

function isUnknownEntity(interpretation: PendingInterpretation): boolean {
  const name = entityName(interpretation);
  return name === "نامشخص" || name === "طرف حساب نامشخص" || name.toLowerCase() === "unknown";
}

function resolvedWorker(interpretation: PendingInterpretation, workers: Worker[]): Worker | undefined {
  const name = entityName(interpretation);
  return workers.find((worker) => worker.name === name);
}

function roleLabelFromType(type: string | undefined): string {
  if (type === "CLIENT") return "Client / کارفرما";
  if (type === "VENDOR") return "Vendor / فروشنده";
  if (type === "SKILLED_WORKER") return "Skilled worker / استادکار";
  if (type === "DAILY_WORKER") return "Worker / کارگر";
  return "Project person";
}

function roleLabel(interpretation: PendingInterpretation, workers: Worker[]): string {
  const worker = resolvedWorker(interpretation, workers);
  if (worker) return roleLabelFromType(worker.type);
  const entity = firstEntity(interpretation);
  const type = typeof entity.type === "string" ? entity.type : typeof entity.role_guess === "string" ? entity.role_guess : undefined;
  return roleLabelFromType(type);
}

function setupEntities(interpretation: PendingInterpretation): Array<{ name: string; type: string }> {
  return (interpretation.extracted_entities ?? [])
    .map((entity) => ({
      name: typeof entity.name === "string" ? entity.name : "",
      type: typeof entity.type === "string" ? entity.type : "WORKER",
    }))
    .filter((entity) => entity.name.trim());
}

function setupRoleLabel(type: string): string {
  if (type === "CLIENT") return "project client";
  if (type === "VENDOR") return "vendor";
  return "simple/daily worker";
}

function hasExplicitCreateNew(interpretation: PendingInterpretation): boolean {
  return firstEntity(interpretation).create_new === true;
}

function needsFinancialEntityResolution(interpretation: PendingInterpretation): boolean {
  return interpretation.canonical_event_type === "FINANCIAL_EVENT" && !interpretation.suggested_entity_id && !hasExplicitCreateNew(interpretation);
}

function matchedPartialName(interpretation: PendingInterpretation): string | null {
  if (interpretation.matched_input_text) return interpretation.matched_input_text;
  const name = entityName(interpretation);
  if (isUnknownEntity(interpretation) || interpretation.raw_input_text.includes(name)) return null;
  const token = name.split(/\s+/).find((part) => part.length > 1 && interpretation.raw_input_text.includes(part));
  return token ?? null;
}

function actionLabel(action: string): string {
  const labels: Record<string, string> = {
    SETUP: "Setup entity",
    ENTITY_UPDATE: "Update entity",
    INCREMENT: "Work recorded",
    PAYMENT: "Payment recorded",
    PAYMENT_RECEIVED: "Payment received",
    PURCHASE_PAID: "Paid purchase",
    CHECK_PAYMENT: "Check payment",
    DEFERRED_PAYMENT: "Deferred payment",
    INVOICE: "Invoice/debt recorded",
    DEBT_CREATED: "Debt created",
    NOTE: "Note saved",
  };
  return labels[action] ?? action;
}

function effectLabel(interpretation: PendingInterpretation): string {
  const amount = interpretation.extracted_amount;
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT" && amount) {
    if (["INVOICE", "DEBT_CREATED"].includes(interpretation.semantic_action)) return `Vendor balance increases by ${amount}`;
    return `Project cash/balance changes by ${amount}`;
  }
  if (interpretation.canonical_event_type === "WORK_EVENT") return `Worker state increases by ${interpretation.extracted_quantity ?? "1"}`;
  if (interpretation.canonical_event_type === "SETUP_EVENT") return "Project entity registry will be updated";
  return "A project note/history entry will be saved";
}

function financialDirection(interpretation: PendingInterpretation, workers: Worker[]): "incoming" | "outgoing" | "debt" {
  if (interpretation.financial_direction === "INCOMING") return "incoming";
  if (interpretation.financial_direction === "DEBT") return "debt";
  if (["INVOICE", "DEBT_CREATED"].includes(interpretation.semantic_action)) return "debt";
  const worker = resolvedWorker(interpretation, workers);
  const entity = firstEntity(interpretation);
  const type = worker?.type ?? (typeof entity.type === "string" ? entity.type : typeof entity.role_guess === "string" ? entity.role_guess : undefined);
  return type === "CLIENT" ? "incoming" : "outgoing";
}

function actionSummary(interpretation: PendingInterpretation, workers: Worker[]): string {
  if (interpretation.semantic_action === "PURCHASE_PAID") return "Paid purchase";
  if (interpretation.semantic_action === "DEBT_CREATED" || interpretation.semantic_action === "INVOICE") return "Debt / unpaid purchase";
  if (interpretation.semantic_action === "CHECK_PAYMENT" || interpretation.semantic_action === "DEFERRED_PAYMENT") return "Deferred check payment";
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") return financialDirection(interpretation, workers) === "incoming" ? "Incoming payment to project" : "Outgoing payment from project";
  if (interpretation.canonical_event_type === "WORK_EVENT") return "Worked today";
  if (interpretation.canonical_event_type === "SETUP_EVENT") return "Project client/person setup";
  return "Project note";
}

function understoodRows(interpretation: PendingInterpretation, workers: Worker[]): Array<{ label: string; value: string }> {
  const entity = entityName(interpretation);
  const amount = formatMoney(interpretation.extracted_amount);
  const partial = matchedPartialName(interpretation);
  if (interpretation.canonical_event_type === "SETUP_EVENT") {
    const entities = setupEntities(interpretation);
    if (entities.length > 1) {
      return [
        {
          label: "People",
          value: entities.map((item) => `${item.name} — ${setupRoleLabel(item.type)}`).join("\n"),
        },
      ];
    }
    return [{ label: entities[0]?.type === "CLIENT" ? "Project client" : "Project person", value: entity }];
  }
  if (interpretation.canonical_event_type === "WORK_EVENT") {
    return [
      { label: "Worker", value: entity },
      { label: "Role", value: roleLabel(interpretation, workers) },
      { label: "Action", value: "Worked today" },
    ];
  }
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") {
    return [
      ...(partial ? [{ label: `Yara matched "${partial}" to`, value: `${entity} — ${roleLabel(interpretation, workers)}` }] : []),
      { label: financialDirection(interpretation, workers) === "debt" ? "Vendor" : "Person", value: entity },
      { label: "Role", value: roleLabel(interpretation, workers) },
      { label: "Action", value: actionSummary(interpretation, workers) },
      { label: "Amount", value: amount ?? "Amount missing" },
      ...(interpretation.due_date ? [{ label: "Due date", value: interpretation.due_date }] : []),
    ];
  }
  return [{ label: "Note", value: interpretation.description || interpretation.raw_input_text }];
}

function outcomeSummary(interpretation: PendingInterpretation, workers: Worker[]): string[] {
  const entity = entityName(interpretation);
  const amount = formatMoney(interpretation.extracted_amount);
  if (interpretation.canonical_event_type === "SETUP_EVENT") {
    const entities = setupEntities(interpretation);
    if (entities.length > 1) return [`${entities.length} people will be added to this project as daily workers.`];
    return [`${entity} will be added as the project client/person.`];
  }
  if (interpretation.canonical_event_type === "WORK_EVENT") return [`${interpretation.extracted_quantity ?? "One"} work day/unit will be added for ${entity}.`];
  if (interpretation.semantic_action === "PURCHASE_PAID") return [`Yara will record a paid purchase from ${entity}.`, "No vendor debt will be created."];
  if (interpretation.semantic_action === "DEBT_CREATED" || interpretation.semantic_action === "INVOICE") return [`Vendor debt will increase${amount ? ` by ${amount}` : ""}.`];
  if (interpretation.semantic_action === "CHECK_PAYMENT" || interpretation.semantic_action === "DEFERRED_PAYMENT") return [`Yara will record a deferred check payment to ${entity}${amount ? ` for ${amount}` : ""}.`, "It will be tracked until the due date."];
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") {
    if (financialDirection(interpretation, workers) === "incoming") return [`Yara will record that ${entity} paid ${amount ?? "this amount"} into this project.`, `Project received payments will increase${amount ? ` by ${amount}` : ""}.`];
    return [`Yara will record that this project paid ${amount ?? "this amount"} to ${entity}.`, `Project outgoing payments will increase${amount ? ` by ${amount}` : ""}.`];
  }
  return ["A note will be saved in project history."];
}

function ambiguousEntityCandidates(interpretation: PendingInterpretation, workers: Worker[]): Worker[] {
  const name = entityName(interpretation);
  if (name === "نامشخص" || name.length < 2) return [];
  const exact = workers.filter((worker) => worker.name === name);
  if (exact.length === 1) return [];
  return workers.filter((worker) => worker.name.includes(name));
}

function explanationLines(interpretation: PendingInterpretation): string[] {
  const explanation = interpretation.semantic_explanation;
  if (!explanation) return ["No semantic explanation was provided."];
  const lines: string[] = [];
  const signals = explanation.matched_signals;
  const path = explanation.decision_path;
  const rule = explanation.triggered_rule;
  if (rule) lines.push(`Triggered rule: ${String(rule)}`);
  if (Array.isArray(signals)) lines.push(`Detected: ${signals.map(String).join(", ")}`);
  if (Array.isArray(path)) lines.push(...path.map(String));
  return lines.length ? lines : [JSON.stringify(explanation)];
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectName, setProjectName] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [rawEntries, setRawEntries] = useState<RawEntry[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [workerStates, setWorkerStates] = useState<WorkerState[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [operatingSummary, setOperatingSummary] = useState<OperatingSummary | null>(null);
  const [naturalText, setNaturalText] = useState("");
  const [pendingInterpretations, setPendingInterpretations] = useState<PendingInterpretation[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [setupEditEntities, setSetupEditEntities] = useState<Record<number, Array<{ name: string; type: string }>>>({});
  const [ambiguitySelections, setAmbiguitySelections] = useState<Record<number, number>>({});
  const [unknownEntityForms, setUnknownEntityForms] = useState<Record<number, { workerId: string; name: string; type: string }>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isLoading = loadingAction !== null;

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (selectedProjectId) loadProjectData(selectedProjectId);
  }, [selectedProjectId]);

  async function runAction(label: string, action: () => Promise<void>) {
    setLoadingAction(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoadingAction(null);
    }
  }

  async function loadProjects() {
    await runAction("Loading projects", async () => setProjects(await api.listProjects()));
  }

  async function loadProjectData(projectId: number) {
    await runAction("Loading project", async () => {
      const [detail, rawEntryList, workerList, states, historyList, invoiceList, paymentList, summary] = await Promise.all([
        api.getProject(projectId),
        api.listRawEntries(projectId),
        api.listWorkers(projectId),
        api.listWorkerStates(projectId),
        api.listHistory(projectId),
        api.listInvoices(projectId),
        api.listPayments(projectId),
        api.getOperatingSummary(projectId),
      ]);
      setProjectDetail(detail);
      setRawEntries(rawEntryList);
      setWorkers(workerList);
      setWorkerStates(states);
      setHistory(historyList);
      setInvoices(invoiceList);
      setPayments(paymentList);
      setOperatingSummary(summary);
    });
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    const name = projectName.trim();
    if (!name) return;
    await runAction("Creating project", async () => {
      const project = await api.createProject(name);
      setProjectName("");
      setProjects(await api.listProjects());
      setSelectedProjectId(project.id);
    });
  }

  async function submitNaturalInput(event: FormEvent) {
    event.preventDefault();
    if (!selectedProjectId || !naturalText.trim()) return;
    await runAction("Processing natural input", async () => {
      const result = await api.processNaturalInput(selectedProjectId, naturalText.trim());
      setPendingInterpretations(result.interpretations);
      setNaturalText("");
    });
  }

  function startEdit(interpretation: PendingInterpretation) {
    const entity = firstEntity(interpretation);
    setEditingId(interpretation.id);
    if (interpretation.canonical_event_type === "SETUP_EVENT") {
      setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: setupEntities(interpretation) });
    }
    setEditForm({
      entity: typeof entity.name === "string" ? entity.name : "",
      entityType: typeof entity.type === "string" ? entity.type : typeof entity.role_guess === "string" ? entity.role_guess : "WORKER",
      canonical_event_type: interpretation.canonical_event_type,
      semantic_action: interpretation.semantic_action,
      extracted_amount: interpretation.extracted_amount ?? "",
      extracted_quantity: interpretation.extracted_quantity ?? "",
      payment_method: interpretation.payment_method ?? "",
      due_date: interpretation.due_date ?? "",
      description: interpretation.description ?? "",
    });
  }

  async function saveEdit(interpretation: PendingInterpretation) {
    await runAction("Saving interpretation", async () => {
      const updated = await api.updatePendingInterpretation(interpretation.id, {
        canonical_event_type: editForm.canonical_event_type,
        semantic_action: editForm.semantic_action,
        extracted_entities: interpretation.canonical_event_type === "SETUP_EVENT"
          ? (setupEditEntities[interpretation.id] ?? []).filter((entity) => entity.name.trim())
          : editForm.entity ? [{ ...firstEntity(interpretation), name: editForm.entity, type: editForm.entityType || "WORKER" }] : [],
        extracted_amount: editForm.extracted_amount || null,
        extracted_quantity: editForm.extracted_quantity || null,
        payment_method: (editForm.payment_method || null) as PaymentType | null,
        due_date: editForm.due_date || null,
        description: editForm.description || null,
      });
      setPendingInterpretations((items) => items.map((item) => item.id === updated.id ? updated : item));
      setEditingId(null);
    });
  }

  async function confirmInterpretation(interpretation: PendingInterpretation) {
    if (!selectedProjectId) return;
    await runAction("Confirming interpretation", async () => {
      await api.confirmPendingInterpretation(interpretation.id);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(selectedProjectId);
    });
  }

  async function selectAmbiguousEntity(interpretation: PendingInterpretation, worker: Worker) {
    await runAction("Updating entity", async () => {
      const updated = await api.updatePendingInterpretation(interpretation.id, {
        suggested_entity_id: worker.id,
        extracted_entities: [{ ...firstEntity(interpretation), name: worker.name, type: worker.type }],
      });
      setPendingInterpretations((items) => items.map((item) => item.id === updated.id ? updated : item));
    });
  }

  async function resolveUnknownEntity(interpretation: PendingInterpretation) {
    const form = unknownEntityForms[interpretation.id];
    if (!form) return;
    const selectedWorker = workers.find((worker) => String(worker.id) === form.workerId);
    const name = selectedWorker?.name ?? form.name.trim();
    const type = selectedWorker?.type ?? form.type;
    if (!name) return;
    await runAction("Updating entity", async () => {
      const updated = await api.updatePendingInterpretation(interpretation.id, {
        suggested_entity_id: selectedWorker?.id ?? null,
        extracted_entities: [
          {
            ...firstEntity(interpretation),
            name,
            type: type || "VENDOR",
            create_new: selectedWorker ? null : true,
          },
        ],
      });
      setPendingInterpretations((items) => items.map((item) => item.id === updated.id ? updated : item));
    });
  }

  async function discardInterpretation(interpretation: PendingInterpretation) {
    if (!selectedProjectId) return;
    await runAction("Discarding interpretation", async () => {
      await api.discardPendingInterpretation(interpretation.id);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(selectedProjectId);
    });
  }

  return (
    <main className="app">
      <header>
        <h1>Yara Construction Finance OS</h1>
        <p>Natural language → structured construction finance graph</p>
      </header>

      {error && <div className="error">{error}</div>}
      {loadingAction && <div className="loading">{loadingAction}...</div>}

      {pendingInterpretations.length > 0 && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="interpretation-title">
          <section className="confirmation-modal">
            <div className="modal-header">
              <div>
                <h2 id="interpretation-title">Please verify this interpretation</h2>
                <p>Nothing will be saved until you confirm.</p>
              </div>
            </div>
            <div className="interpretation-stack">
              {pendingInterpretations.map((interpretation) => {
                const isEditing = editingId === interpretation.id;
                const candidates = ambiguousEntityCandidates(interpretation, workers);
                if (candidates.length <= 1 && (isUnknownEntity(interpretation) || needsFinancialEntityResolution(interpretation))) {
                  const form = unknownEntityForms[interpretation.id] ?? { workerId: "", name: "", type: "VENDOR" };
                  const canContinue = Boolean(form.workerId || form.name.trim());
                  return (
                    <article className="interpretation-card approval-card" key={interpretation.id}>
                      <section className="approval-section">
                        <span className="section-kicker">Who is involved?</span>
                        <p className="approval-summary">طرف حساب مشخص نیست.</p>
                        <p className="approval-help">Please select who this refers to before confirming.</p>
                        <div className="unknown-entity-box">
                          <label>
                            Select project entity
                            <select value={form.workerId} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, workerId: event.target.value } })}>
                              <option value="">Select...</option>
                              {workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name} — {roleLabelFromType(worker.type)}</option>)}
                            </select>
                          </label>
                          <div className="or-divider">or create new entity</div>
                          <div className="edit-grid">
                            <label>Name<input value={form.name} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, name: event.target.value } })} /></label>
                            <label>Role<select value={form.type} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, type: event.target.value } })}><option value="CLIENT">Client / کارفرما</option><option value="VENDOR">Vendor / فروشنده</option><option value="DAILY_WORKER">Worker / کارگر</option><option value="SKILLED_WORKER">Skilled worker / استادکار</option></select></label>
                          </div>
                        </div>
                      </section>
                      {isEditing && (
                        <div className="edit-grid modal-edit-grid">
                          <label>Entity<input value={editForm.entity ?? ""} onChange={(event) => setEditForm({ ...editForm, entity: event.target.value })} /></label>
                          <label>Entity type<input value={editForm.entityType ?? ""} onChange={(event) => setEditForm({ ...editForm, entityType: event.target.value })} /></label>
                          <label>Action<input value={editForm.semantic_action ?? ""} onChange={(event) => setEditForm({ ...editForm, semantic_action: event.target.value })} /></label>
                          <label>Amount<input value={editForm.extracted_amount ?? ""} onChange={(event) => setEditForm({ ...editForm, extracted_amount: event.target.value })} /></label>
                          <label>Quantity<input value={editForm.extracted_quantity ?? ""} onChange={(event) => setEditForm({ ...editForm, extracted_quantity: event.target.value })} /></label>
                          <label>Payment method<input value={editForm.payment_method ?? ""} onChange={(event) => setEditForm({ ...editForm, payment_method: event.target.value })} /></label>
                          <label>Due date<input value={editForm.due_date ?? ""} onChange={(event) => setEditForm({ ...editForm, due_date: event.target.value })} /></label>
                          <label className="wide-field">Description<textarea value={editForm.description ?? ""} onChange={(event) => setEditForm({ ...editForm, description: event.target.value })} /></label>
                        </div>
                      )}
                      <div className="actions modal-actions">
                        {isEditing ? <button className="primary-action" type="button" onClick={() => saveEdit(interpretation)} disabled={isLoading}>Save edit</button> : <button className="primary-action" type="button" onClick={() => resolveUnknownEntity(interpretation)} disabled={isLoading || !canContinue}>Continue</button>}
                        {isEditing ? <button type="button" onClick={() => setEditingId(null)} disabled={isLoading}>Cancel edit</button> : <button type="button" onClick={() => startEdit(interpretation)} disabled={isLoading}>Edit</button>}
                        <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>Discard</button>
                      </div>
                    </article>
                  );
                }
                if (candidates.length > 1) {
                  const selectedCandidate = candidates.find((worker) => worker.id === ambiguitySelections[interpretation.id]);
                  return (
                    <article className="interpretation-card approval-card" key={interpretation.id}>
                      <section className="approval-section">
                        <h3>Who is "{entityName(interpretation)}"?</h3>
                        <div className="entity-choice-list">
                          {candidates.map((worker) => (
                            <label key={worker.id} className="entity-choice">
                              <input type="radio" name={`entity-${interpretation.id}`} checked={ambiguitySelections[interpretation.id] === worker.id} onChange={() => setAmbiguitySelections({ ...ambiguitySelections, [interpretation.id]: worker.id })} />
                              <strong>{worker.name}</strong>
                              <span>{worker.type}</span>
                            </label>
                          ))}
                        </div>
                      </section>
                      <div className="actions modal-actions">
                        <button className="primary-action" type="button" onClick={() => selectedCandidate && selectAmbiguousEntity(interpretation, selectedCandidate)} disabled={isLoading || !selectedCandidate}>Continue</button>
                        <button type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>Discard</button>
                      </div>
                    </article>
                  );
                }
                return (
                  <article className="interpretation-card approval-card" key={interpretation.id}>
                    <section className="approval-section">
                      <span className="section-kicker">What Yara understood</span>
                      <dl className="approval-fields">
                        {understoodRows(interpretation, workers).map((row) => <div key={`${row.label}-${row.value}`}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
                      </dl>
                    </section>
                    <section className="approval-section outcome-section">
                      <span className="section-kicker">What will happen</span>
                      <div className="approval-outcome">{outcomeSummary(interpretation, workers).map((line) => <p key={line}>{line}</p>)}</div>
                    </section>
                    {isEditing && (
                      interpretation.canonical_event_type === "SETUP_EVENT" ? (
                        <div className="setup-edit-list modal-edit-grid">
                          {(setupEditEntities[interpretation.id] ?? []).map((entity, index) => (
                            <div className="setup-edit-row" key={`${interpretation.id}-${index}`}>
                              <label>Name<input value={entity.name} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) })} /></label>
                              <label>Role<select value={entity.type} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, type: event.target.value } : item) })}><option value="WORKER">Daily worker</option><option value="CLIENT">Client</option><option value="VENDOR">Vendor</option></select></label>
                              <button type="button" onClick={() => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).filter((_, itemIndex) => itemIndex !== index) })}>Remove</button>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="edit-grid modal-edit-grid">
                          <label>Entity<input value={editForm.entity ?? ""} onChange={(event) => setEditForm({ ...editForm, entity: event.target.value })} /></label>
                          <label>Entity type<input value={editForm.entityType ?? ""} onChange={(event) => setEditForm({ ...editForm, entityType: event.target.value })} /></label>
                          <label>Action<input value={editForm.semantic_action ?? ""} onChange={(event) => setEditForm({ ...editForm, semantic_action: event.target.value })} /></label>
                          <label>Amount<input value={editForm.extracted_amount ?? ""} onChange={(event) => setEditForm({ ...editForm, extracted_amount: event.target.value })} /></label>
                          <label>Quantity<input value={editForm.extracted_quantity ?? ""} onChange={(event) => setEditForm({ ...editForm, extracted_quantity: event.target.value })} /></label>
                          <label>Payment method<input value={editForm.payment_method ?? ""} onChange={(event) => setEditForm({ ...editForm, payment_method: event.target.value })} /></label>
                          <label>Due date<input value={editForm.due_date ?? ""} onChange={(event) => setEditForm({ ...editForm, due_date: event.target.value })} /></label>
                          <label className="wide-field">Description<textarea value={editForm.description ?? ""} onChange={(event) => setEditForm({ ...editForm, description: event.target.value })} /></label>
                        </div>
                      )
                    )}
                    <details className="technical-details" open={debugSemantics}>
                      <summary>Technical Details</summary>
                      <dl className="fields compact-fields">
                        <div><dt>Input</dt><dd>{interpretation.raw_input_text}</dd></div>
                        <div><dt>Entity</dt><dd>{entityLabel(interpretation)}</dd></div>
                        <div><dt>Semantic event</dt><dd>{interpretation.canonical_event_type}</dd></div>
                        <div><dt>Semantic action</dt><dd>{interpretation.semantic_action}</dd></div>
                        <div><dt>Confidence</dt><dd>{formatConfidence(interpretation.confidence)}</dd></div>
                        <div><dt>Effect</dt><dd>{effectLabel(interpretation)}</dd></div>
                      </dl>
                      <div className="explanation">
                        {explanationLines(interpretation).map((line) => <p key={line}>{line}</p>)}
                        <pre>{JSON.stringify(interpretation.semantic_explanation, null, 2)}</pre>
                      </div>
                    </details>
                    <div className="actions modal-actions">
                      {isEditing ? <button className="primary-action" type="button" onClick={() => saveEdit(interpretation)} disabled={isLoading}>Save edit</button> : <button className="primary-action" type="button" onClick={() => confirmInterpretation(interpretation)} disabled={isLoading}>{interpretation.canonical_event_type === "SETUP_EVENT" && setupEntities(interpretation).length > 1 ? "Confirm all" : "Confirm"}</button>}
                      {isEditing ? <button type="button" onClick={() => setEditingId(null)} disabled={isLoading}>Cancel edit</button> : <button type="button" onClick={() => startEdit(interpretation)} disabled={isLoading}>Edit</button>}
                      <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>Discard</button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      )}

      <section className="panel">
        <h2>Projects</h2>
        <form className="row" onSubmit={createProject}>
          <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="New project name" />
          <button type="submit" disabled={isLoading}>Create project</button>
        </form>
        <div className="list">
          {projects.map((project) => (
            <button className={project.id === selectedProjectId ? "project selected" : "project"} key={project.id} onClick={() => setSelectedProjectId(project.id)} type="button">
              Open {project.name}
            </button>
          ))}
          {projects.length === 0 && <p>No projects yet.</p>}
        </div>
      </section>

      {projectDetail && (
        <section className="panel">
          <h2>{projectDetail.name}</h2>

          <form className="raw-note" onSubmit={submitNaturalInput}>
            <label htmlFor="natural-input">ورودی طبیعی پروژه را فارسی بنویس</label>
            <textarea id="natural-input" value={naturalText} onChange={(event) => setNaturalText(event.target.value)} placeholder="مثلا: مش رحیم امروز کار کرد" />
            <div className="examples">
              <strong>نمونه‌ها</strong>
              <div className="example-buttons">
                {exampleInputs.map((input) => <button key={input} type="button" onClick={() => setNaturalText(input)}>{input}</button>)}
              </div>
            </div>
            <button type="submit" disabled={isLoading}>{loadingAction === "Processing natural input" ? "Processing..." : "Add to project"}</button>
          </form>

          <div className="totals">
            <div><span>Work Amount</span><strong>{operatingSummary?.total_work_amount ?? "0"}</strong></div>
            <div><span>Invoices</span><strong>{operatingSummary?.total_invoice_amount ?? "0"}</strong></div>
            <div><span>Payments</span><strong>{operatingSummary?.total_payments ?? "0"}</strong></div>
          </div>

          <section className="subsection">
            <h3>Project context</h3>
            <div className="cards compact-list">
              {workers.map((worker) => <article className="card" key={worker.id}><strong>{worker.name}</strong><p>{worker.type}{worker.phone ? ` · ${worker.phone}` : ""}{worker.role_detail ? ` · ${worker.role_detail}` : ""}</p></article>)}
              {workers.length === 0 && <p>No project context yet.</p>}
            </div>
          </section>

          <section className="subsection">
            <h3>Persistent state</h3>
            <div className="cards compact-list">
              {workerStates.map((state) => <article className="card" key={state.id}><strong>{state.name}</strong><p>{state.role} · days: {state.total_days_worked} · quantity: {state.total_quantity} {state.unit ?? ""} · balance: {state.financial_balance}</p></article>)}
              {workerStates.length === 0 && <p>No state yet.</p>}
            </div>
          </section>

          <section className="subsection">
            <h3>History log</h3>
            <div className="cards">
              {history.map((entry) => {
                const semanticType = typeof entry.delta === "object" && entry.delta !== null && "canonical_event_type" in entry.delta ? String(entry.delta.canonical_event_type) : entry.change_type;
                return <article className={semanticType === "NOTE_EVENT" ? "card uncertain" : "card"} key={entry.id}><div className="card-header"><strong>{semanticType}</strong><span>{formatDateTime(entry.created_at)}</span></div><p>{entry.input_text}</p><small>{JSON.stringify(entry.delta)}</small></article>;
              })}
              {history.length === 0 && <p>No history yet.</p>}
            </div>
          </section>

          <section className="subsection">
            <h3>Invoices</h3>
            <div className="cards compact-list">
              {invoices.map((invoice) => <article className="card" key={invoice.id}><strong>Vendor #{invoice.vendor_id}</strong><p>{invoice.total_amount} · {invoice.status}</p></article>)}
              {invoices.length === 0 && <p>No invoices yet.</p>}
            </div>
          </section>

          <section className="subsection">
            <h3>Payments</h3>
            <div className="cards compact-list">
              {payments.map((payment) => <article className="card" key={payment.id}><strong>{payment.amount}</strong><p>Entity #{payment.entity_id} · {payment.type}</p></article>)}
              {payments.length === 0 && <p>No payments yet.</p>}
            </div>
          </section>

          <section className="subsection">
            <h3>Vendor debt</h3>
            <div className="cards compact-list">
              {operatingSummary?.vendor_debts.map((debt) => <article className="card" key={debt.vendor_id}><strong>{debt.vendor_name}</strong><p>Debt: {debt.debt} · Invoices: {debt.invoice_total} · Paid: {debt.paid_total}</p></article>)}
              {(!operatingSummary || operatingSummary.vendor_debts.length === 0) && <p>No vendor debt yet.</p>}
            </div>
          </section>

          <section className="subsection">
            <h3>Input history</h3>
            <div className="raw-entry-list">
              {rawEntries.map((entry) => <article className="raw-entry" key={entry.id}><div><strong>Entry #{entry.id}</strong><p>{entry.text}</p><small>{entry.status} · {formatDateTime(entry.created_at)}</small></div></article>)}
              {rawEntries.length === 0 && <p>No inputs yet.</p>}
            </div>
          </section>
        </section>
      )}
    </main>
  );
}

export default App;
