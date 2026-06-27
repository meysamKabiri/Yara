import { useEffect, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, Banknote, Hammer, ReceiptText, Scale } from "lucide-react";
import { api, Project, ProjectReportResponse } from "../api";
import { PersianDatePicker } from "../components/PersianDatePicker";
import { quickReportRange, ReportFilterKey } from "../utils/jalaliDate";

type ReportsPageProps = {
  projects: Project[];
  selectedProjectId: number | null;
  onProjectChange: (projectId: number) => void;
};

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function days(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} روز`;
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString("fa-IR");
}

export function ReportsPage({ projects, selectedProjectId, onProjectChange }: ReportsPageProps) {
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [report, setReport] = useState<ProjectReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null;

  useEffect(() => {
    if (!selectedProjectId) return;
    let cancelled = false;
    setError(null);
    api.getProjectReportSummary(selectedProjectId, { from_date: fromDate || undefined, to_date: toDate || undefined })
      .then((nextReport) => {
        if (!cancelled) setReport(nextReport);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || "خطا در دریافت گزارش");
      });
    return () => {
      cancelled = true;
    };
  }, [fromDate, selectedProjectId, toDate]);

  const applyQuickFilter = (key: ReportFilterKey) => {
    const range = quickReportRange(key);
    setFromDate(range.from_date);
    setToDate(range.to_date);
  };

  if (projects.length === 0) {
    return <div className="page-stack"><p className="empty-state">برای گزارش، ابتدا یک پروژه ایجاد کنید.</p></div>;
  }

  const summary = report?.summary;

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <span className="eyebrow">گزارش‌ها</span>
          <h1>گزارش پروژه</h1>
          <p>گزارش خواندنی از رکوردهای تاییدشده پروژه.</p>
        </div>
        <label className="project-selector">
          <span>پروژه</span>
          <select value={selectedProjectId ?? ""} onChange={(event) => onProjectChange(Number(event.target.value))}>
            {!selectedProjectId && <option value="">انتخاب پروژه</option>}
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
      </section>

      <section className="report-controls" aria-label="بازه گزارش">
        <PersianDatePicker id="global-report-from" label="از تاریخ" value={fromDate} onChange={setFromDate} />
        <PersianDatePicker id="global-report-to" label="تا تاریخ" value={toDate} onChange={setToDate} />
        <div className="quick-filter-group" aria-label="فیلتر سریع">
          <button type="button" onClick={() => applyQuickFilter("week")}>این هفته</button>
          <button type="button" onClick={() => applyQuickFilter("month")}>این ماه</button>
          <button type="button" onClick={() => applyQuickFilter("year")}>امسال</button>
          <button type="button" onClick={() => applyQuickFilter("all")}>همه</button>
        </div>
      </section>

      {error && <p className="empty-state">{error}</p>}
      {summary && (
        <>
          <section className="summary-grid six-up project-summary-grid">
            <article className="metric-card positive"><ArrowDownCircle aria-hidden="true" /><span>دریافتی</span><strong>{money(summary.money_in)}</strong><small>{selectedProject?.name}</small></article>
            <article className="metric-card negative"><ArrowUpCircle aria-hidden="true" /><span>پرداخت‌شده واقعی</span><strong>{money(summary.paid_out)}</strong><small>بدون چک و بدهی مدت‌دار</small></article>
            <article className="metric-card pending"><Hammer aria-hidden="true" /><span>کارکرد ثبت‌شده</span><strong>{money(summary.labor_cost)}</strong><small>هزینه کارکرد تاییدشده</small></article>
            <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>بدهی باز</span><strong>{money(summary.open_payables)}</strong><small>فروشنده + کارکرد پرداخت‌نشده</small></article>
            <article className="metric-card pending"><Banknote aria-hidden="true" /><span>چک / مدت‌دار</span><strong>{money(summary.deferred_checks)}</strong><small>جدا از پرداخت‌شده واقعی</small></article>
            <article className={Number(summary.approximate_balance) >= 0 ? "metric-card positive" : "metric-card negative"}><Scale aria-hidden="true" /><span>مانده تقریبی</span><strong>{money(summary.approximate_balance)}</strong><small>دریافتی - پرداختی - بدهی باز</small></article>
          </section>
          <p className="summary-helper">موارد در انتظار تایید فقط جداگانه شمرده می‌شوند: {summary.pending_count.toLocaleString("fa-IR")}</p>
          <section className="content-grid two-column">
            <article className="panel-card">
              <div className="section-title"><div><span className="eyebrow">کارفرما</span><h2>پرداخت‌های کارفرما</h2></div></div>
              <div className="mini-list">
                {report.client_payments.map((row) => <div className="mini-row" key={row.entity_id}><strong>{row.name}</strong><span>{money(row.total_paid)} / {row.payment_count.toLocaleString("fa-IR")} پرداخت / {row.last_payment_at ? shortDate(row.last_payment_at) : "-"}</span></div>)}
                {report.client_payments.length === 0 && <p className="empty-state">پرداختی از کارفرما ثبت نشده است</p>}
              </div>
            </article>
            <article className="panel-card">
              <div className="section-title"><div><span className="eyebrow">کارگران</span><h2>گزارش کارگران</h2></div></div>
              <div className="mini-list">
                {report.workers.map((row) => <div className="mini-row" key={row.worker_id}><strong>{row.name}</strong><span>{days(row.total_days)} / کارکرد {money(row.total_labor_cost)} / مانده {money(row.remaining_balance)}</span></div>)}
                {report.workers.length === 0 && <p className="empty-state">کارکردی برای کارگران ثبت نشده است</p>}
              </div>
            </article>
            <article className="panel-card">
              <div className="section-title"><div><span className="eyebrow">بدهی</span><h2>بدهی‌ها و چک‌ها</h2></div></div>
              <div className="mini-list">
                {report.payables.map((row) => <div className="mini-row" key={row.id}><strong>{row.name}</strong><span>{money(row.amount)} / {row.due_date || row.description || "بدون توضیح"}</span></div>)}
                {report.payables.length === 0 && <p className="empty-state">بدهی یا چکی ثبت نشده است</p>}
              </div>
            </article>
          </section>
        </>
      )}
    </div>
  );
}
