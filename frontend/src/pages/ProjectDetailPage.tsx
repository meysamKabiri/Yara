import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ArrowDownCircle,
  ArrowUpCircle,
  Banknote,
  CheckCircle2,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Clock,
  Coins,
  CreditCard,
  FileText,
  Hammer,
  Landmark,
  Mic,
  Paperclip,
  Phone,
  Pencil,
  ReceiptText,
  Scale,
  Send,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { api, HistoryEntry, Invoice, OperatingSummary, PayableCorrectionPayload, Payment, PaymentCorrectionPayload, PayableReportRow, PendingInterpretation, ProjectDetail, ProjectReportResponse, RawEntry, Worker, WorkerReportRow, WorkerType, WorkLog, WorkLogCorrectionPayload } from "../api";
import { PersianDatePicker } from "../components/PersianDatePicker";
import { quickReportRange, ReportFilterKey } from "../utils/jalaliDate";

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

const REPORT_PAYABLE_KIND_LABELS: Record<PayableReportRow["kind"], string> = {
  vendor_payable: "بدهی باز",
  deferred_check: "چک / پرداخت مدت‌دار",
  worker_labor: "کارکرد پرداخت‌نشده",
};

type TabKey = "summary" | "people" | "labor" | "financial" | "payables" | "notes" | "reports" | "pending";
type CorrectionTarget =
  | { kind: "payment"; record: Payment }
  | { kind: "workLog"; record: WorkLog }
  | { kind: "payable"; record: Invoice }
  | { kind: "note"; record: HistoryEntry };
type VoidTarget = CorrectionTarget;

