import { FormEvent } from "react";
import { ArrowDownCircle, ArrowUpCircle, ChevronRight, Coins, Mic, Paperclip, ReceiptText, Scale, Send, Wallet } from "lucide-react";
import { HistoryEntry, Invoice, OperatingSummary, Payment, ProjectDetail, RawEntry, WorkLog } from "../api";

type ProjectDetailPageProps = {
  project: ProjectDetail | null;
  summary: OperatingSummary | null;
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
};

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function date(value: string): string {
  return new Date(value).toLocaleString("fa-IR");
}

export function ProjectDetailPage({ project, summary, workLogs, payments, invoices, history, rawEntries, text, examples, isLoading, onBack, onTextChange, onSubmit, onVoicePlaceholder, onAttachPlaceholder }: ProjectDetailPageProps) {
  const paidOut = Number(summary?.total_paid_out ?? 0) || payments.filter((payment) => payment.direction === "OUTGOING" || payment.direction === "DEFERRED").reduce((total, payment) => total + Number(payment.amount || 0), 0);
  const received = Number(summary?.total_received_from_client ?? summary?.total_received ?? 0) || payments.filter((payment) => payment.direction === "INCOMING").reduce((total, payment) => total + Number(payment.amount || 0), 0);
  const payables = Number(summary?.open_payables ?? 0);
  const totalCost = Number(summary?.total_work_amount ?? 0) + Number(summary?.total_invoice_amount ?? 0) + paidOut;
  const receivables = Number(summary?.client_receivable ?? Math.max(paidOut + payables - received, 0));
  const availableBalance = Number(summary?.available_balance ?? Math.max(received - paidOut - payables, 0));
  const netBalance = Number(summary?.project_balance ?? received - paidOut - payables);
  const recent = [...history].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 10);

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

      <section className="summary-grid six-up">
        <article className="metric-card negative"><Coins aria-hidden="true" /><span>هزینه کل</span><strong>{money(totalCost)}</strong><small>کار، فاکتور و پرداختی</small></article>
        <article className="metric-card positive"><ArrowDownCircle aria-hidden="true" /><span>دریافتی از کارفرما</span><strong>{money(received)}</strong><small>ورودی تاییدشده</small></article>
        <article className="metric-card negative"><ArrowUpCircle aria-hidden="true" /><span>پرداختی‌ها</span><strong>{money(paidOut)}</strong><small>کارگر، فروشنده و خرید</small></article>
        <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>طلب‌ها</span><strong>{money(receivables)}</strong><small>طلب از کارفرما بابت کسری پروژه</small></article>
        <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>بدهی‌ها</span><strong>{money(payables)}</strong><small>فقط فاکتورهای پرداخت‌نشده</small></article>
        <article className={netBalance >= 0 ? "metric-card positive" : "metric-card negative"}><Scale aria-hidden="true" /><span>مانده پروژه</span><strong>{money(netBalance >= 0 ? availableBalance : netBalance)}</strong><small>{netBalance >= 0 ? "موجودی قابل خرج" : "کسری تامین مالی"}</small></article>
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

      <section className="panel-card recent-activity">
        <div className="section-title">
          <div>
            <span className="eyebrow">فعالیت اخیر</span>
            <h2>خط زمان</h2>
          </div>
        </div>
        <div className="timeline-list">
          {recent.map((entry) => (
            <article className="timeline-card" key={entry.id}>
              <span>{date(entry.created_at)}</span>
              <strong>{entry.change_type}</strong>
              <p>{entry.input_text}</p>
            </article>
          ))}
          {recent.length === 0 && rawEntries.length === 0 && <p className="empty-state">هنوز فعالیتی ثبت نشده است. از ورودی هوشمند بالا شروع کنید.</p>}
        </div>
      </section>

      <section className="supporting-records">
        <article className="panel-card"><Wallet aria-hidden="true" /><span className="eyebrow">کارکردها</span><strong>{workLogs.length}</strong></article>
        <article className="panel-card"><ArrowUpCircle aria-hidden="true" /><span className="eyebrow">پرداخت‌ها</span><strong>{payments.length}</strong></article>
        <article className="panel-card"><ReceiptText aria-hidden="true" /><span className="eyebrow">فاکتورها</span><strong>{invoices.length}</strong></article>
      </section>
    </div>
  );
}
