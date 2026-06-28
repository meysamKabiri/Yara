import { useEffect, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, ReceiptText, Scale } from "lucide-react";
import { api, PayableReportRow, Project, ProjectReportResponse, WorkerReportRow } from "../api";
import { PersianDatePicker } from "../components/PersianDatePicker";
import { quickReportRange, ReportFilterKey } from "../utils/jalaliDate";

type ReportsPageProps = {
  projects: Project[];
  selectedProjectId: number | null;
  onProjectChange: (projectId: number) => void;
};

const CSV_EXPORTS = [
  { label: "خلاصه پروژه", path: "summary.csv" },
  { label: "پرداخت‌ها", path: "payments.csv" },
  { label: "افراد", path: "people.csv" },
  { label: "کارکرد کارگران", path: "work-logs.csv" },
  { label: "بدهی‌ها و چک‌ها", path: "payables.csv" },
  { label: "یادداشت‌ها", path: "notes.csv" },
];

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function days(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} روز`;
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString("fa-IR");
}

function exportHref(projectId: number, path: string, fromDate: string, toDate: string): string {
  const params = new URLSearchParams();
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  const query = params.toString();
  return `/api/projects/${projectId}/exports/${path}${query ? `?${query}` : ""}`;
}

const REPORT_PAYABLE_KIND_LABELS: Record<PayableReportRow["kind"], string> = {
  vendor_payable: "بدهی باز",
  deferred_check: "چک / پرداخت مدت‌دار",
  worker_labor: "کارکرد پرداخت‌نشده",
};

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

function WorkerReportRows({ workers }: { workers: WorkerReportRow[] }) {
  if (workers.length === 0) return <p className="empty-state">کارکردی برای کارگران ثبت نشده است</p>;
  return (
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
  );
}

function PayableReportRows({ payables }: { payables: PayableReportRow[] }) {
  if (payables.length === 0) return <p className="empty-state">بدهی یا چکی ثبت نشده است</p>;
  return (
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
  );
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
  const cashBalance = summary ? Number(summary.money_in) - Number(summary.paid_out) : 0;

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

      {selectedProjectId && (
        <div className="report-actions-row">
          <CsvExportMenu projectId={selectedProjectId} fromDate={fromDate} toDate={toDate} />
        </div>
      )}

      {error && <p className="empty-state">{error}</p>}
      {summary && (
        <>
          <section className="report-summary-grid">
            <article className="metric-card positive"><ArrowDownCircle aria-hidden="true" /><span>دریافتی</span><strong>{money(summary.money_in)}</strong><small>{selectedProject?.name}</small></article>
            <article className="metric-card negative"><ArrowUpCircle aria-hidden="true" /><span>پرداخت‌شده</span><strong>{money(summary.paid_out)}</strong><small>بدون چک و بدهی مدت‌دار</small></article>
            <article className={cashBalance >= 0 ? "metric-card positive" : "metric-card negative"}><Scale aria-hidden="true" /><span>موجودی نقدی</span><strong>{money(cashBalance)}</strong><small>دریافتی - پرداخت‌شده</small></article>
          </section>
          <aside className="debt-notice report-debt-notice" aria-label="بدهی باز">
            <ReceiptText aria-hidden="true" />
            <span>بدهی باز</span>
            <strong>{money(summary.open_payables)}</strong>
            <small>شامل بدهی فروشندگان و مانده کارگران</small>
          </aside>
          <p className="summary-helper">موارد در انتظار تایید فقط جداگانه شمرده می‌شوند: {summary.pending_count.toLocaleString("fa-IR")}</p>
          <section className="report-sections">
            <article className="report-section-card">
              <div className="section-title"><div><span className="eyebrow">کارفرما</span><h2>پرداخت‌های کارفرما</h2></div></div>
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
                {report.client_payments.length === 0 && <p className="empty-state">پرداختی از کارفرما ثبت نشده است</p>}
              </div>
            </article>
            <article className="report-section-card">
              <div className="section-title"><div><span className="eyebrow">کارگران</span><h2>گزارش کارگران</h2></div></div>
              <WorkerReportRows workers={report.workers} />
            </article>
            <article className="report-section-card">
              <div className="section-title"><div><span className="eyebrow">بدهی</span><h2>بدهی‌ها و چک‌ها</h2></div></div>
              <PayableReportRows payables={report.payables} />
            </article>
          </section>
        </>
      )}
    </div>
  );
}
