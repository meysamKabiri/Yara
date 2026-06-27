import { FormEvent, useMemo, useState } from "react";
import {
  ArrowDownCircle,
  ArrowUpCircle,
  Banknote,
  CheckCircle2,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Clock,
  Coins,
  CreditCard,
  FileText,
  Landmark,
  Mic,
  Paperclip,
  Phone,
  ReceiptText,
  Scale,
  Send,
  Users,
} from "lucide-react";
import { HistoryEntry, Invoice, OperatingSummary, Payment, PendingInterpretation, ProjectDetail, RawEntry, Worker, WorkerType, WorkLog } from "../api";

type PersonKind = WorkerType | "OTHER";

const ROLE_LABELS: Record<PersonKind, string> = {
  CLIENT: "کارفرما",
  DAILY_WORKER: "کارگر روزمزد",
  SKILLED_WORKER: "نیروی متخصص",
  VENDOR: "فروشنده / تامین‌کننده",
  OTHER: "سایر",
};

const ROLE_ORDER: PersonKind[] = ["CLIENT", "SKILLED_WORKER", "DAILY_WORKER", "VENDOR", "OTHER"];

const DIRECTION_LABELS: Record<string, string> = {
  INCOMING: "دریافتی",
  OUTGOING: "پرداختی",
  DEBT: "بدهی پرداخت‌نشده",
  DEFERRED: "پرداخت مدت‌دار",
};

const PAYMENT_TYPE_LABELS: Record<string, string> = {
  CASH: "نقدی",
  BANK_TRANSFER: "انتقال بانکی",
  CHECK: "چک",
  OTHER: "سایر",
};

const UNKNOWN_LABEL = "نامشخص";

type TabKey = "summary" | "people" | "financial" | "payables" | "notes" | "pending";

type ProjectDetailPageProps = {
  project: ProjectDetail | null;
  summary: OperatingSummary | null;
  workers: Worker[];
  pendingInterpretations: PendingInterpretation[];
  workLogs: WorkLog[];
  payments: Payment[];
  invoices: Invoice[];
  history: HistoryEntry[];
  rawEntries: RawEntry[];
  text: string;
  examples: string[];
  isLoading: boolean;
  onBack: () => void;
  onTextChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onVoicePlaceholder: () => void;
  onAttachPlaceholder: () => void;
  successMessage: string | null;
  onConfirmPending: (interpretation: PendingInterpretation) => void;
  onEditPending: (interpretation: PendingInterpretation) => void;
  onDiscardPending: (interpretation: PendingInterpretation) => void;
};

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function date(value: string): string {
  return new Date(value).toLocaleString("fa-IR");
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString("fa-IR");
}

function personKind(worker: Worker): PersonKind {
  if (["CLIENT", "DAILY_WORKER", "SKILLED_WORKER", "VENDOR"].includes(worker.type)) {
    return worker.type;
  }
  return "OTHER";
}

function PersonCard({ worker }: { worker: Worker }) {
  const roleLabel = ROLE_LABELS[personKind(worker)] ?? ROLE_LABELS.OTHER;
  return (
    <article className="visibility-person-card">
      <div className="vpc-head">
        <strong>{worker.name}</strong>
        <mark className="role-pill">{roleLabel}</mark>
      </div>
      <div className="vpc-detail-list">
        <span>نقش: {roleLabel}</span>
        {worker.role_detail && <span>تخصص/توضیح: {worker.role_detail}</span>}
      </div>
      <div className="vpc-meta">
        {worker.phone && <span><Phone size={12} />{worker.phone}</span>}
        {worker.account_number && <span><CreditCard size={12} />{worker.account_number}</span>}
        {worker.daily_rate && Number(worker.daily_rate) > 0 && <span><Clock size={12} />دستمزد روزانه: {money(worker.daily_rate)}</span>}
      </div>
    </article>
  );
}

