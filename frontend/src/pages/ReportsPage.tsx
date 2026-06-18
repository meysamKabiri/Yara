import { ArrowDownCircle, ArrowUpCircle, BarChart3, ReceiptText, TrendingUp } from "lucide-react";
import { Invoice, OperatingSummary, Payment, Project, ProjectDetail, Worker, WorkerState } from "../api";

type ReportsPageProps = {
  projects: Project[];
  project: ProjectDetail | null;
  summary: OperatingSummary | null;
  workers: Worker[];
  workerStates: WorkerState[];
  payments: Payment[];
  invoices: Invoice[];
};

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function barWidth(value: number, max: number): string {
  if (max <= 0) return "0%";
  return `${Math.max(4, Math.min(100, (value / max) * 100))}%`;
}

export function ReportsPage({ projects, project, summary, workers, workerStates, payments, invoices }: ReportsPageProps) {
  const incoming = payments.filter((payment) => payment.direction === "INCOMING").reduce((total, payment) => total + Number(payment.amount || 0), 0);
  const outgoing = payments.filter((payment) => payment.direction === "OUTGOING").reduce((total, payment) => total + Number(payment.amount || 0), 0);
  const profitability = incoming - outgoing - Number(summary?.total_invoice_amount ?? 0);
  const dailyWorkerCosts = workerStates.filter((state) => state.role === "DAILY");
  const skilledWorkerCosts = workerStates.filter((state) => state.role === "SKILLED");
  const vendorCosts = summary?.vendor_debts ?? [];
  const maxDailyWorkerBalance = Math.max(...dailyWorkerCosts.map((state) => Math.abs(Number(state.financial_balance || 0))), 1);
  const maxSkilledWorkerBalance = Math.max(...skilledWorkerCosts.map((state) => Math.abs(Number(state.financial_balance || 0))), 1);
  const maxVendorDebt = Math.max(...vendorCosts.map((debt) => Number(debt.debt || 0)), 1);

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <span className="eyebrow">گزارش‌ها</span>
          <h1>گزارش مالی</h1>
          <p>جریان پول، سود و هزینه‌های مهم پروژه‌ها.</p>
        </div>
      </section>

      <section className="summary-grid">
        <article className={profitability >= 0 ? "metric-card positive" : "metric-card negative"}>
          <TrendingUp aria-hidden="true" />
          <span>سود/زیان پروژه</span>
          <strong>{money(profitability)}</strong>
          <small>{project?.name ?? "پروژه‌ای انتخاب نشده"}</small>
        </article>
        <article className="metric-card positive"><ArrowDownCircle aria-hidden="true" /><span>ورود پول</span><strong>{money(incoming)}</strong><small>{payments.filter((payment) => payment.direction === "INCOMING").length} پرداخت ورودی</small></article>
        <article className="metric-card negative"><ArrowUpCircle aria-hidden="true" /><span>خروج پول</span><strong>{money(outgoing)}</strong><small>{payments.filter((payment) => payment.direction === "OUTGOING").length} پرداخت خروجی</small></article>
        <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>فاکتورها</span><strong>{money(summary?.total_invoice_amount)}</strong><small>{invoices.length} فاکتور</small></article>
      </section>

      <section className="content-grid two-column">
        <article className="panel-card">
          <div className="section-title"><div><span className="eyebrow inline-icon"><BarChart3 aria-hidden="true" size={18} />ورود و خروج پول</span><h2>جریان نقدی</h2></div></div>
          <div className="bar-list">
            <div className="bar-row"><span>ورودی</span><div><i className="bar positive" style={{ width: barWidth(incoming, Math.max(incoming, outgoing, 1)) }} /></div><strong>{money(incoming)}</strong></div>
            <div className="bar-row"><span>خروجی</span><div><i className="bar negative" style={{ width: barWidth(outgoing, Math.max(incoming, outgoing, 1)) }} /></div><strong>{money(outgoing)}</strong></div>
          </div>
        </article>

        <article className="panel-card">
          <div className="section-title"><div><span className="eyebrow">پروژه‌ها</span><h2>{projects.length} پروژه</h2></div></div>
          <div className="mini-list">
            {projects.map((item) => <button className={item.id === project?.id ? "mini-row active" : "mini-row"} key={item.id} type="button">{item.name}<span>{new Date(item.updated_at).toLocaleDateString("fa-IR")}</span></button>)}
          </div>
        </article>
      </section>

      <section className="content-grid two-column">
        <article className="panel-card">
          <div className="section-title"><div><span className="eyebrow">هزینه کارگرها</span><h2>جزئیات</h2></div></div>
          <div className="bar-list">
            {dailyWorkerCosts.map((state) => {
              const amount = Math.abs(Number(state.financial_balance || 0));
              return <div className="bar-row" key={state.id}><span>{state.name}</span><div><i className="bar pending" style={{ width: barWidth(amount, maxDailyWorkerBalance) }} /></div><strong>{money(amount)}</strong></div>;
            })}
            {dailyWorkerCosts.length === 0 && <p className="empty-state">هنوز هزینه کارگری ثبت نشده است.</p>}
          </div>
        </article>

        <article className="panel-card">
          <div className="section-title"><div><span className="eyebrow">هزینه استادکارها</span><h2>جزئیات</h2></div></div>
          <div className="bar-list">
            {skilledWorkerCosts.map((state) => {
              const amount = Math.abs(Number(state.financial_balance || 0));
              return <div className="bar-row" key={state.id}><span>{state.name}</span><div><i className="bar pending" style={{ width: barWidth(amount, maxSkilledWorkerBalance) }} /></div><strong>{money(amount)}</strong></div>;
            })}
            {skilledWorkerCosts.length === 0 && <p className="empty-state">هنوز هزینه استادکاری ثبت نشده است.</p>}
          </div>
        </article>
      </section>

      <section className="content-grid two-column">
        <article className="panel-card">
          <div className="section-title"><div><span className="eyebrow">هزینه فروشنده‌ها</span><h2>جزئیات</h2></div></div>
          <div className="bar-list">
            {vendorCosts.map((debt) => <div className="bar-row" key={debt.vendor_id}><span>{debt.vendor_name}</span><div><i className="bar negative" style={{ width: barWidth(Number(debt.debt || 0), maxVendorDebt) }} /></div><strong>{money(debt.debt)}</strong></div>)}
            {vendorCosts.length === 0 && <p className="empty-state">هنوز هزینه فروشنده ثبت نشده است.</p>}
          </div>
        </article>
      </section>
    </div>
  );
}
