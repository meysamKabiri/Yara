import { FormEvent, useEffect, useState } from "react";
import { api, HistoryEntry, Invoice, OperatingSummary, Payment, Project, ProjectDetail, RawEntry, Worker, WorkerState } from "./api";

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
      await api.processNaturalInput(selectedProjectId, naturalText.trim());
      setNaturalText("");
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