function PaymentRow({ payment, workerMap }: { payment: Payment; workerMap: Record<number, Worker> }) {
  const person = workerMap[payment.entity_id];
  const isIncoming = payment.direction === "INCOMING";
  const isDeferred = payment.direction === "DEFERRED";
  const directionClass = isIncoming ? "trx-incoming" : isDeferred ? "trx-deferred" : "trx-outgoing";
  const directionLabel = DIRECTION_LABELS[payment.direction] ?? UNKNOWN_LABEL;
  const methodLabel = isDeferred && payment.type !== "CHECK" ? "مدت‌دار" : PAYMENT_TYPE_LABELS[payment.type] ?? UNKNOWN_LABEL;
  return (
    <div className={`visibility-trx-row ${directionClass}`}>
      <div className="trx-main">
        <span className="trx-person">{person?.name ?? `فرد ${payment.entity_id}`}</span>
        <span className="trx-amount">{money(payment.amount)}</span>
      </div>
      <div className="trx-meta">
        <span>{shortDate(payment.created_at)}</span>
        <span>{directionLabel}</span>
        <span>{methodLabel}</span>
        {payment.due_date && <span>سررسید: {shortDate(payment.due_date)}</span>}
      </div>
    </div>
  );
}

function InvoiceRow({ invoice, workerMap }: { invoice: Invoice; workerMap: Record<number, Worker> }) {
  const vendor = workerMap[invoice.vendor_id];
  const statusLabel = invoice.status === "OPEN" ? "پرداخت‌نشده" : invoice.status === "PARTIAL" ? "بخشی پرداخت شده" : "پرداخت شده";
  return (
    <div className="visibility-trx-row trx-payable">
      <div className="trx-main">
        <span className="trx-person">{vendor?.name ?? `فروشنده ${invoice.vendor_id}`}</span>
        <span className="trx-amount">{money(invoice.total_amount)}</span>
      </div>
      <div className="trx-meta">
        <span>{shortDate(invoice.created_at)}</span>
        <span className={`status-badge status-${invoice.status.toLowerCase()}`}>{statusLabel}</span>
        {invoice.description && <span>{invoice.description}</span>}
      </div>
    </div>
  );
}

function EmptyState({ children }: { children: string }) {
  return <p className="empty-state">{children}</p>;
}

function pendingTitle(pi: PendingInterpretation): string {
  if (pi.semantic_action === "SET_ROLE") return "تعریف طرف حساب";
  if (pi.semantic_action === "ENTITY_UPDATE" || pi.domain_route?.domain === "ENTITY_UPDATE") return "به‌روزرسانی اطلاعات فرد";
  if (pi.canonical_event_type === "FINANCIAL_EVENT") return "ثبت مالی";
  if (pi.semantic_action === "NOTE") return "یادداشت";
  return "مورد در انتظار بررسی";
}

function pendingEntityName(pi: PendingInterpretation): string | null {
  const entity = pi.extracted_entities?.[0];
  return typeof entity?.name === "string" && entity.name.trim() ? entity.name.trim() : null;
}

function pendingFieldUpdates(pi: PendingInterpretation): string[] {
  const entity = pi.extracted_entities?.[0] ?? {};
  const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
    ? entity.field_updates as Record<string, unknown>
    : {};
  const parts: string[] = [];
  const phone = updates.phone ?? entity.phone;
  const account = updates.account_number ?? entity.account_number;
  const dailyRate = updates.daily_rate ?? entity.daily_rate;
  const notes = updates.notes ?? entity.notes;
  if (phone) parts.push(`شماره تماس: ${String(phone)}`);
  if (account) parts.push(`شماره حساب: ${String(account)}`);
  if (dailyRate) parts.push(`دستمزد روزانه: ${money(String(dailyRate))}`);
  if (notes) parts.push(`توضیحات: ${String(notes)}`);
  return parts;
}

function TabBar({ tabs, activeTab, onTabChange }: { tabs: { key: TabKey; label: string; count?: number }[]; activeTab: TabKey; onTabChange: (key: TabKey) => void }) {
  return (
    <nav className="detail-tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={activeTab === tab.key}
          className={activeTab === tab.key ? "tab-active" : ""}
          type="button"
          onClick={() => onTabChange(tab.key)}
        >
          {tab.label}
          {tab.count !== undefined && tab.count > 0 && <mark className="count-badge">{tab.count.toLocaleString("fa-IR")}</mark>}
        </button>
      ))}
    </nav>
  );
}