const CSV_EXPORTS = [
  { label: "خلاصه پروژه", path: "summary.csv" },
  { label: "پرداخت‌ها", path: "payments.csv" },
  { label: "افراد", path: "people.csv" },
  { label: "کارکرد کارگران", path: "work-logs.csv" },
  { label: "بدهی‌ها و چک‌ها", path: "payables.csv" },
  { label: "یادداشت‌ها", path: "notes.csv" },
];

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
  onCorrectPayment: (projectId: number, paymentId: number, payload: PaymentCorrectionPayload) => Promise<void>;
  onVoidPayment: (projectId: number, paymentId: number, reason?: string | null) => Promise<void>;
  onCorrectWorkLog: (projectId: number, workLogId: number, payload: WorkLogCorrectionPayload) => Promise<void>;
  onVoidWorkLog: (projectId: number, workLogId: number, reason?: string | null) => Promise<void>;
  onCorrectPayable: (projectId: number, payableId: number, payload: PayableCorrectionPayload) => Promise<void>;
  onVoidPayable: (projectId: number, payableId: number, reason?: string | null) => Promise<void>;
  onCorrectNote: (projectId: number, noteId: number, payload: { text: string; correction_note?: string | null }) => Promise<void>;
  onVoidNote: (projectId: number, noteId: number, reason?: string | null) => Promise<void>;
  onUpdateProject: (projectId: number, payload: { name: string; description?: string | null }) => Promise<void>;
  requestedTab?: string | null;
};

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function days(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} روز`;
}

function date(value: string): string {
  return new Date(value).toLocaleString("fa-IR");
}

function shortDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("fa-IR");
}

function exportHref(projectId: number, path: string, fromDate: string, toDate: string): string {
  const params = new URLSearchParams();
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  const query = params.toString();
  return `/api/projects/${projectId}/exports/${path}${query ? `?${query}` : ""}`;
}

function CsvExportMenu({ projectId, fromDate, toDate }: { projectId: number; fromDate: string; toDate: string }) {
  return (
    <details className="csv-export-menu">
      <summary>خروجی CSV</summary>
      <div className="csv-export-panel">
        <p>خروجی‌ها فقط از رکوردهای تاییدشده ساخته می‌شوند.</p>
        <div className="csv-export-actions">
          {CSV_EXPORTS.map((item) => (
            <a key={item.path} href={exportHref(projectId, item.path, fromDate, toDate)} download>
              {item.label}
            </a>
          ))}
        </div>
      </div>
    </details>
  );
}

function personKind(worker: Worker): PersonKind {
  if (["CLIENT", "DAILY_WORKER", "SKILLED_WORKER", "VENDOR"].includes(worker.type)) {
    return worker.type;
  }
  return "OTHER";
}

type LaborStats = {
  totalDays: number;
  totalCost: number;
  paidOut: number;
  balance: number;
};

function PersonCard({ worker, laborStats, onOpen }: { worker: Worker; laborStats?: LaborStats; onOpen: (workerId: number) => void }) {
  const roleLabel = ROLE_LABELS[personKind(worker)] ?? ROLE_LABELS.OTHER;
  const showLabor = worker.type === "DAILY_WORKER" && laborStats && (laborStats.totalDays > 0 || laborStats.totalCost > 0 || laborStats.paidOut > 0);
  return (
    <button className="visibility-person-card clickable-card" type="button" onClick={() => onOpen(worker.id)}>
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
        {showLabor && <span><Hammer size={12} />کارکرد ثبت‌شده: {days(laborStats.totalDays)}</span>}
        {showLabor && <span>مبلغ کارکرد: {money(laborStats.totalCost)}</span>}
        {showLabor && <span>پرداخت‌شده: {money(laborStats.paidOut)}</span>}
        {showLabor && <span>مانده تقریبی: {money(laborStats.balance)}</span>}
      </div>
    </button>
  );
}

function VoidedBadge({ isVoided }: { isVoided?: boolean }) {
  return isVoided ? <mark className="voided-badge">باطل‌شده</mark> : null;
}

function RecordActions({ disabled, onEdit, onVoid }: { disabled?: boolean; onEdit: () => void; onVoid: () => void }) {
  return (
    <div className="record-actions">
      <button className="icon-button" type="button" onClick={onEdit} disabled={disabled} aria-label="ویرایش">
        <Pencil aria-hidden="true" size={16} />
      </button>
      <button className="icon-button danger-icon" type="button" onClick={onVoid} disabled={disabled} aria-label="باطل کردن">
        <Trash2 aria-hidden="true" size={16} />
      </button>
    </div>
  );
}

function PaymentRow({ payment, workerMap, onEdit, onVoid }: { payment: Payment; workerMap: Record<number, Worker>; onEdit: () => void; onVoid: () => void }) {
  const person = workerMap[payment.entity_id];
  const isIncoming = payment.direction === "INCOMING";
  const isDeferred = payment.direction === "DEFERRED";
  const directionClass = isIncoming ? "trx-incoming" : isDeferred ? "trx-deferred" : "trx-outgoing";
  const directionLabel = DIRECTION_LABELS[payment.direction] ?? UNKNOWN_LABEL;
  const methodLabel = isDeferred && payment.type !== "CHECK" ? "مدت‌دار" : PAYMENT_TYPE_LABELS[payment.type] ?? UNKNOWN_LABEL;
  return (
    <div className={`visibility-trx-row ${directionClass}${payment.is_voided ? " is-voided" : ""}`}>
      <div className="trx-main">
        <span className="trx-person">{person?.name ?? `فرد ${payment.entity_id}`}</span>
        <span className="trx-amount">{money(payment.amount)}</span>
      </div>
      <div className="trx-meta">
        <VoidedBadge isVoided={payment.is_voided} />
        <span>{shortDate(payment.created_at)}</span>
        <span>{directionLabel}</span>
        <span>{methodLabel}</span>
        {payment.due_date && <span>سررسید: {shortDate(payment.due_date)}</span>}
        {payment.description && <span>{payment.description}</span>}
        {payment.void_reason && <span>علت: {payment.void_reason}</span>}
      </div>
      <RecordActions disabled={payment.is_voided} onEdit={onEdit} onVoid={onVoid} />
    </div>
  );
}

function InvoiceRow({ invoice, workerMap, onEdit, onVoid }: { invoice: Invoice; workerMap: Record<number, Worker>; onEdit: () => void; onVoid: () => void }) {
  const vendor = workerMap[invoice.vendor_id];
  const statusLabel = invoice.status === "OPEN" ? "پرداخت‌نشده" : invoice.status === "PARTIAL" ? "بخشی پرداخت شده" : "پرداخت شده";
  return (
    <div className={`visibility-trx-row trx-payable${invoice.is_voided ? " is-voided" : ""}`}>
      <div className="trx-main">
        <span className="trx-person">{vendor?.name ?? `فروشنده ${invoice.vendor_id}`}</span>
        <span className="trx-amount">{money(invoice.total_amount)}</span>
      </div>
      <div className="trx-meta">
        <VoidedBadge isVoided={invoice.is_voided} />
        <span>{shortDate(invoice.created_at)}</span>
        <span className={`status-badge status-${invoice.status.toLowerCase()}`}>{statusLabel}</span>
        {invoice.description && <span>{invoice.description}</span>}
        {invoice.void_reason && <span>علت: {invoice.void_reason}</span>}
      </div>
      <RecordActions disabled={invoice.is_voided} onEdit={onEdit} onVoid={onVoid} />
    </div>
  );
}

function WorkLogRow({ workLog, workerMap, onEdit, onVoid }: { workLog: WorkLog; workerMap: Record<number, Worker>; onEdit: () => void; onVoid: () => void }) {
  const worker = workerMap[workLog.worker_id];
  return (
    <div className={`visibility-trx-row labor-row${workLog.is_voided ? " is-voided" : ""}`}>
      <div className="trx-main">
        <span className="trx-person">{worker?.name ?? `کارگر ${workLog.worker_id}`}</span>
        <span className="trx-amount">{workLog.total_amount ? money(workLog.total_amount) : "نرخ روزانه ثبت نشده"}</span>
      </div>
      <div className="trx-meta">
        <VoidedBadge isVoided={workLog.is_voided} />
        <span>{workLog.period_label || "بازه ثبت نشده"}</span>
        <span>{days(workLog.quantity)}</span>
        <span>{workLog.rate_per_unit ? `نرخ: ${money(workLog.rate_per_unit)}` : "نرخ روزانه ثبت نشده"}</span>
        <span>{shortDate(workLog.created_at)}</span>
        {workLog.description && <span>{workLog.description}</span>}
        {workLog.void_reason && <span>علت: {workLog.void_reason}</span>}
      </div>
      <RecordActions disabled={workLog.is_voided} onEdit={onEdit} onVoid={onVoid} />
    </div>
  );
}

function WorkLogGroupCard({ worker, logs, laborStats, onEditLog, onVoidLog }: { worker: Worker; logs: WorkLog[]; laborStats?: LaborStats; onEditLog: (log: WorkLog) => void; onVoidLog: (log: WorkLog) => void }) {
  const activeLogs = logs.filter((log) => !log.is_voided);
  const totalDays = laborStats?.totalDays ?? activeLogs.reduce((total, log) => total + Number(log.unit === "day" ? log.quantity || 0 : 0), 0);
  const totalCost = laborStats?.totalCost ?? activeLogs.reduce((total, log) => total + Number(log.total_amount || 0), 0);
  const paidOut = laborStats?.paidOut ?? 0;
  const balance = laborStats?.balance ?? totalCost - paidOut;
  return (
    <article className="worker-labor-card">
      <div className="worker-labor-head">
        <div>
          <strong>{worker.name}</strong>
          <span>{ROLE_LABELS[personKind(worker)] ?? "کارگر"}</span>
        </div>
        <mark className="role-pill">{worker.daily_rate ? `دستمزد: ${money(worker.daily_rate)}` : "دستمزد ثبت نشده"}</mark>
      </div>
      <section className="worker-labor-metrics">
        <div><span>روز کارکرد</span><strong>{days(totalDays)}</strong></div>
        <div><span>مبلغ کارکرد</span><strong>{money(totalCost)}</strong></div>
        <div><span>پرداخت‌شده</span><strong>{money(paidOut)}</strong></div>
        <div><span>مانده</span><strong>{money(balance)}</strong></div>
      </section>
      <div className="worker-labor-logs">
        {logs.map((log) => (
          <div className={`worker-labor-log${log.is_voided ? " is-voided" : ""}`} key={log.id}>
            <div>
              <strong>{log.period_label || "بازه ثبت نشده"} <VoidedBadge isVoided={log.is_voided} /></strong>
              <span>{log.description || log.task_name}</span>
            </div>
            <div>
              <span>{days(log.quantity)}</span>
              <span>{log.rate_per_unit ? money(log.rate_per_unit) : "نرخ ثبت نشده"}</span>
              <strong>{log.total_amount ? money(log.total_amount) : "بدون مبلغ"}</strong>
              <small>{shortDate(log.created_at)}</small>
            </div>
            <RecordActions disabled={log.is_voided} onEdit={() => onEditLog(log)} onVoid={() => onVoidLog(log)} />
          </div>
        ))}
      </div>
    </article>
  );
}

function PersonDetailDrawer({
  worker,
  laborStats,
  payments,
  workLogs,
  invoices,
  vendorDebt,
  onClose,
}: {
  worker: Worker;
  laborStats?: LaborStats;
  payments: Payment[];
  workLogs: WorkLog[];
  invoices: Invoice[];
  vendorDebt: number;
  onClose: () => void;
}) {
  const kind = personKind(worker);
  const activePayments = payments.filter((payment) => !payment.is_voided);
  const activeInvoices = invoices.filter((invoice) => !invoice.is_voided);
  const incoming = activePayments.filter((payment) => payment.direction === "INCOMING");
  const outgoing = activePayments.filter((payment) => payment.direction === "OUTGOING");
  const deferred = activePayments.filter((payment) => payment.direction === "DEFERRED" || payment.type === "CHECK");
  const paid = outgoing.reduce((total, payment) => total + Number(payment.amount || 0), 0);
  const received = incoming.reduce((total, payment) => total + Number(payment.amount || 0), 0);
  const invoiceTotal = activeInvoices.reduce((total, invoice) => total + Number(invoice.total_amount || 0), 0);
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="person-drawer" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-header">
          <div>
            <span className="eyebrow">{ROLE_LABELS[kind] ?? "فرد"}</span>
            <h2>{worker.name}</h2>
            <p>{worker.role_detail || ROLE_LABELS[kind] || "نقش ثبت نشده"}</p>
          </div>
          <button className="modal-close icon-button" type="button" onClick={onClose} aria-label="بستن">
            <X aria-hidden="true" size={20} />
          </button>
        </header>
        <section className="drawer-metrics">
          {kind === "CLIENT" && <><article><span>دریافتی</span><strong>{money(received)}</strong></article><article><span>تعداد پرداخت</span><strong>{incoming.length.toLocaleString("fa-IR")}</strong></article></>}
          {kind === "DAILY_WORKER" && <><article><span>روز کارکرد</span><strong>{days(laborStats?.totalDays ?? 0)}</strong></article><article><span>مبلغ کارکرد</span><strong>{money(laborStats?.totalCost ?? 0)}</strong></article><article><span>پرداخت‌شده</span><strong>{money(laborStats?.paidOut ?? 0)}</strong></article><article><span>مانده</span><strong>{money(laborStats?.balance ?? 0)}</strong></article></>}
          {kind === "SKILLED_WORKER" && <><article><span>پرداخت‌شده</span><strong>{money(paid)}</strong></article><article><span>تعداد پرداخت</span><strong>{outgoing.length.toLocaleString("fa-IR")}</strong></article></>}
          {kind === "VENDOR" && <><article><span>خرید / فاکتور</span><strong>{money(invoiceTotal)}</strong></article><article><span>پرداخت‌شده</span><strong>{money(paid)}</strong></article><article><span>بدهی باز</span><strong>{money(vendorDebt)}</strong></article><article><span>چک / مدت‌دار</span><strong>{money(deferred.reduce((total, payment) => total + Number(payment.amount || 0), 0))}</strong></article></>}
        </section>
        <section className="drawer-section">
          <h3>اطلاعات تماس</h3>
          <dl className="detail-list">
            <div><dt>تلفن</dt><dd>{worker.phone || "ثبت نشده"}</dd></div>
            <div><dt>شماره حساب</dt><dd>{worker.account_number || "ثبت نشده"}</dd></div>
            {worker.daily_rate && <div><dt>دستمزد روزانه</dt><dd>{money(worker.daily_rate)}</dd></div>}
          </dl>
        </section>
        {workLogs.length > 0 && <section className="drawer-section"><h3>سوابق کارکرد</h3><div className="mini-list">{workLogs.map((log) => <div className={`mini-row${log.is_voided ? " is-voided" : ""}`} key={log.id}><strong>{log.total_amount ? money(log.total_amount) : days(log.quantity)}</strong><span>{log.period_label || shortDate(log.created_at)} <VoidedBadge isVoided={log.is_voided} /></span></div>)}</div></section>}
        <section className="drawer-section"><h3>سوابق پرداخت</h3><div className="mini-list">{payments.map((payment) => <div className={`mini-row${payment.is_voided ? " is-voided" : ""}`} key={payment.id}><strong>{money(payment.amount)}</strong><span>{DIRECTION_LABELS[payment.direction] ?? "پرداخت"} <VoidedBadge isVoided={payment.is_voided} /></span></div>)}{payments.length === 0 && <p className="empty-state">پرداختی ثبت نشده است</p>}</div></section>
        {invoices.length > 0 && <section className="drawer-section"><h3>فاکتورها</h3><div className="mini-list">{invoices.map((invoice) => <div className={`mini-row${invoice.is_voided ? " is-voided" : ""}`} key={invoice.id}><strong>{money(invoice.total_amount)}</strong><span>{invoice.description || "فاکتور"} <VoidedBadge isVoided={invoice.is_voided} /></span></div>)}</div></section>}
      </aside>
    </div>
  );
}

function CorrectionModal({
  target,
  workers,
  isLoading,
  onClose,
  onSubmit,
}: {
  target: CorrectionTarget | null;
  workers: Worker[];
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (target: CorrectionTarget, values: Record<string, FormDataEntryValue>) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  useEffect(() => {
    setNote("");
  }, [target]);
  if (!target) return null;
  const title = target.kind === "payment" ? "اصلاح پرداخت" : target.kind === "workLog" ? "اصلاح کارکرد" : target.kind === "payable" ? "اصلاح بدهی" : "اصلاح یادداشت";
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal-shell correction-modal"
        onClick={(event) => event.stopPropagation()}
        onSubmit={async (event) => {
          event.preventDefault();
          const values = Object.fromEntries(new FormData(event.currentTarget).entries());
          await onSubmit(target, values);
        }}
      >
        <header className="modal-header">
          <div>
            <h2 className="modal-title">{title}</h2>
            <p>فقط رکورد تاییدشده اصلاح می‌شود.</p>
          </div>
          <button className="modal-close icon-button" type="button" onClick={onClose} aria-label="بستن">
            <X aria-hidden="true" size={20} />
          </button>
        </header>
        <div className="modal-body correction-form">
          {target.kind === "payment" && (
            <>
              <label><span>شخص</span><select name="entity_id" defaultValue={target.record.entity_id}>{workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>
              <label><span>مبلغ</span><input name="amount" inputMode="decimal" defaultValue={target.record.amount} /></label>
              <label><span>جهت</span><select name="direction" defaultValue={target.record.direction}><option value="INCOMING">دریافت</option><option value="OUTGOING">پرداخت</option><option value="DEFERRED">مدت‌دار</option></select></label>
              <label><span>روش پرداخت</span><select name="type" defaultValue={target.record.type}><option value="CASH">نقدی</option><option value="BANK_TRANSFER">کارت/بانک</option><option value="CHECK">چک</option><option value="OTHER">سایر</option></select></label>
              <label><span>سررسید</span><input name="due_date" defaultValue={target.record.due_date ?? ""} /></label>
              <label><span>توضیح</span><textarea name="description" defaultValue={target.record.description ?? ""} /></label>
            </>
          )}
          {target.kind === "workLog" && (
            <>
              <label><span>کارگر</span><select name="worker_id" defaultValue={target.record.worker_id}>{workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>
              <label><span>عنوان کار</span><input name="task_name" defaultValue={target.record.task_name} /></label>
              <label><span>بازه</span><input name="period_label" defaultValue={target.record.period_label ?? ""} /></label>
              <label><span>مقدار</span><input name="quantity" inputMode="decimal" defaultValue={target.record.quantity} /></label>
              <label><span>واحد</span><select name="unit" defaultValue={target.record.unit}><option value="day">روز</option><option value="meter">متر</option><option value="item">عدد</option><option value="project">پروژه</option><option value="custom">سفارشی</option></select></label>
              <label><span>نرخ</span><input name="rate_per_unit" inputMode="decimal" defaultValue={target.record.rate_per_unit ?? ""} /></label>
              <label><span>توضیح</span><textarea name="description" defaultValue={target.record.description ?? ""} /></label>
            </>
          )}
          {target.kind === "payable" && (
            <>
              <label><span>فروشنده</span><select name="vendor_id" defaultValue={target.record.vendor_id}>{workers.filter((worker) => worker.type === "VENDOR").map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}</select></label>
              <label><span>مبلغ</span><input name="total_amount" inputMode="decimal" defaultValue={target.record.total_amount} /></label>
              <label><span>توضیح</span><textarea name="description" defaultValue={target.record.description ?? ""} /></label>
            </>
          )}
          {target.kind === "note" && (
            <label><span>متن یادداشت</span><textarea name="text" defaultValue={target.record.input_text} /></label>
          )}
          <label><span>یادداشت اصلاح</span><textarea name="correction_note" value={note} onChange={(event) => setNote(event.target.value)} /></label>
        </div>
        <footer className="modal-footer">
          <div className="modal-actions">
            <button className="primary-action" type="submit" disabled={isLoading}>ثبت اصلاح</button>
            <button type="button" onClick={onClose} disabled={isLoading}>انصراف</button>
          </div>
        </footer>
      </form>
    </div>
  );
}

function VoidModal({
  target,
  isLoading,
  onClose,
  onSubmit,
}: {
  target: VoidTarget | null;
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (target: VoidTarget, reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => {
    setReason("");
  }, [target]);
  if (!target) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal-shell correction-modal"
        onClick={(event) => event.stopPropagation()}
        onSubmit={async (event) => {
          event.preventDefault();
          await onSubmit(target, reason);
        }}
      >
        <header className="modal-header">
          <div>
            <h2 className="modal-title">باطل کردن رکورد</h2>
            <p>رکورد حذف نمی‌شود و فقط از محاسبات فعال خارج می‌شود.</p>
          </div>
          <button className="modal-close icon-button" type="button" onClick={onClose} aria-label="بستن">
            <X aria-hidden="true" size={20} />
          </button>
        </header>
        <div className="modal-body correction-form">
          <label><span>علت</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="مثلا ثبت تکراری یا اشتباه" /></label>
        </div>
        <footer className="modal-footer">
          <div className="modal-actions">
            <button className="danger-action" type="submit" disabled={isLoading}>باطل کردن</button>
            <button type="button" onClick={onClose} disabled={isLoading}>انصراف</button>
          </div>
        </footer>
      </form>
    </div>
  );
}

function ProjectEditModal({
  project,
  isLoading,
  onClose,
  onSubmit,
}: {
  project: ProjectDetail;
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (payload: { name: string; description?: string | null }) => Promise<void>;
}) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const trimmedName = name.trim();

  useEffect(() => {
    setName(project.name);
    setDescription(project.description ?? "");
  }, [project.id, project.name, project.description]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal-shell correction-modal project-edit-modal"
        onClick={(event) => event.stopPropagation()}
        onSubmit={async (event) => {
          event.preventDefault();
          if (!trimmedName) return;
          await onSubmit({ name: trimmedName, description: description.trim() || null });
        }}
      >
        <header className="modal-header">
          <div>
            <h2 className="modal-title">ویرایش پروژه</h2>
            <p>نام و توضیح پروژه را به‌روزرسانی کنید.</p>
          </div>
          <button className="modal-close icon-button" type="button" onClick={onClose} aria-label="بستن">
            <X aria-hidden="true" size={20} />
          </button>
        </header>
        <div className="modal-body correction-form">
          <label>
            <span>نام پروژه</span>
            <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
          </label>
          <label>
            <span>توضیح اختیاری</span>
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
        </div>
        <footer className="modal-footer">
          <div className="modal-actions">
            <button className="primary-action" type="submit" disabled={isLoading || !trimmedName}>ذخیره تغییرات</button>
            <button type="button" onClick={onClose} disabled={isLoading}>انصراف</button>
          </div>
        </footer>
      </form>
    </div>
  );
}

function EmptyState({ children }: { children: string }) {
  return <p className="empty-state">{children}</p>;
}

function pendingTitle(pi: PendingInterpretation): string {
  if (pi.semantic_action === "SET_ROLE") return "تعریف طرف حساب";
  if (pi.semantic_action === "WORK_LOG" || pi.canonical_event_type === "WORK_EVENT") return "ثبت کارکرد کارگر";
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
  const si = pi.structured_interpretation as Record<string, unknown> | null;
  const work = typeof si?.work === "object" && si.work !== null ? si.work as Record<string, unknown> : {};
  const quantity = pi.extracted_quantity ?? work.quantity;
  const period = work.period_label;
  const notes = updates.notes ?? entity.notes;
  if (phone) parts.push(`شماره تماس: ${String(phone)}`);
  if (account) parts.push(`شماره حساب: ${String(account)}`);
  if (dailyRate) parts.push(`دستمزد روزانه: ${money(String(dailyRate))}`);
  if (quantity) parts.push(`تعداد روز: ${days(String(quantity))}`);
  if (period) parts.push(`بازه: ${String(period)}`);
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

function ProjectReportsTab({ projectId, pendingCount }: { projectId: number; pendingCount: number }) {
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [report, setReport] = useState<ProjectReportResponse | null>(null);
  const [isReportLoading, setIsReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsReportLoading(true);
    setReportError(null);
    api.getProjectReportSummary(projectId, { from_date: fromDate || undefined, to_date: toDate || undefined })
      .then((nextReport) => {
        if (!cancelled) setReport(nextReport);
      })
      .catch((error: Error) => {
        if (!cancelled) setReportError(error.message || "خطا در دریافت گزارش");
      })
      .finally(() => {
        if (!cancelled) setIsReportLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fromDate, projectId, toDate]);

  const applyQuickFilter = (key: ReportFilterKey) => {
    const range = quickReportRange(key);
    setFromDate(range.from_date);
    setToDate(range.to_date);
  };

  const summary = report?.summary;
  const reportCashBalance = summary ? Number(summary.money_in) - Number(summary.paid_out) : 0;
  return (
    <div className="detail-tab-content reports-tab">
      <section className="report-controls" aria-label="بازه گزارش">
        <PersianDatePicker id="report-from" label="از تاریخ" value={fromDate} onChange={setFromDate} />
        <PersianDatePicker id="report-to" label="تا تاریخ" value={toDate} onChange={setToDate} />
        <div className="quick-filter-group" aria-label="فیلتر سریع">
          <button type="button" onClick={() => applyQuickFilter("week")}>این هفته</button>
          <button type="button" onClick={() => applyQuickFilter("month")}>این ماه</button>
          <button type="button" onClick={() => applyQuickFilter("year")}>امسال</button>
          <button type="button" onClick={() => applyQuickFilter("all")}>همه</button>
        </div>
      </section>

      <div className="report-actions-row">
        <CsvExportMenu projectId={projectId} fromDate={fromDate} toDate={toDate} />
      </div>

      {reportError && <div className="empty-state">{reportError}</div>}
      {isReportLoading && !report && <div className="empty-state">در حال دریافت گزارش...</div>}

      {report && summary && (
        <>
          <section className="report-summary-grid">
            <article className="metric-card positive"><ArrowDownCircle aria-hidden="true" /><span>دریافتی</span><strong>{money(summary.money_in)}</strong><small>پرداخت‌های تاییدشده کارفرما</small></article>
            <article className="metric-card negative"><ArrowUpCircle aria-hidden="true" /><span>پرداخت‌شده</span><strong>{money(summary.paid_out)}</strong><small>بدون چک و بدهی مدت‌دار</small></article>
            <article className={reportCashBalance >= 0 ? "metric-card positive" : "metric-card negative"}><Scale aria-hidden="true" /><span>موجودی نقدی</span><strong>{money(reportCashBalance)}</strong><small>دریافتی - پرداخت‌شده</small></article>
          </section>
          <aside className="debt-notice report-debt-notice" aria-label="بدهی باز">
            <ReceiptText aria-hidden="true" />
            <span>بدهی باز</span>
            <strong>{money(summary.open_payables)}</strong>
            <small>شامل بدهی فروشندگان و مانده کارگران</small>
          </aside>
          <p className="summary-helper">
            گزارش فقط از رکوردهای تاییدشده ساخته می‌شود. موارد در انتظار تایید فعلی: {pendingCount.toLocaleString("fa-IR")}
          </p>

          <section className="report-sections">
            <article className="report-section-card">
              <div className="section-title compact-title">
                <div>
                  <span className="eyebrow">کارفرما</span>
                  <h2>پرداخت‌های کارفرما</h2>
                </div>
              </div>
              {report.client_payments.length === 0 ? (
                <EmptyState>پرداختی از کارفرما ثبت نشده است</EmptyState>
              ) : (
                <div className="report-row-list">
                  {report.client_payments.map((row) => (
                    <article className="report-list-row" key={row.entity_id}>
                      <div className="report-row-head">
                        <strong>{row.name}</strong>
                        <span>{row.payment_count.toLocaleString("fa-IR")} پرداخت</span>
                      </div>
                      <div className="report-row-amount">{money(row.total_paid)}</div>
                      <p className="report-description">آخرین پرداخت: {row.last_payment_at ? shortDate(row.last_payment_at) : "-"}</p>
                    </article>
                  ))}
                </div>
              )}
            </article>

            <WorkerReportSection workers={report.workers} />

            <PayableReportSection payables={report.payables} />
          </section>
        </>
      )}
    </div>
  );
}

function WorkerReportSection({ workers }: { workers: WorkerReportRow[] }) {
  return (
    <article className="report-section-card">
      <div className="section-title compact-title">
        <div>
          <span className="eyebrow">کارگران</span>
          <h2>گزارش کارگران</h2>
        </div>
      </div>
      {workers.length === 0 ? (
        <EmptyState>کارکردی برای کارگران ثبت نشده است</EmptyState>
      ) : (
        <div className="report-row-list">
          {workers.map((row) => (
            <article className="report-list-row" key={row.worker_id}>
              <div className="report-row-head">
                <strong>{row.name}</strong>
                <span>{days(row.total_days)} کارکرد</span>
              </div>
              <dl className="report-labeled-values">
                <div><dt>مبلغ کارکرد</dt><dd>{money(row.total_labor_cost)}</dd></div>
                <div><dt>پرداخت‌شده</dt><dd>{money(row.total_paid)}</dd></div>
                <div><dt>مانده</dt><dd>{money(row.remaining_balance)}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </article>
  );
}

function PayableReportSection({ payables }: { payables: PayableReportRow[] }) {
  return (
    <article className="report-section-card">
      <div className="section-title compact-title">
        <div>
          <span className="eyebrow">بدهی</span>
          <h2>بدهی‌ها و چک‌ها</h2>
        </div>
      </div>
      {payables.length === 0 ? (
        <EmptyState>بدهی یا چکی ثبت نشده است</EmptyState>
      ) : (
        <div className="report-row-list">
          {payables.map((row) => (
            <article className="report-list-row" key={row.id}>
              <div className="report-row-head">
                <strong>{row.name}</strong>
                <span className="report-badge">{REPORT_PAYABLE_KIND_LABELS[row.kind]}</span>
              </div>
              <div className="report-row-amount">{money(row.amount)}</div>
              <p className="report-description">{row.description || "بدون توضیح"}</p>
              {row.due_date && <span className="report-due-date">سررسید: {shortDate(row.due_date)}</span>}
            </article>
          ))}
        </div>
      )}
    </article>
  );
}

export function ProjectDetailPage({
  project, summary, workers, pendingInterpretations, workLogs, payments, invoices, history,
  rawEntries, text, examples, isLoading, onBack, onTextChange, onSubmit,
  onVoicePlaceholder, onAttachPlaceholder, successMessage,
  onConfirmPending, onEditPending, onDiscardPending, requestedTab,
  onCorrectPayment, onVoidPayment, onCorrectWorkLog, onVoidWorkLog,
  onCorrectPayable, onVoidPayable, onCorrectNote, onVoidNote,
  onUpdateProject,
}: ProjectDetailPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("summary");
  const [selectedPersonId, setSelectedPersonId] = useState<number | null>(null);
  const [correctionTarget, setCorrectionTarget] = useState<CorrectionTarget | null>(null);
  const [voidTarget, setVoidTarget] = useState<VoidTarget | null>(null);
  const [isProjectEditOpen, setIsProjectEditOpen] = useState(false);

  useEffect(() => {
    if (!requestedTab) return;
    if (["summary", "people", "labor", "financial", "payables", "notes", "reports", "pending"].includes(requestedTab)) {
      setActiveTab(requestedTab as TabKey);
    }
  }, [requestedTab]);

  const activePayments = useMemo(() => payments.filter((payment) => !payment.is_voided), [payments]);
  const activeWorkLogs = useMemo(() => workLogs.filter((log) => !log.is_voided), [workLogs]);
  const activeInvoices = useMemo(() => invoices.filter((invoice) => !invoice.is_voided), [invoices]);
  const activeHistory = useMemo(() => history.filter((entry) => !entry.is_voided), [history]);
  const paidOut = summary ? Number(summary.total_paid_out) : activePayments.filter((p) => p.direction === "OUTGOING").reduce((t, p) => t + Number(p.amount || 0), 0);
  const received = summary ? Number(summary.total_received_from_client ?? summary.total_received) : activePayments.filter((p) => p.direction === "INCOMING").reduce((t, p) => t + Number(p.amount || 0), 0);
  const payables = Number(summary?.open_payables ?? 0);
  const totalLaborCost = summary ? Number(summary.total_work_amount ?? 0) : activeWorkLogs.reduce((t, log) => t + Number(log.total_amount || 0), 0);
  const cashBalance = received - paidOut;
  const notes = history.filter((entry) => entry.change_type === "NOTE");
  const activeNotes = activeHistory.filter((entry) => entry.change_type === "NOTE");
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

  const laborStatsByWorker = useMemo(() => {
    const stats: Record<number, LaborStats> = {};
    for (const log of activeWorkLogs) {
      const current = stats[log.worker_id] ?? { totalDays: 0, totalCost: 0, paidOut: 0, balance: 0 };
      current.totalDays += Number(log.quantity || 0);
      current.totalCost += Number(log.total_amount || 0);
      stats[log.worker_id] = current;
    }
    for (const payment of activePayments) {
      const worker = workerMap[payment.entity_id];
      if (!worker || worker.type !== "DAILY_WORKER") continue;
      const current = stats[payment.entity_id] ?? { totalDays: 0, totalCost: 0, paidOut: 0, balance: 0 };
      if (payment.direction === "OUTGOING") {
        current.paidOut += Number(payment.amount || 0);
      }
      stats[payment.entity_id] = current;
    }
    for (const item of Object.values(stats)) item.balance = item.totalCost - item.paidOut;
    return stats;
  }, [activePayments, activeWorkLogs, workerMap]);

  const totalLaborDays = useMemo(() => {
    return activeWorkLogs.reduce((total, log) => total + Number(log.unit === "day" ? log.quantity || 0 : 0), 0);
  }, [activeWorkLogs]);

  const dailyWorkerPaidOut = useMemo(() => {
    return Object.values(laborStatsByWorker).reduce((total, stats) => total + stats.paidOut, 0);
  }, [laborStatsByWorker]);

  const workLogsByWorker = useMemo(() => {
    const grouped: Record<number, WorkLog[]> = {};
    for (const log of workLogs) {
      grouped[log.worker_id] = grouped[log.worker_id] ?? [];
      grouped[log.worker_id].push(log);
    }
    for (const logs of Object.values(grouped)) {
      logs.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    }
    return grouped;
  }, [workLogs]);

  const openInvoices = useMemo(() => {
    return activeInvoices.filter((inv) => inv.status === "OPEN" || inv.status === "PARTIAL");
  }, [activeInvoices]);

  const payableInvoices = useMemo(() => {
    return invoices.filter((inv) => inv.is_voided || inv.status === "OPEN" || inv.status === "PARTIAL");
  }, [invoices]);

  const deferredPayments = useMemo(() => {
    return confirmedPayments.filter((payment) => !payment.is_voided && (payment.direction === "DEFERRED" || payment.type === "CHECK"));
  }, [confirmedPayments]);

  const payablePayments = useMemo(() => {
    return confirmedPayments.filter((payment) => payment.direction === "DEFERRED" || payment.type === "CHECK");
  }, [confirmedPayments]);

  const tabs = [
    { key: "summary" as TabKey, label: "خلاصه" },
    { key: "people" as TabKey, label: "افراد", count: workers.length },
    { key: "labor" as TabKey, label: "کارکرد کارگران", count: activeWorkLogs.length },
    { key: "financial" as TabKey, label: "مالی", count: activePayments.length },
    { key: "payables" as TabKey, label: "بدهی‌ها / چک‌ها", count: openInvoices.length + deferredPayments.length },
    { key: "notes" as TabKey, label: "یادداشت‌ها", count: activeNotes.length },
    { key: "reports" as TabKey, label: "گزارش‌ها" },
    { key: "pending" as TabKey, label: "در انتظار تایید", count: pending.length },
  ];

  const valueText = (values: Record<string, FormDataEntryValue>, key: string) => {
    const value = values[key];
    return typeof value === "string" ? value.trim() : "";
  };

  async function submitCorrection(target: CorrectionTarget, values: Record<string, FormDataEntryValue>) {
    if (!project) return;
    if (target.kind === "payment") {
      await onCorrectPayment(project.id, target.record.id, {
        entity_id: Number(valueText(values, "entity_id")),
        amount: valueText(values, "amount"),
        direction: valueText(values, "direction") as Payment["direction"],
        type: valueText(values, "type") as Payment["type"],
        due_date: valueText(values, "due_date") || null,
        description: valueText(values, "description") || null,
        correction_note: valueText(values, "correction_note") || null,
      });
    } else if (target.kind === "workLog") {
      await onCorrectWorkLog(project.id, target.record.id, {
        worker_id: Number(valueText(values, "worker_id")),
        task_name: valueText(values, "task_name"),
        period_label: valueText(values, "period_label") || null,
        unit: valueText(values, "unit") as WorkLog["unit"],
        quantity: valueText(values, "quantity"),
        rate_per_unit: valueText(values, "rate_per_unit") || null,
        description: valueText(values, "description") || null,
        correction_note: valueText(values, "correction_note") || null,
      });
    } else if (target.kind === "payable") {
      await onCorrectPayable(project.id, target.record.id, {
        vendor_id: Number(valueText(values, "vendor_id")),
        total_amount: valueText(values, "total_amount"),
        description: valueText(values, "description") || null,
        correction_note: valueText(values, "correction_note") || null,
      });
    } else {
      await onCorrectNote(project.id, target.record.id, {
        text: valueText(values, "text"),
        correction_note: valueText(values, "correction_note") || null,
      });
    }
    setCorrectionTarget(null);
  }

  async function submitVoid(target: VoidTarget, reason: string) {
    if (!project) return;
    if (target.kind === "payment") await onVoidPayment(project.id, target.record.id, reason);
    else if (target.kind === "workLog") await onVoidWorkLog(project.id, target.record.id, reason);
    else if (target.kind === "payable") await onVoidPayable(project.id, target.record.id, reason);
    else await onVoidNote(project.id, target.record.id, reason);
    setVoidTarget(null);
  }

  async function submitProjectEdit(payload: { name: string; description?: string | null }) {
    if (!project) return;
    await onUpdateProject(project.id, payload);
    setIsProjectEditOpen(false);
  }

  if (!project) {
    return <div className="empty-page">برای شروع، یک پروژه را از خانه باز کنید.</div>;
  }

  return (
    <div className="page-stack project-workspace">
      <section className="project-topbar">
        <button className="icon-button" type="button" onClick={onBack} aria-label="بازگشت"><ChevronRight aria-hidden="true" size={22} /></button>
        <div className="project-title-block min-w-0">
          <span className="eyebrow">جزئیات پروژه</span>
          <h1>{project.name}</h1>
          {project.description && <p>{project.description}</p>}
        </div>
        <button className="icon-button project-edit-button" type="button" onClick={() => setIsProjectEditOpen(true)} aria-label="ویرایش پروژه">
          <Pencil aria-hidden="true" size={18} />
        </button>
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
      </section>

      {successMessage && <div className="success-feedback"><CheckCircle2 aria-hidden="true" size={18} />{successMessage}</div>}

      <TabBar tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />

      {activeTab === "summary" && (
        <div className="detail-tab-content">
          <section className="summary-grid project-summary-grid">
            <button
              className="metric-card summary-action-card positive"
              type="button"
              onClick={() => setActiveTab("financial")}
              aria-label="مشاهده جزئیات دریافتی از کارفرما در تب مالی"
            >
              <ArrowDownCircle aria-hidden="true" />
              <span>دریافتی از کارفرما</span>
              <strong>{money(received)}</strong>
              <small>پول تاییدشده ورودی به پروژه</small>
              <em>مشاهده جزئیات</em>
            </button>
            <button
              className="metric-card summary-action-card negative"
              type="button"
              onClick={() => setActiveTab("financial")}
              aria-label="مشاهده جزئیات پرداخت‌شده در تب مالی"
            >
              <ArrowUpCircle aria-hidden="true" />
              <span>پرداخت‌شده</span>
              <strong>{money(paidOut)}</strong>
              <small>فقط پرداخت واقعی نقدی یا بانکی</small>
              <em>مشاهده جزئیات</em>
            </button>
            <button
              className={cashBalance >= 0 ? "metric-card summary-action-card positive" : "metric-card summary-action-card negative"}
              type="button"
              onClick={() => setActiveTab("financial")}
              aria-label="مشاهده جزئیات موجودی نقدی پروژه در تب مالی"
            >
              <Scale aria-hidden="true" />
              <span>موجودی نقدی پروژه</span>
              <strong>{money(cashBalance)}</strong>
              <small>دریافتی از کارفرما - پرداخت‌شده</small>
              <em>مشاهده جزئیات</em>
            </button>
          </section>
          <button
            className="debt-notice"
            type="button"
            onClick={() => setActiveTab("payables")}
            aria-label="مشاهده جزئیات بدهی باز در تب بدهی‌ها و چک‌ها"
          >
            <ReceiptText aria-hidden="true" />
            <span>بدهی باز</span>
            <strong>{money(payables)}</strong>
            <small>شامل بدهی فروشندگان و مانده کارگران</small>
            <em>مشاهده جزئیات</em>
          </button>
          {pending.length > 0 && (
            <p className="summary-helper">
              {pending.length.toLocaleString("fa-IR")} مورد در انتظار تایید هنوز در اعداد خلاصه حساب نشده است.
            </p>
          )}
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
                      {roleWorkers.map((worker) => <PersonCard key={worker.id} worker={worker} laborStats={laborStatsByWorker[worker.id]} onOpen={setSelectedPersonId} />)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {activeTab === "labor" && (
        <div className="detail-tab-content">
          <section className="summary-grid four-up">
            <article className="metric-card pending">
              <Clock aria-hidden="true" />
              <span>مجموع روزهای کارکرد</span>
              <strong>{days(totalLaborDays)}</strong>
              <small>بر اساس ثبت‌های تاییدشده</small>
            </article>
            <article className="metric-card pending">
              <Hammer aria-hidden="true" />
              <span>مجموع مبلغ کارکرد</span>
              <strong>{money(totalLaborCost)}</strong>
              <small>هزینه کارکرد؛ پرداخت نشده محسوب می‌شود</small>
            </article>
            <article className="metric-card negative">
              <ArrowUpCircle aria-hidden="true" />
              <span>پرداخت‌شده به کارگران</span>
              <strong>{money(dailyWorkerPaidOut)}</strong>
              <small>پرداخت واقعی ثبت‌شده</small>
            </article>
            <article className={totalLaborCost - dailyWorkerPaidOut > 0 ? "metric-card pending" : "metric-card"}>
              <Scale aria-hidden="true" />
              <span>مانده تقریبی کارگران</span>
              <strong>{money(totalLaborCost - dailyWorkerPaidOut)}</strong>
              <small>کارکرد منهای پرداخت به کارگران روزمزد</small>
            </article>
          </section>
          {workLogs.length === 0 ? (
            <EmptyState>کارکردی ثبت نشده است</EmptyState>
          ) : (
            <div className="worker-labor-grid">
              {Object.entries(workLogsByWorker).map(([workerId, logs]) => {
                const worker = workerMap[Number(workerId)];
                if (!worker) return null;
                return (
                  <WorkLogGroupCard
                    key={workerId}
                    worker={worker}
                    logs={logs}
                    laborStats={laborStatsByWorker[Number(workerId)]}
                    onEditLog={(log) => setCorrectionTarget({ kind: "workLog", record: log })}
                    onVoidLog={(log) => setVoidTarget({ kind: "workLog", record: log })}
                  />
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
              {confirmedPayments.map((payment) => (
                <PaymentRow
                  key={payment.id}
                  payment={payment}
                  workerMap={workerMap}
                  onEdit={() => setCorrectionTarget({ kind: "payment", record: payment })}
                  onVoid={() => setVoidTarget({ kind: "payment", record: payment })}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "payables" && (
        <div className="detail-tab-content">
          {payableInvoices.length === 0 && payablePayments.length === 0 && (!summary?.vendor_debts || summary.vendor_debts.length === 0) ? (
            <EmptyState>بدهی یا چک ثبت نشده است</EmptyState>
          ) : (
            <>
              {payableInvoices.length > 0 && (
                <section className="payable-section">
                  <h4 className="role-group-title"><ReceiptText size={14} />بدهی‌های باز</h4>
                  <div className="visibility-trx-list">
                    {payableInvoices.map((invoice) => (
                      <InvoiceRow
                        key={invoice.id}
                        invoice={invoice}
                        workerMap={workerMap}
                        onEdit={() => setCorrectionTarget({ kind: "payable", record: invoice })}
                        onVoid={() => setVoidTarget({ kind: "payable", record: invoice })}
                      />
                    ))}
                  </div>
                </section>
              )}
              {payablePayments.length > 0 && (
                <section className="payable-section">
                  <h4 className="role-group-title"><Banknote size={14} />چک‌ها / پرداخت‌های مدت‌دار</h4>
                  <div className="visibility-trx-list">
                    {payablePayments.map((payment) => (
                      <PaymentRow
                        key={payment.id}
                        payment={payment}
                        workerMap={workerMap}
                        onEdit={() => setCorrectionTarget({ kind: "payment", record: payment })}
                        onVoid={() => setVoidTarget({ kind: "payment", record: payment })}
                      />
                    ))}
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
                <article key={note.id} className={`visibility-note-card${note.is_voided ? " is-voided" : ""}`}>
                  <div className="vpc-meta">
                    <VoidedBadge isVoided={note.is_voided} />
                    <span><Clock size={12} />{shortDate(note.created_at)}</span>
                    {note.void_reason && <span>علت: {note.void_reason}</span>}
                  </div>
                  <p>{note.input_text}</p>
                  <RecordActions disabled={note.is_voided} onEdit={() => setCorrectionTarget({ kind: "note", record: note })} onVoid={() => setVoidTarget({ kind: "note", record: note })} />
                </article>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "reports" && (
        <ProjectReportsTab projectId={project.id} pendingCount={pending.length} />
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
      {selectedPersonId && workerMap[selectedPersonId] && (
        <PersonDetailDrawer
          worker={workerMap[selectedPersonId]}
          laborStats={laborStatsByWorker[selectedPersonId]}
          payments={payments.filter((payment) => payment.entity_id === selectedPersonId)}
          workLogs={workLogs.filter((log) => log.worker_id === selectedPersonId)}
          invoices={invoices.filter((invoice) => invoice.vendor_id === selectedPersonId)}
          vendorDebt={Number(summary?.vendor_debts.find((debt) => debt.vendor_id === selectedPersonId)?.debt ?? 0)}
          onClose={() => setSelectedPersonId(null)}
        />
      )}
      <CorrectionModal
        target={correctionTarget}
        workers={workers}
        isLoading={isLoading}
        onClose={() => setCorrectionTarget(null)}
        onSubmit={submitCorrection}
      />
      <VoidModal
        target={voidTarget}
        isLoading={isLoading}
        onClose={() => setVoidTarget(null)}
        onSubmit={submitVoid}
      />
      {isProjectEditOpen && (
        <ProjectEditModal
          project={project}
          isLoading={isLoading}
          onClose={() => setIsProjectEditOpen(false)}
          onSubmit={submitProjectEdit}
        />
      )}
    </div>
  );
}