export function ProjectDetailPage({
  project, summary, workers, pendingInterpretations, payments, invoices, history,
  rawEntries, text, examples, isLoading, onBack, onTextChange, onSubmit,
  onVoicePlaceholder, onAttachPlaceholder, successMessage,
  onConfirmPending, onEditPending, onDiscardPending,
}: ProjectDetailPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("summary");

  const paidOut = summary ? Number(summary.total_paid_out) : payments.filter((p) => p.direction === "OUTGOING" || p.direction === "DEFERRED").reduce((t, p) => t + Number(p.amount || 0), 0);
  const received = summary ? Number(summary.total_received_from_client ?? summary.total_received) : payments.filter((p) => p.direction === "INCOMING").reduce((t, p) => t + Number(p.amount || 0), 0);
  const payables = Number(summary?.open_payables ?? 0);
  const deferredAmount = summary ? Number(summary.deferred_amount ?? 0) : payments.filter((p) => p.direction === "DEFERRED").reduce((t, p) => t + Number(p.amount || 0), 0);
  const checkAmount = summary ? Number(summary.check_amount ?? 0) : payments.filter((p) => p.type === "CHECK").reduce((t, p) => t + Number(p.amount || 0), 0);
  const netBalance = Number(summary?.project_balance ?? received - paidOut - payables);
  const notes = history.filter((entry) => entry.change_type === "NOTE");
  const pending = pendingInterpretations.filter((pi) => pi.status === "PENDING" || pi.status === "EDITED");

  const workerMap: Record<number, Worker> = useMemo(() => {
    const map: Record<number, Worker> = {};
    for (const w of workers) map[w.id] = w;
    return map;
  }, [workers]);

  const groupedPeople = useMemo(() => {
    const groups: Record<PersonKind, Worker[]> = { CLIENT: [], DAILY_WORKER: [], SKILLED_WORKER: [], VENDOR: [], OTHER: [] };
    for (const w of workers) {
      const kind = personKind(w);
      if (groups[kind]) groups[kind].push(w);
      else groups.OTHER.push(w);
    }
    return groups;
  }, [workers]);

  const confirmedPayments = useMemo(() => {
    return [...payments].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  }, [payments]);

  const openInvoices = useMemo(() => {
    return invoices.filter((inv) => inv.status === "OPEN" || inv.status === "PARTIAL");
  }, [invoices]);

  const deferredPayments = useMemo(() => {
    return confirmedPayments.filter((payment) => payment.direction === "DEFERRED" || payment.type === "CHECK");
  }, [confirmedPayments]);

  const tabs = [
    { key: "summary" as TabKey, label: "خلاصه" },
    { key: "people" as TabKey, label: "افراد", count: workers.length },
    { key: "financial" as TabKey, label: "مالی", count: confirmedPayments.length },
    { key: "payables" as TabKey, label: "بدهی‌ها / چک‌ها", count: openInvoices.length + deferredPayments.length },
    { key: "notes" as TabKey, label: "یادداشت‌ها", count: notes.length },
    { key: "pending" as TabKey, label: "در انتظار تایید", count: pending.length },
  ];

  if (!project) {
    return <div className="empty-page">برای شروع، یک پروژه را از خانه باز کنید.</div>;
  }

  return (
    <div className="page-stack project-workspace">
      <section className="project-topbar">
        <button className="icon-button" type="button" onClick={onBack} aria-label="بازگشت"><ChevronRight aria-hidden="true" size={22} /></button>
        <div>
          <span className="eyebrow">جزئیات پروژه</span>
          <h1>{project.name}</h1>
        </div>
      </section>

      <section className="ai-work-card">
        <div className="section-title compact-title">
          <div>
            <span className="eyebrow">ورودی هوشمند پروژه</span>
            <h2>به یارا بگویید چه اتفاقی افتاد</h2>
          </div>
          <mark className="project-pill">{project.name}</mark>
        </div>
        <form className="chat-composer" onSubmit={onSubmit}>
          <textarea value={text} onChange={(event) => onTextChange(event.target.value)} placeholder="مثلا: میثم ۲۰۰ میلیون پول داد برای شروع پروژه" />
          <div className="chat-actions icon-actions">
            <button type="button" onClick={onVoicePlaceholder} aria-label="ضبط صدا"><Mic aria-hidden="true" size={20} /></button>
            <button type="button" onClick={onAttachPlaceholder} aria-label="افزودن فایل"><Paperclip aria-hidden="true" size={20} /></button>
            <button className="primary-action send-button" type="submit" disabled={isLoading || !text.trim()} aria-label="ارسال"><Send aria-hidden="true" size={20} /></button>
          </div>
        </form>
        <div className="example-chip-list">
          {examples.slice(0, 4).map((example) => <button key={example} type="button" onClick={() => onTextChange(example)}>{example}</button>)}
        </div>
      </section>

      {successMessage && <div className="success-feedback"><CheckCircle2 aria-hidden="true" size={18} />{successMessage}</div>}

      <TabBar tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />

      {activeTab === "summary" && (
        <div className="detail-tab-content">
          <section className="summary-grid six-up project-summary-grid">
            <article className="metric-card positive">
              <ArrowDownCircle aria-hidden="true" />
              <span>دریافتی از کارفرما</span>
              <strong>{money(received)}</strong>
              <small>پول تاییدشده ورودی به پروژه</small>
            </article>
            <article className="metric-card negative">
              <ArrowUpCircle aria-hidden="true" />
              <span>پرداخت‌شده</span>
              <strong>{money(paidOut)}</strong>
              <small>شامل پرداخت نقدی، بانکی و مدت‌دار</small>
            </article>
            <article className="metric-card pending">
              <ReceiptText aria-hidden="true" />
              <span>بدهی باز</span>
              <strong>{money(payables)}</strong>
              <small>پرداخت‌های انجام‌نشده</small>
            </article>
            <article className="metric-card pending">
              <Banknote aria-hidden="true" />
              <span>چک / پرداخت مدت‌دار</span>
              <strong>{money(deferredAmount || checkAmount)}</strong>
              <small>در عدد پرداخت‌شده هم حساب شده است</small>
            </article>
            <article className={netBalance >= 0 ? "metric-card positive" : "metric-card negative"}>
              <Scale aria-hidden="true" />
              <span>مانده پروژه</span>
              <strong>{money(netBalance >= 0 ? Number(summary?.available_balance ?? netBalance) : netBalance)}</strong>
              <small>{netBalance >= 0 ? "موجودی پروژه" : "کسری بودجه"}</small>
            </article>
            <article className={pending.length > 0 ? "metric-card pending" : "metric-card"}>
              <ClipboardList aria-hidden="true" />
              <span>موارد در انتظار تایید</span>
              <strong>{pending.length.toLocaleString("fa-IR")}</strong>
              <small>{pending.length > 0 ? "هنوز در totals حساب نشده‌اند" : "همه موارد بررسی شده‌اند"}</small>
            </article>
          </section>
          <p className="summary-helper">مانده پروژه = دریافتی از کارفرما - پرداخت‌شده - بدهی باز. پرداخت‌شده شامل چک‌ها و پرداخت‌های مدت‌دار تاییدشده هم هست.</p>
        </div>
      )}

      {activeTab === "people" && (
        <div className="detail-tab-content">
          {workers.length === 0 ? (
            <EmptyState>هیچ شخصی ثبت نشده است</EmptyState>
          ) : (
            <div className="visibility-people-grid">
              {ROLE_ORDER.map((role) => {
                const roleWorkers = groupedPeople[role];
                if (!roleWorkers || roleWorkers.length === 0) return null;
                return (
                  <div key={role} className="visibility-role-group">
                    <h4 className="role-group-title">
                      <Users size={14} />
                      {ROLE_LABELS[role] ?? "سایر"}
                      <mark>{roleWorkers.length.toLocaleString("fa-IR")}</mark>
                    </h4>
                    <div className="visibility-people-list">
                      {roleWorkers.map((worker) => <PersonCard key={worker.id} worker={worker} />)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {activeTab === "financial" && (
        <div className="detail-tab-content">
          {confirmedPayments.length === 0 ? (
            <EmptyState>هیچ تراکنشی ثبت نشده است</EmptyState>
          ) : (
            <div className="visibility-trx-list">
              {confirmedPayments.map((payment) => <PaymentRow key={payment.id} payment={payment} workerMap={workerMap} />)}
            </div>
          )}
        </div>
      )}

      {activeTab === "payables" && (
        <div className="detail-tab-content">
          {openInvoices.length === 0 && deferredPayments.length === 0 && (!summary?.vendor_debts || summary.vendor_debts.length === 0) ? (
            <EmptyState>بدهی یا چک ثبت نشده است</EmptyState>
          ) : (
            <>
              {openInvoices.length > 0 && (
                <section className="payable-section">
                  <h4 className="role-group-title"><ReceiptText size={14} />بدهی‌های باز</h4>
                  <div className="visibility-trx-list">
                    {openInvoices.map((invoice) => <InvoiceRow key={invoice.id} invoice={invoice} workerMap={workerMap} />)}
                  </div>
                </section>
              )}
              {deferredPayments.length > 0 && (
                <section className="payable-section">
                  <h4 className="role-group-title"><Banknote size={14} />چک‌ها / پرداخت‌های مدت‌دار</h4>
                  <div className="visibility-trx-list">
                    {deferredPayments.map((payment) => <PaymentRow key={payment.id} payment={payment} workerMap={workerMap} />)}
                  </div>
                </section>
              )}
              {summary && summary.vendor_debts && summary.vendor_debts.length > 0 && (
                <div className="visibility-vendor-debts">
                  <h4 className="role-group-title">خلاصه بدهی فروشندگان</h4>
                  {summary.vendor_debts.map((debt) => (
                    <div key={debt.vendor_id} className="visibility-trx-row trx-payable vendor-debt-row">
                      <div className="trx-main">
                        <span className="trx-person">{debt.vendor_name}</span>
                        <span className="trx-amount">{money(debt.debt)}</span>
                      </div>
                      <div className="trx-meta">
                        <span>فاکتور: {money(debt.invoice_total)}</span>
                        <span>پرداخت شده: {money(debt.paid_total)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {activeTab === "notes" && (
        <div className="detail-tab-content">
          {notes.length === 0 ? (
            <EmptyState>یادداشتی ثبت نشده است</EmptyState>
          ) : (
            <div className="visibility-notes-list">
              {notes.map((note) => (
                <article key={note.id} className="visibility-note-card">
                  <div className="vpc-meta">
                    <span><Clock size={12} />{shortDate(note.created_at)}</span>
                  </div>
                  <p>{note.input_text}</p>
                </article>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "pending" && (
        <div className="detail-tab-content">
          {pending.length === 0 ? (
            <EmptyState>بدون مورد در انتظار تایید</EmptyState>
          ) : (
            <div className="visibility-pending-list">
              {pending.map((pi) => (
                <article key={pi.id} className="visibility-pending-card">
                  <div className="vpc-head">
                    <strong>{pendingTitle(pi)}</strong>
                    <mark className="role-pill">در انتظار تایید</mark>
                  </div>
                  <p className="pending-text">{pi.matched_input_text || pi.description || pi.raw_input_text}</p>
                  <div className="vpc-meta">
                    {pendingEntityName(pi) && <span>فرد: {pendingEntityName(pi)}</span>}
                    {pi.extracted_amount && <span>مبلغ: {money(pi.extracted_amount)}</span>}
                    {pi.financial_direction && <span>{DIRECTION_LABELS[pi.financial_direction] ?? UNKNOWN_LABEL}</span>}
                    {pi.payment_method && <span>{PAYMENT_TYPE_LABELS[pi.payment_method] ?? UNKNOWN_LABEL}</span>}
                    {pendingFieldUpdates(pi).map((part) => <span key={part}>{part}</span>)}
                    <span>{date(pi.created_at)}</span>
                  </div>
                  <div className="modal-actions pending-actions">
                    <button className="primary-action" type="button" onClick={() => onConfirmPending(pi)} disabled={isLoading}>
                      تایید
                    </button>
                    <button type="button" onClick={() => onEditPending(pi)} disabled={isLoading}>
                      ویرایش
                    </button>
                    <button className="danger-action" type="button" onClick={() => onDiscardPending(pi)} disabled={isLoading}>
                      نادیده گرفتن
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
